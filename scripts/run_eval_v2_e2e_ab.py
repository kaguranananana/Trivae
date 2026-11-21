"""End-to-end A/B evaluation harness for eval@v2 (24 real-user cases on frozen-20261028-validated).

Compares:
  - baseline: pre-ce553277 dual-layer semantic time truncation (R2 + R6 reverted) and strict JSON
    parsing without unescaped-quote repair.
  - candidate: current main (R2 + R6 rank-preserving semantic retention + observable JSON quote repair).

Both arms share the exact same frozen snapshot, DeepSeek Flash model, current SYSTEM_PROMPT,
7 retrieval tools, and fixed 128K context / 32K shared tool-evidence budget, and run in isolated
APFS workspaces via EvaluationWorkspace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
import types
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "data/evaluation/eval-v2-20261122"
SUITE_PATH = ROOT / "evaluation/suites/eval-v2.json"
FREEZE_MANIFEST = ROOT / "data/evaluation/frozen-20261028-validated/freeze.json"
FROZEN_DB = ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3"
MODELS_CONFIG = ROOT / "config/models.yaml"
PRE_FIX_COMMIT = "ce553277~1"

FORMAL_BUDGET_ENV = {
    "TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS": "128000",
    "TRIVAE_RUN_TOOL_EVIDENCE_BUDGET": "32000",
    "TRIVAE_PER_CALL_TOOL_RESULT_PERCENT": "50",
    "TRIVAE_PER_CALL_TOOL_RESULT_CAP": "128000",
    "TRIVAE_RUN_TOOL_EVIDENCE_PERCENT": "25",
    "TRIVAE_RUN_TOOL_EVIDENCE_CAP": "256000",
    "TRIVAE_TOOL_RESULT_BUDGET_MODE": "dynamic",
    "TRIVAE_MAX_TOOL_ROUNDS": "6",
    "TRIVAE_MAX_TURNS": "8",
    "TRIVAE_MAX_OUTPUT_TOKENS": "16384",
    "TRIVAE_COMPLETION_MAX_TOKENS": "2048",
    "TRIVAE_ROUTER_JEV_ENABLED": "false",
}


def _now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _install_baseline_patches() -> None:
    """Revert R2, R6, and JSON quote repair inside the isolated baseline subprocess ONLY."""

    # 1. Disable JSON unescaped-quote repair across all call sites.
    import trivae.query.evidence as evidence_mod
    import trivae.query.json_repair as json_repair_mod
    import trivae.query.orchestrator as orchestrator_mod
    import trivae.query.streaming as streaming_mod

    def _disabled_repair(_raw: str) -> None:
        return None

    json_repair_mod.repair_unescaped_json_quotes = _disabled_repair  # type: ignore[assignment]
    streaming_mod.repair_unescaped_json_quotes = _disabled_repair  # type: ignore[assignment]
    evidence_mod.repair_unescaped_json_quotes = _disabled_repair  # type: ignore[assignment]
    orchestrator_mod.repair_unescaped_json_quotes = _disabled_repair  # type: ignore[assignment]

    # 2. Revert R2 (SemanticRetrieval capacity truncation to pre-ce553277 time order).
    source = subprocess.run(
        ["git", "show", f"{PRE_FIX_COMMIT}:src/trivae/retrieval/semantic/retrieval.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    module = types.ModuleType("trivae.retrieval.semantic._ab_baseline_retrieval")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{PRE_FIX_COMMIT}:retrieval.py", "exec"), module.__dict__)
    baseline_semantic_cls = module.SemanticRetrieval

    import trivae.retrieval as retrieval_pkg
    import trivae.retrieval.semantic as semantic_pkg
    import trivae.retrieval.semantic.retrieval as retrieval_mod

    retrieval_mod.SemanticRetrieval = baseline_semantic_cls  # type: ignore[misc]
    semantic_pkg.SemanticRetrieval = baseline_semantic_cls  # type: ignore[misc]
    retrieval_pkg.SemanticRetrieval = baseline_semantic_cls  # type: ignore[misc]

    # 3. Revert R6 (Host budget hit pruning back to canonical time order for SemanticRetrievalResult).
    from trivae.retrieval.semantic.contracts import SemanticRetrievalResult

    orig_project = evidence_mod.project_tool_result_for_model

    def _baseline_project_tool_result_for_model(envelope: Any, record: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(envelope.data, SemanticRetrievalResult):
            primary_set = set(envelope.data.primary_message_ids)
            canonical_primaries = tuple(
                item.message.internal_message_id
                for item in record.message_items
                if item.message.internal_message_id in primary_set
            )
            reverted_data = replace(envelope.data, primary_message_ids=canonical_primaries)
            envelope = replace(envelope, data=reverted_data)
        return orig_project(envelope, record, *args, **kwargs)

    evidence_mod.project_tool_result_for_model = _baseline_project_tool_result_for_model  # type: ignore[assignment]


def _verify_arm_wiring(arm: str) -> None:
    """Zero-API-cost self-check confirming baseline/candidate execute their exact intended code paths."""

    import trivae.bootstrap.application as app_mod
    import trivae.query.evidence as evidence_mod
    import trivae.query.runtime.openai_tools as tools_mod
    import trivae.query.streaming as streaming_mod
    from trivae.query.evidence import finalize_answer_gracefully

    raw_quote_bad = (
        '{"claims":[{"text":"关键不是"不断提醒"","finding":"f","criterion":"c",'
        '"sufficiency":"sufficient","sources":[],"limitations":[]}],"limitations":[]}'
    )
    probe_json = evidence_mod.repair_unescaped_json_quotes(raw_quote_bad)
    probe_stream = streaming_mod.repair_unescaped_json_quotes(raw_quote_bad)

    if arm == "baseline":
        assert app_mod.SemanticRetrieval.__module__ == "trivae.retrieval.semantic._ab_baseline_retrieval", (
            f"baseline SemanticRetrieval not wired into application: {app_mod.SemanticRetrieval.__module__}"
        )
        assert tools_mod.project_tool_result_for_model is evidence_mod.project_tool_result_for_model
        assert tools_mod.project_tool_result_for_model.__name__ == "_baseline_project_tool_result_for_model"
        assert probe_json is None and probe_stream is None
        res = finalize_answer_gracefully(raw_quote_bad, run_id="r", tool_results=(), scope=app_mod.ExecutionScope())
        assert res.error is not None and res.error.code == "INVALID_ANSWER_ARTIFACT"
    else:
        assert app_mod.SemanticRetrieval.__module__ == "trivae.retrieval.semantic.retrieval"
        assert tools_mod.project_tool_result_for_model.__name__ == "project_tool_result_for_model"
        assert probe_json is not None and probe_stream is not None
        res = finalize_answer_gracefully(raw_quote_bad, run_id="r", tool_results=(), scope=app_mod.ExecutionScope())
        assert res.error is None and res.diagnostics.degradation_codes == ("repaired_unescaped_json_quotes",)
    print(f"[{arm}] wiring self-check PASSED", flush=True)


def _extract_trace_telemetry(trace_dict: dict[str, Any]) -> dict[str, Any]:
    timeline = trace_dict.get("timeline", [])
    semantic_calls = 0
    semantic_capacity_truncated = 0
    semantic_host_omitted_hits = 0
    semantic_host_omitted_context = 0
    semantic_host_truncated = 0
    lexical_calls = 0
    recent_calls = 0
    context_calls = 0
    budget_errors = 0
    quote_repaired = False
    quote_repair_count = 0
    parse_error = False
    tool_calls_total = 0

    for event in timeline:
        op = event.get("operation", "")
        payload = event.get("payload", {}) or {}
        if op == "tool.call.completed":
            tool_calls_total += 1
            tname = payload.get("tool_name")
            if tname == "semantic_search":
                semantic_calls += 1
            elif tname == "lexical_search":
                lexical_calls += 1
            elif tname == "get_recent_messages":
                recent_calls += 1
            elif tname == "get_message_context":
                context_calls += 1
            if payload.get("error_code") == "TOOL_RESULT_BUDGET_EXHAUSTED":
                budget_errors += 1
        elif op == "runtime.tool.completed":
            tname = payload.get("tool_name")
            if payload.get("tool_error_code") == "TOOL_RESULT_BUDGET_EXHAUSTED":
                budget_errors += 1
            if tname == "semantic_search":
                omitted_hits = int(payload.get("omitted_hit_messages") or 0)
                omitted_ctx = int(payload.get("omitted_context_messages") or 0)
                if omitted_hits > 0:
                    semantic_host_omitted_hits += omitted_hits
                if omitted_ctx > 0:
                    semantic_host_omitted_context += omitted_ctx
                if payload.get("projection_truncated"):
                    semantic_host_truncated += 1
        elif op == "retrieval.search.completed":
            if payload.get("strategy") == "semantic" and payload.get("truncated"):
                semantic_capacity_truncated += 1
        elif op == "answer.finalization.completed":
            codes = payload.get("degradation_codes") or []
            if "repaired_unescaped_json_quotes" in codes:
                quote_repaired = True
                quote_repair_count = int(payload.get("normalization_count") or 0)
        elif op == "answer.parse.failed":
            parse_error = True

    return {
        "tool_calls_total": tool_calls_total,
        "semantic_calls": semantic_calls,
        "semantic_capacity_truncated": semantic_capacity_truncated,
        "semantic_host_truncated": semantic_host_truncated,
        "semantic_host_omitted_hits": semantic_host_omitted_hits,
        "semantic_host_omitted_context": semantic_host_omitted_context,
        "semantic_truncation_affected": (
            semantic_capacity_truncated > 0 or semantic_host_truncated > 0 or semantic_host_omitted_hits > 0
        ),
        "lexical_calls": lexical_calls,
        "recent_calls": recent_calls,
        "context_calls": context_calls,
        "budget_errors": budget_errors,
        "quote_repaired": quote_repaired,
        "quote_repair_count": quote_repair_count,
        "answer_parse_failed": parse_error,
    }


def _read_lossless_answer_artifact(workspace_db: Path, conversation_id: str | None) -> dict[str, Any] | None:
    if not conversation_id:
        return None
    con = sqlite3.connect(workspace_db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT answer_artifact_json FROM conversation_messages "
            "WHERE conversation_id = ? AND role = 'assistant' ORDER BY ordinal",
            (conversation_id,),
        ).fetchall()
    finally:
        con.close()
    if len(rows) != 1 or not rows[0][0]:
        return None
    return json.loads(rows[0][0])


def _is_transient_transport_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc)
    if name in {"APIConnectionError", "APITimeoutError", "ConnectError", "ReadTimeout", "RemoteProtocolError"}:
        return True
    if "Connection error" in msg or "ConnectError" in msg or "ReadTimeout" in msg:
        return True
    return False


async def _run_arm_async(arm: str, record_dir: Path, case_filter: list[str] | None) -> None:
    # Apply formal budget overrides BEFORE loading settings.
    for key, val in FORMAL_BUDGET_ENV.items():
        os.environ[key] = val

    if arm == "baseline":
        _install_baseline_patches()

    from trivae.bootstrap.application import create_application
    from trivae.config.dotenv import load_environment_file
    from trivae.config.settings import load_settings
    from trivae.evaluation.capability_conditions import FORMAL_RUNTIME, FORMAL_TOOLS
    from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationSuite
    from trivae.evaluation.variant import ControlledVariant
    from trivae.evaluation.workspace import EvaluationWorkspace

    _verify_arm_wiring(arm)
    load_environment_file(None)
    # Re-apply formal budget overrides after dotenv load so local .env (e.g. 200K shared) never leaks.
    for key, val in FORMAL_BUDGET_ENV.items():
        os.environ[key] = val

    agent_settings = load_settings(model_id="deepseek-flash", role="agent", config_path=MODELS_CONFIG)
    safe_cfg = agent_settings.to_safe_dict()
    assert safe_cfg["run_tool_evidence_budget"] == 32000, f"unexpected budget: {safe_cfg}"
    assert safe_cfg["model_context_window_tokens"] == 128000, f"unexpected context: {safe_cfg}"
    assert agent_settings.provider == "deepseek" and agent_settings.model_name == "deepseek-flash"

    suite = EvaluationSuite.from_json(SUITE_PATH)
    cases: dict[str, EvaluationCaseBundle] = {}
    for p in sorted((BUNDLE_DIR / "cases").glob("*.json")):
        c = EvaluationCaseBundle.from_json(p)
        cases[c.identity] = c

    freeze_data = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    index_identity = json.dumps(freeze_data["index_state"]["semantic_index"], ensure_ascii=False, sort_keys=True)
    commit = _git_head()

    variant = ControlledVariant(
        variant_id=f"eval-v2-ab-{arm}",
        role="last_stable" if arm == "baseline" else "candidate",
        code_version=commit,
        provider="deepseek",
        model="deepseek-flash",
        model_parameters={},
        prompt_identity="bef01f27-evidence-constraints",
        router_configuration={"jev_enabled": False},
        planner_configuration={},
        runtime_configuration={"trace_profile": "normal"},
        available_tools=FORMAL_TOOLS,
        retrieval_configuration={
            "surface": "agent-facing",
            "semantic_core_retention": "time_order_pre_ce553277" if arm == "baseline" else "literal_then_rank",
            "host_primary_retention": "time_order_pre_ce553277" if arm == "baseline" else "literal_then_rank",
            "json_quote_repair": "disabled" if arm == "baseline" else "enabled_observable",
        },
        index_identity=index_identity,
        context_expansion_configuration={"context_window_limit": None},
        evidence_citation_version="production-default",
        budget=dict(FORMAL_RUNTIME),
    )

    record_dir.mkdir(parents=True, exist_ok=True)
    cases_out = record_dir / "cases"
    cases_out.mkdir(exist_ok=True)
    eval_db = record_dir / "evaluation.sqlite3"
    retry_log = record_dir / "transport-retries.jsonl"

    target_refs = list(suite.case_references)
    if case_filter:
        allowed = set(case_filter)
        target_refs = [ref for ref in target_refs if ref.case_id in allowed or ref.identity in allowed]

    with EvaluationWorkspace.create(FREEZE_MANIFEST) as workspace:
        async with create_application(
            workspace.database_path,
            agent_settings=agent_settings,
            evaluation_database_path=eval_db,
            semantic_index_path=workspace.semantic_index_path,
        ) as app:
            for idx, ref in enumerate(target_refs, 1):
                case = cases[ref.identity]
                cdir = cases_out / case.case_id
                summary_path = cdir / "summary.json"
                if summary_path.exists():
                    prev = json.loads(summary_path.read_text(encoding="utf-8"))
                    print(f"[{arm}] ({idx:02d}/{len(target_refs)}) SKIP {case.case_id} (already {prev['terminal_status']})", flush=True)
                    continue

                cdir.mkdir(parents=True, exist_ok=True)
                started = time.perf_counter()
                run = None
                raised_exc: BaseException | None = None

                for attempt in range(1, 4):
                    try:
                        runs = await app.evaluate_suite(
                            suite, cases, variant, repetitions=1, selected_cases=[case.identity]
                        )
                        run = runs[-1]
                        raised_exc = None
                        break
                    except (TypeError, AttributeError, NameError, SyntaxError, ImportError):
                        raise
                    except BaseException as exc:
                        raised_exc = exc
                        print(
                            f"[{arm}] error on {case.case_id} (attempt {attempt}): {type(exc).__name__}: {str(exc)[:200]}",
                            flush=True,
                        )
                        if _is_transient_transport_error(exc) and attempt < 3:
                            with retry_log.open("a", encoding="utf-8") as fh:
                                fh.write(
                                    json.dumps(
                                        {
                                            "at": _now_iso(),
                                            "arm": arm,
                                            "case_id": case.case_id,
                                            "attempt": attempt,
                                            "error_type": type(exc).__name__,
                                            "message": str(exc)[:300],
                                        },
                                        ensure_ascii=False,
                                    )
                                    + "\n"
                                )
                            await asyncio.sleep(5 * attempt)
                            continue
                        # Find the persisted run recorded before exception was re-raised.
                        all_saved = app.evaluation_store.list_runs()
                        matching = [r for r in all_saved if r.case_id == case.case_id]
                        if matching:
                            run = matching[-1]
                        break

                elapsed = round(time.perf_counter() - started, 2)
                trace_dict: dict[str, Any] | None = None
                artifact: dict[str, Any] | None = None
                telemetry: dict[str, Any] = {}

                if run is not None:
                    (cdir / "run.json").write_text(
                        json.dumps(run.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                    )
                    if run.trace_id:
                        trace = app.read_trace(run.trace_id)
                        trace_dict = asdict(trace)
                        (cdir / "trace.json").write_text(
                            json.dumps(trace_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                        )
                        telemetry = _extract_trace_telemetry(trace_dict)
                    if run.terminal_status == "completed" and run.query_result:
                        conv_id = run.query_result.get("conversation_id")
                        artifact = _read_lossless_answer_artifact(workspace.database_path, conv_id)
                        if artifact is not None:
                            (cdir / "answer_artifact.json").write_text(
                                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                            )

                summary = {
                    "arm": arm,
                    "case_id": case.case_id,
                    "case_version": case.version,
                    "run_id": None if run is None else run.run_id,
                    "trace_id": None if run is None else run.trace_id,
                    "terminal_status": "exception" if run is None else run.terminal_status,
                    "finalization_status": (
                        None if (run is None or not run.query_result) else run.query_result.get("finalization_status")
                    ),
                    "error_type": None if raised_exc is None else type(raised_exc).__name__,
                    "runtime_error": (
                        None
                        if (run is None or not run.query_result)
                        else run.query_result.get("runtime_error")
                    ),
                    "has_lossless_artifact": artifact is not None,
                    "usage": None if run is None else run.operational_measurements.get("usage"),
                    "latency_seconds": elapsed,
                    "telemetry": telemetry,
                    "recorded_at": _now_iso(),
                }
                summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(
                    f"[{arm}] ({idx:02d}/{len(target_refs)}) {case.case_id}: status={summary['terminal_status']} "
                    f"fin={summary['finalization_status']} sem={telemetry.get('semantic_calls', 0)} "
                    f"sem_trunc={telemetry.get('semantic_truncation_affected', False)} "
                    f"qrepair={telemetry.get('quote_repaired', False)} {elapsed}s",
                    flush=True,
                )

        manifest = {
            "arm": arm,
            "suite": suite.identity,
            "commit": commit,
            "freeze_id": freeze_data["freeze_id"],
            "variant": variant.to_dict(),
            "settings": safe_cfg,
            "completed_at": _now_iso(),
        }
        (record_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        workspace.mark_results_persisted()
    print(f"[{arm}] DONE and workspace cleaned up -> {record_dir}", flush=True)


def _build_blind_judge_payload(
    *,
    case: Any,
    truth: dict[str, Any],
    packet: dict[str, Any],
    artifact: dict[str, Any],
    con: sqlite3.Connection,
) -> dict[str, Any]:
    """Rehydrate cited messages directly from read-only frozen SQLite matching capability_judge.prepare_review_input."""

    messages: dict[str, dict[str, Any]] = {}
    for item in artifact.get("evidence_items", []):
        for source in item.get("sources", []):
            ref = source.get("reference", {})
            if ref.get("type") != "message":
                continue
            mid = ref["internal_message_id"]
            if mid in messages:
                continue
            row = con.execute(
                "SELECT internal_message_id,session_id,timestamp,sender_user_id,content_text,"
                "reply_to_source_message_id FROM messages WHERE internal_message_id=?",
                (mid,),
            ).fetchone()
            if row is None:
                row = con.execute(
                    "SELECT internal_message_id,session_id,timestamp,sender_user_id,content_text,"
                    "reply_to_source_message_id,root_message_id,parent_message_id,path,original_timestamp "
                    "FROM forwarded_messages WHERE internal_message_id=?",
                    (mid,),
                ).fetchone()
            if row is None or row["session_id"] != ref["session_id"]:
                raise RuntimeError(f"cited source cannot be verified in frozen DB: {mid}")
            record = dict(row)
            root_id = record.get("root_message_id", mid)
            root = con.execute(
                "SELECT internal_message_id,session_id,timestamp,sender_user_id,content_text,"
                "reply_to_source_message_id FROM messages WHERE internal_message_id=?",
                (root_id,),
            ).fetchone()
            if root is None:
                raise RuntimeError(f"cited source root missing: {root_id}")
            before = con.execute(
                "SELECT internal_message_id,session_id,timestamp,sender_user_id,content_text,"
                "reply_to_source_message_id FROM messages WHERE session_id=? AND timestamp<? "
                "ORDER BY timestamp DESC,internal_message_id DESC LIMIT 3",
                (root["session_id"], root["timestamp"]),
            ).fetchall()
            after = con.execute(
                "SELECT internal_message_id,session_id,timestamp,sender_user_id,content_text,"
                "reply_to_source_message_id FROM messages WHERE session_id=? AND timestamp>? "
                "ORDER BY timestamp,internal_message_id LIMIT 3",
                (root["session_id"], root["timestamp"]),
            ).fetchall()
            record["context"] = [dict(x) for x in [*reversed(before), root, *after]]
            messages[mid] = record

    return {
        "case_id": case.case_id,
        "case_version": case.version,
        "as_of": case.time_context,
        "question": case.query,
        "reference": {
            "user_need": truth["user_need"],
            "must_answer": truth["must_answer"],
            "evidence_status": truth["evidence_status"],
            "candidate_facts": truth["candidate_facts"],
            "evidence_limitations": truth["evidence_limitations"],
            "reasonable_other_answers": truth["reasonable_other_answers"],
            "reference_messages": packet["evidence"],
        },
        "answer": artifact,
        "cited_messages": list(messages.values()),
    }


async def _run_judge_async(baseline_dir: Path, candidate_dir: Path, output_dir: Path, case_filter: list[str] | None) -> None:
    from trivae.config.dotenv import load_environment_file
    from trivae.config.settings import load_settings
    from trivae.evaluation.capability_judge import RUBRIC_VERSION_V2_1, judge_prompt_for, parse_review
    from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationRun, EvaluationSuite
    from trivae.evaluation.store import SQLiteEvaluationStore
    from trivae.query.runtime.model_completion import complete_json, completion_record

    load_environment_file(None)
    settings = load_settings(model_id="gpt-plus", role="judge", config_path=MODELS_CONFIG)
    assert settings.provider == "chatgpt-plan", f"unexpected judge provider: {settings.provider}"

    suite = EvaluationSuite.from_json(SUITE_PATH)
    cases = {
        c.case_id: c
        for c in (EvaluationCaseBundle.from_json(p) for p in sorted((BUNDLE_DIR / "cases").glob("*.json")))
    }
    gt_by_id = {c["case_id"]: c for c in json.loads((BUNDLE_DIR / "ground-truth-v2.json").read_text(encoding="utf-8"))["cases"]}
    ev_by_id = {c["case_id"]: c for c in json.loads((BUNDLE_DIR / "evidence.json").read_text(encoding="utf-8"))["cases"]}

    output_dir.mkdir(parents=True, exist_ok=True)
    store = SQLiteEvaluationStore(output_dir / "evaluation.sqlite3")
    con = sqlite3.connect(FROZEN_DB.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    target_ids = [ref.case_id for ref in suite.case_references]
    if case_filter:
        allowed = set(case_filter)
        target_ids = [cid for cid in target_ids if cid in allowed]

    # Interleave baseline & candidate per case so both arms share identical temporal conditions.
    queue: list[tuple[str, Path, str]] = []
    for cid in target_ids:
        queue.append(("baseline", baseline_dir, cid))
        queue.append(("candidate", candidate_dir, cid))

    try:
        for idx, (arm, arm_dir, cid) in enumerate(queue, 1):
            out_case = output_dir / arm / cid
            review_file = out_case / "review.json"
            if review_file.exists():
                print(f"[judge] ({idx:02d}/{len(queue)}) SKIP {arm}/{cid} (already reviewed)", flush=True)
                continue

            cdir = arm_dir / "cases" / cid
            summary_path = cdir / "summary.json"
            if not summary_path.exists():
                print(f"[judge] ({idx:02d}/{len(queue)}) MISSING {arm}/{cid}", flush=True)
                continue
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("terminal_status") != "completed" or not (cdir / "answer_artifact.json").exists():
                out_case.mkdir(parents=True, exist_ok=True)
                (out_case / "excluded.json").write_text(
                    json.dumps(
                        {
                            "arm": arm,
                            "case_id": cid,
                            "run_id": summary.get("run_id"),
                            "terminal_status": summary.get("terminal_status"),
                            "reason": "No completed answer artifact; do not invent a Judge review",
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"[judge] ({idx:02d}/{len(queue)}) EXCLUDED {arm}/{cid} ({summary.get('terminal_status')})", flush=True)
                continue

            run_data = json.loads((cdir / "run.json").read_text(encoding="utf-8"))
            run = EvaluationRun.from_dict(run_data)
            artifact = json.loads((cdir / "answer_artifact.json").read_text(encoding="utf-8"))
            payload = _build_blind_judge_payload(
                case=cases[cid], truth=gt_by_id[cid], packet=ev_by_id[cid], artifact=artifact, con=con
            )
            out_case.mkdir(parents=True, exist_ok=True)
            (out_case / "input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            last_exc: Exception | None = None
            for attempt in range(1, 5):
                try:
                    t0 = time.perf_counter()
                    completion = await complete_json(
                        settings,
                        system_prompt=judge_prompt_for(RUBRIC_VERSION_V2_1),
                        user_prompt=json.dumps(payload, ensure_ascii=False),
                        session_id=f"{run.run_id}-a{attempt}",
                    )
                    dt = round(time.perf_counter() - t0, 2)
                    (out_case / "response.json").write_text(
                        json.dumps(completion_record(completion), ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    assert completion.finish_reason in {"stop", "completed"}, completion.finish_reason
                    review = parse_review(
                        completion.content,
                        run_id=run.run_id,
                        judge_identity=f"{settings.provider}:{completion.model}:{RUBRIC_VERSION_V2_1}",
                        rubric_version=RUBRIC_VERSION_V2_1,
                    )
                    store.save_run(run)
                    store.save_review(review)
                    review_dict = review.to_dict()
                    review_file.write_text(json.dumps(review_dict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    qa = review_dict["quality_axes"]
                    ts = qa["task_satisfaction"]["score"]
                    ar = qa["answer_reliability"]["score"]
                    print(
                        f"[judge] ({idx:02d}/{len(queue)}) {arm}/{cid}: task={ts} rel={ar} "
                        f"diags={len(review_dict.get('diagnostics', []))} ({dt}s)",
                        flush=True,
                    )
                    last_exc = None
                    break
                except (AttributeError, TypeError, KeyError, NameError):
                    raise
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    (out_case / f"error-attempt-{attempt}.json").write_text(
                        json.dumps({"at": _now_iso(), "type": type(exc).__name__, "message": msg[:500]}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    if "usage_limit_exceeded" in msg or "quota" in msg.lower():
                        print(f"[judge] QUOTA LIMIT hit on {arm}/{cid}; stopping cleanly.", flush=True)
                        raise
                    if attempt < 4:
                        wait = 5 * attempt
                        print(f"[judge] transient error on {arm}/{cid} (attempt {attempt}): {type(exc).__name__}; retry in {wait}s", flush=True)
                        await asyncio.sleep(wait)
            if last_exc is not None:
                print(f"[judge] FAILED {arm}/{cid} after retries: {type(last_exc).__name__}: {last_exc}", flush=True)
    finally:
        con.close()
        store.close()


def _summarize_arm(arm: str, arm_dir: Path, judge_dir: Path, case_ids: list[str]) -> dict[str, Any]:
    rows = []
    for cid in case_ids:
        s_path = arm_dir / "cases" / cid / "summary.json"
        if not s_path.exists():
            continue
        s = json.loads(s_path.read_text(encoding="utf-8"))
        r_path = judge_dir / arm / cid / "review.json"
        rev = json.loads(r_path.read_text(encoding="utf-8")) if r_path.exists() else None
        rows.append((cid, s, rev))

    total = len(rows)
    completed = sum(1 for _, s, _ in rows if s["terminal_status"] == "completed")
    parse_failed = sum(1 for _, s, _ in rows if (s.get("telemetry") or {}).get("answer_parse_failed"))
    quote_repaired = sum(1 for _, s, _ in rows if (s.get("telemetry") or {}).get("quote_repaired"))
    quote_repaired_total = sum(int((s.get("telemetry") or {}).get("quote_repair_count") or 0) for _, s, _ in rows)
    budget_err_runs = sum(1 for _, s, _ in rows if int((s.get("telemetry") or {}).get("budget_errors") or 0) > 0)
    sem_runs = sum(1 for _, s, _ in rows if int((s.get("telemetry") or {}).get("semantic_calls") or 0) > 0)
    sem_trunc_runs = sum(1 for _, s, _ in rows if (s.get("telemetry") or {}).get("semantic_truncation_affected"))

    judged = [(cid, s, rev) for cid, s, rev in rows if rev is not None]
    ts_scores = [
        rev["quality_axes"]["task_satisfaction"]["score"]
        for _, _, rev in judged
        if isinstance(rev["quality_axes"]["task_satisfaction"]["score"], int)
    ]
    ar_scores = [
        rev["quality_axes"]["answer_reliability"]["score"]
        for _, _, rev in judged
        if isinstance(rev["quality_axes"]["answer_reliability"]["score"], int)
    ]
    dual_ge3 = sum(
        1
        for _, _, rev in judged
        if isinstance(rev["quality_axes"]["task_satisfaction"]["score"], int)
        and isinstance(rev["quality_axes"]["answer_reliability"]["score"], int)
        and rev["quality_axes"]["task_satisfaction"]["score"] >= 3
        and rev["quality_axes"]["answer_reliability"]["score"] >= 3
    )
    diag_types: Counter[str] = Counter()
    diag_sev: Counter[str] = Counter()
    for _, _, rev in judged:
        for d in rev.get("diagnostics", []):
            diag_types[d["type"]] += 1
            diag_sev[d["severity"]] += 1

    in_tok = sum(int(((s.get("usage") or {}).get("input_tokens")) or 0) for _, s, _ in rows)
    out_tok = sum(int(((s.get("usage") or {}).get("output_tokens")) or 0) for _, s, _ in rows)
    cached_tok = sum(int(((s.get("usage") or {}).get("cached_input_tokens")) or 0) for _, s, _ in rows)
    lat_total = round(sum(float(s.get("latency_seconds") or 0.0) for _, s, _ in rows), 2)

    return {
        "arm": arm,
        "total_cases": total,
        "completed": completed,
        "delivery_rate": round(completed / total, 4) if total else 0.0,
        "answer_parse_failed": parse_failed,
        "quote_repaired_runs": quote_repaired,
        "quote_repaired_total_quotes": quote_repaired_total,
        "runs_with_budget_errors": budget_err_runs,
        "semantic_search_runs": sem_runs,
        "semantic_truncation_affected_runs": sem_trunc_runs,
        "judged": len(judged),
        "task_satisfaction_mean": round(sum(ts_scores) / len(ts_scores), 3) if ts_scores else None,
        "task_satisfaction_ge3": sum(1 for x in ts_scores if x >= 3),
        "task_satisfaction_dist": dict(sorted(Counter(ts_scores).items())),
        "answer_reliability_mean": round(sum(ar_scores) / len(ar_scores), 3) if ar_scores else None,
        "answer_reliability_ge3": sum(1 for x in ar_scores if x >= 3),
        "answer_reliability_dist": dict(sorted(Counter(ar_scores).items())),
        "dual_axis_ge3": dual_ge3,
        "dual_axis_ge3_rate_of_judged": round(dual_ge3 / len(judged), 4) if judged else None,
        "dual_axis_ge3_rate_of_total": round(dual_ge3 / total, 4) if total else None,
        "diagnostic_types": dict(diag_types),
        "diagnostic_severities": dict(diag_sev),
        "usage": {
            "input_tokens": in_tok,
            "cached_input_tokens": cached_tok,
            "output_tokens": out_tok,
            "total_latency_seconds": lat_total,
        },
    }


def _generate_report(baseline_dir: Path, candidate_dir: Path, judge_dir: Path, output_dir: Path) -> None:
    from trivae.evaluation.contracts import EvaluationSuite

    suite = EvaluationSuite.from_json(SUITE_PATH)
    case_ids = [ref.case_id for ref in suite.case_references]

    base_summary = _summarize_arm("baseline", baseline_dir, judge_dir, case_ids)
    cand_summary = _summarize_arm("candidate", candidate_dir, judge_dir, case_ids)

    per_case = []
    paired_both = []
    sem_affected_paired = []
    sem_used_paired = []

    for cid in case_ids:
        bs = json.loads((baseline_dir / "cases" / cid / "summary.json").read_text(encoding="utf-8"))
        cs = json.loads((candidate_dir / "cases" / cid / "summary.json").read_text(encoding="utf-8"))
        br_p = judge_dir / "baseline" / cid / "review.json"
        cr_p = judge_dir / "candidate" / cid / "review.json"
        br = json.loads(br_p.read_text(encoding="utf-8")) if br_p.exists() else None
        cr = json.loads(cr_p.read_text(encoding="utf-8")) if cr_p.exists() else None

        bts = br["quality_axes"]["task_satisfaction"]["score"] if br else None
        bar = br["quality_axes"]["answer_reliability"]["score"] if br else None
        cts = cr["quality_axes"]["task_satisfaction"]["score"] if cr else None
        car = cr["quality_axes"]["answer_reliability"]["score"] if cr else None

        sem_affected = bool(
            (bs.get("telemetry") or {}).get("semantic_truncation_affected")
            or (cs.get("telemetry") or {}).get("semantic_truncation_affected")
        )
        sem_used = bool(
            int((bs.get("telemetry") or {}).get("semantic_calls") or 0) > 0
            or int((cs.get("telemetry") or {}).get("semantic_calls") or 0) > 0
        )

        entry = {
            "case_id": cid,
            "baseline_status": bs["terminal_status"],
            "candidate_status": cs["terminal_status"],
            "baseline_task": bts,
            "baseline_rel": bar,
            "candidate_task": cts,
            "candidate_rel": car,
            "delta_task": (cts - bts) if (isinstance(bts, int) and isinstance(cts, int)) else None,
            "delta_rel": (car - bar) if (isinstance(bar, int) and isinstance(car, int)) else None,
            "semantic_used": sem_used,
            "semantic_truncation_affected": sem_affected,
            "baseline_quote_parse_fail": bool((bs.get("telemetry") or {}).get("answer_parse_failed")),
            "candidate_quote_repaired": bool((cs.get("telemetry") or {}).get("quote_repaired")),
            "baseline_sem_calls": int((bs.get("telemetry") or {}).get("semantic_calls") or 0),
            "candidate_sem_calls": int((cs.get("telemetry") or {}).get("semantic_calls") or 0),
            "baseline_sem_omitted_hits": int((bs.get("telemetry") or {}).get("semantic_host_omitted_hits") or 0),
            "candidate_sem_omitted_hits": int((cs.get("telemetry") or {}).get("semantic_host_omitted_hits") or 0),
            "baseline_diags": len(br.get("diagnostics", [])) if br else None,
            "candidate_diags": len(cr.get("diagnostics", [])) if cr else None,
        }
        per_case.append(entry)
        if isinstance(bts, int) and isinstance(bar, int) and isinstance(cts, int) and isinstance(car, int):
            paired_both.append(entry)
            if sem_used:
                sem_used_paired.append(entry)
            if sem_affected:
                sem_affected_paired.append(entry)

    def _slice_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        if n == 0:
            return {"count": 0}
        b_ts = sum(x["baseline_task"] for x in items) / n
        c_ts = sum(x["candidate_task"] for x in items) / n
        b_ar = sum(x["baseline_rel"] for x in items) / n
        c_ar = sum(x["candidate_rel"] for x in items) / n
        b_dual = sum(1 for x in items if x["baseline_task"] >= 3 and x["baseline_rel"] >= 3)
        c_dual = sum(1 for x in items if x["candidate_task"] >= 3 and x["candidate_rel"] >= 3)
        return {
            "count": n,
            "baseline_task_mean": round(b_ts, 3),
            "candidate_task_mean": round(c_ts, 3),
            "delta_task_mean": round(c_ts - b_ts, 3),
            "baseline_rel_mean": round(b_ar, 3),
            "candidate_rel_mean": round(c_ar, 3),
            "delta_rel_mean": round(c_ar - b_ar, 3),
            "baseline_dual_ge3": b_dual,
            "candidate_dual_ge3": c_dual,
            "task_win_tie_loss": [
                sum(1 for x in items if x["delta_task"] > 0),
                sum(1 for x in items if x["delta_task"] == 0),
                sum(1 for x in items if x["delta_task"] < 0),
            ],
            "rel_win_tie_loss": [
                sum(1 for x in items if x["delta_rel"] > 0),
                sum(1 for x in items if x["delta_rel"] == 0),
                sum(1 for x in items if x["delta_rel"] < 0),
            ],
        }

    report = {
        "generated_at": _now_iso(),
        "suite": suite.identity,
        "baseline": base_summary,
        "candidate": cand_summary,
        "paired_completed_both": _slice_stats(paired_both),
        "semantic_used_paired": _slice_stats(sem_used_paired),
        "semantic_truncation_affected_paired": _slice_stats(sem_affected_paired),
        "per_case": per_case,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ab-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_case"}, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run-arm")
    p_run.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    p_run.add_argument("--record-dir", type=Path, required=True)
    p_run.add_argument("--cases", nargs="*")

    p_judge = sub.add_parser("judge")
    p_judge.add_argument("--baseline-dir", type=Path, required=True)
    p_judge.add_argument("--candidate-dir", type=Path, required=True)
    p_judge.add_argument("--output-dir", type=Path, required=True)
    p_judge.add_argument("--cases", nargs="*")

    p_rep = sub.add_parser("report")
    p_rep.add_argument("--baseline-dir", type=Path, required=True)
    p_rep.add_argument("--candidate-dir", type=Path, required=True)
    p_rep.add_argument("--judge-dir", type=Path, required=True)
    p_rep.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "run-arm":
        asyncio.run(_run_arm_async(args.arm, args.record_dir, args.cases))
    elif args.cmd == "judge":
        asyncio.run(_run_judge_async(args.baseline_dir, args.candidate_dir, args.output_dir, args.cases))
    elif args.cmd == "report":
        _generate_report(args.baseline_dir, args.candidate_dir, args.judge_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
