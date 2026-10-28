"""Re-review the saved Eval v1 Baseline answers with the versioned Judge v2 rubric."""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from scripts.judge_capability import main_async as judge_one
from scripts.verify_capability_bundle import verify
from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_settings
from trivae.evaluation.capability_judge import JUDGE_PROMPT
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationContractError, EvaluationRun
from trivae.evaluation.store import SQLiteEvaluationStore


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_transient(error_path: Path) -> bool:
    """Retry only transport interruptions, timeouts and provider rate/server errors."""
    try:
        error = _read_json(error_path)
    except (OSError, json.JSONDecodeError):
        return False
    observation = error.get("observation", {})
    if not isinstance(observation, dict):
        return False
    status = observation.get("status_code")
    if status in (408, 425, 429) or isinstance(status, int) and 500 <= status <= 599:
        return True
    transient_codes = {"AUTH_NETWORK", "PROVIDER_ERROR", "REQUEST_TIMEOUT", "STREAM_INTERRUPTED"}
    if observation.get("error_code") in transient_codes:
        return True
    chain = observation.get("transport_exception_chain", [])
    return isinstance(chain, list) and any(
        isinstance(item, dict) and item.get("type") in {
            "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "RemoteProtocolError"
        }
        for item in chain
    )


def _load_source_runs(sources: list[tuple[Path, Path]]) -> tuple[dict[str, EvaluationRun], dict[str, Path], dict[str, Path]]:
    runs: dict[str, EvaluationRun] = {}
    stores: dict[str, Path] = {}
    databases: dict[str, Path] = {}
    for store_path, database_path in sources:
        con = sqlite3.connect(store_path.resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT payload_json FROM evaluation_runs ORDER BY started_at, run_id").fetchall()
            for row in rows:
                run = EvaluationRun.from_dict(json.loads(row["payload_json"]))
                if run.case_id in runs:
                    raise EvaluationContractError(f"duplicate Baseline Run for {run.case_id}")
                runs[run.case_id] = run
                stores[run.case_id] = store_path
                databases[run.case_id] = database_path
        finally:
            con.close()
    return runs, stores, databases


def _has_v2_review(store: SQLiteEvaluationStore, run_id: str) -> bool:
    rows = store.connection.execute(
        "SELECT payload_json FROM evaluation_reviews WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
    ).fetchall()
    for row in rows:
        review = json.loads(row["payload_json"])
        if review.get("rubric_version") == "eval-rubric-v2":
            return True
    return False


async def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    preflight = _read_json(args.bundle_dir / "preflight-record" / "experiment.json")
    suite_data = preflight["suite"]
    suite_path = args.output_dir / "suite.json"
    if suite_path.exists() and _read_json(suite_path) != suite_data:
        raise EvaluationContractError("existing experiment suite differs from the frozen Baseline")
    if not suite_path.exists():
        _write_json(suite_path, suite_data)

    full_snapshot = DatasetSnapshot.from_database(args.database)
    supplement_snapshot = DatasetSnapshot.from_database(args.supplement_database)
    if (full_snapshot.snapshot_id, full_snapshot.deterministic_fingerprint) != (
        supplement_snapshot.snapshot_id, supplement_snapshot.deterministic_fingerprint
    ):
        raise EvaluationContractError("Baseline and supplement data are not the same frozen snapshot")
    bundle_check = verify(args.bundle_dir, suite_path, args.freeze_manifest, args.database)
    load_environment_file(args.env_file)
    settings = load_settings(model_id=args.judge_model, role="judge", config_path=args.models_config)
    if settings.provider != "chatgpt-plan" or settings.model_name != "gpt-6.1-sol" or settings.chatgpt_reasoning_effort != "medium":
        raise EvaluationContractError("Judge v2 must use the Baseline GPT-6.1 Sol Medium profile")

    source_pairs = [
        (args.full_evaluation_database, args.database),
        (args.supplement_evaluation_database, args.supplement_database),
    ]
    runs, source_by_case, database_by_case = _load_source_runs(source_pairs)
    baseline_summary = _read_json(args.baseline_dir / "summary.json")
    failure_by_case = {
        item["case_id"]: item for item in baseline_summary.get("agent", {}).get("failures", [])
    }
    expected_ids = [item["case_id"] for item in suite_data["cases"]]
    if len(runs) != 16 or set(runs) != set(expected_ids):
        raise EvaluationContractError("Baseline must contain exactly one Run for each of the 16 frozen Cases")
    if sum(run.terminal_status == "completed" and run.query_result is not None
           and run.query_result.get("is_successful") is True for run in runs.values()) != 14:
        raise EvaluationContractError("Baseline must contain exactly 14 completed answers eligible for Judge")
    failed = [run for run in runs.values() if run.terminal_status != "completed" or run.query_result is None
              or run.query_result.get("is_successful") is not True]
    if {run.case_id for run in failed} != {"cap1-03-task-progress", "cap1-14-agent-interview"}:
        raise EvaluationContractError("the only non-reviewable Baseline Cases must remain 03 and 14")
    if any(not run.trace_id for run in runs.values()):
        raise EvaluationContractError("a Baseline Run is missing its Trace identity")

    target_database = args.output_dir / "evaluation-v2.sqlite3"
    target_store = SQLiteEvaluationStore(target_database)
    try:
        for run_record in runs.values():
            target_store.save_run(run_record)

        campaign_path = args.output_dir / "campaign.json"
        campaign: dict[str, Any] = _read_json(campaign_path) if campaign_path.exists() else {
            "rubric_version": "eval-rubric-v2",
            "source_suite": str(args.bundle_dir / "preflight-record" / "experiment.json"),
            "source_baseline": str(args.baseline_dir),
            "snapshot_id": full_snapshot.snapshot_id,
            "model_profile": settings.model_profile,
            "provider": settings.provider,
            "model": settings.model_name,
            "reasoning_effort": settings.chatgpt_reasoning_effort,
            "max_attempts_per_case": 2,
            "answer_database_by_batch": {
                "full": str(args.database),
                "supplement": str(args.supplement_database),
            },
            "bundle_verification": bundle_check,
            "cases": {},
        }

        case_records = campaign.setdefault("cases", {})
        if not isinstance(case_records, dict):
            raise EvaluationContractError("campaign cases must be a JSON object")
        for case_id in expected_ids:
            run_record = runs[case_id]
            case_record: dict[str, Any] = case_records.setdefault(case_id, {
                "run_id": run_record.run_id,
                "trace_id": run_record.trace_id,
                "terminal_status": run_record.terminal_status,
                "exception_type": run_record.exception_type,
                "answer_database": str(database_by_case[case_id]),
                "status": "pending",
                "attempts": [],
            })
            if (run_record.terminal_status != "completed" or run_record.query_result is None
                    or run_record.query_result.get("is_successful") is not True):
                case_record["status"] = "not_reviewed_agent_failure"
                failure = failure_by_case.get(case_id, {})
                case_record["exception_type"] = failure.get("exception_type") or run_record.exception_type
                case_record["failure_diagnostic"] = {
                    "error_code": failure.get("error_code"),
                    "diagnostic_type": failure.get("diagnostic_type"),
                    "category": failure.get("category"),
                    "provider_status_codes": failure.get("provider_status_codes", []),
                }
                case_record["failure_reason"] = {
                    "exception_type": case_record["exception_type"],
                    "message": "原始 Baseline Agent Run 失败；未生成 Judge 质量评分。",
                }
                _write_json(campaign_path, campaign)
                continue
            if _has_v2_review(target_store, run_record.run_id):
                case_record["status"] = "reviewed"
                _write_json(campaign_path, campaign)
                continue

            case_dir = args.output_dir / "cases" / case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            existing_attempts = sorted(case_dir.glob("attempt-[0-9][0-9]"))
            next_attempt = max((int(path.name.split("-")[1]) for path in existing_attempts), default=0) + 1
            attempts = case_record.get("attempts", [])
            previous_retryable = not attempts or bool(attempts[-1].get("retryable"))
            while next_attempt <= 2 and previous_retryable:
                record_dir = case_dir / f"attempt-{next_attempt:02d}"
                call_args = argparse.Namespace(
                    bundle_dir=args.bundle_dir,
                    suite=suite_path,
                    freeze_manifest=args.freeze_manifest,
                    database=database_by_case[case_id],
                    evaluation_database=target_database,
                    source_evaluation_database=source_by_case[case_id],
                    run_id=run_record.run_id,
                    record_dir=record_dir,
                    judge_model=args.judge_model,
                    models_config=args.models_config,
                    env_file=args.env_file,
                    skip_bundle_verification=True,
                )
                started = time.time()
                print(f"Judge v2 {case_id}: attempt {next_attempt}/2", flush=True)
                try:
                    await judge_one(call_args)
                    attempt_record = {
                        "attempt": next_attempt,
                        "status": "completed",
                        "record_dir": str(record_dir),
                        "elapsed_ms": round((time.time() - started) * 1000, 1),
                        "retryable": False,
                    }
                    _write_json(record_dir / "attempt.json", attempt_record)
                    case_record["attempts"].append(attempt_record)
                    case_record["status"] = "reviewed"
                    previous_retryable = False
                except Exception as exc:
                    error_path = record_dir / "error.json"
                    retryable = _is_transient(error_path)
                    attempt_record = {
                        "attempt": next_attempt,
                        "status": "failed",
                        "record_dir": str(record_dir),
                        "elapsed_ms": round((time.time() - started) * 1000, 1),
                        "exception_type": type(exc).__name__,
                        "error": str(exc),
                        "retryable": retryable,
                    }
                    _write_json(record_dir / "attempt.json", attempt_record)
                    case_record["attempts"].append(attempt_record)
                    case_record["status"] = "review_failed"
                    case_record["failure_reason"] = {"exception_type": type(exc).__name__, "message": str(exc)}
                    previous_retryable = retryable
                    if retryable and next_attempt < 2:
                        print(f"Judge v2 {case_id}: temporary provider failure; retrying once", flush=True)
                        await asyncio.sleep(2)
                _write_json(campaign_path, campaign)
                if _has_v2_review(target_store, run_record.run_id):
                    case_record["status"] = "reviewed"
                    previous_retryable = False
                next_attempt += 1
            if case_record["status"] == "reviewed":
                print(f"Judge v2 {case_id}: saved", flush=True)
            else:
                print(f"Judge v2 {case_id}: not scored", flush=True)
            _write_json(campaign_path, campaign)
    finally:
        target_store.close()

    (args.output_dir / "judge-prompt-v2.txt").write_text(JUDGE_PROMPT, encoding="utf-8")
    return campaign


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=Path("data/evaluation/eval-v1-baseline-20261028"))
    parser.add_argument("--bundle-dir", type=Path, default=Path("data/evaluation/eval-v1-20261028"))
    parser.add_argument("--database", type=Path,
                        help="Frozen Canonical database; defaults to Baseline full-work copy")
    parser.add_argument("--supplement-database", type=Path,
                        help="Supplement frozen Canonical database; defaults to supplement-work copy")
    parser.add_argument("--full-evaluation-database", type=Path,
                        help="Baseline Evaluation Store; defaults to full-evaluation.sqlite3")
    parser.add_argument("--supplement-evaluation-database", type=Path,
                        help="Supplement Evaluation Store; defaults to supplement-evaluation.sqlite3")
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--models-config", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--judge-model", default="gpt-plus")
    parser.add_argument("--output-dir", type=Path, default=Path("data/evaluation/eval-v2-baseline-20261028"))
    args = parser.parse_args()
    args.database = args.database or args.baseline_dir / "full-work" / "trivae.sqlite3"
    args.supplement_database = args.supplement_database or args.baseline_dir / "supplement-20261028" / "supplement-work" / "trivae.sqlite3"
    args.full_evaluation_database = args.full_evaluation_database or args.baseline_dir / "full-evaluation.sqlite3"
    args.supplement_evaluation_database = args.supplement_evaluation_database or args.baseline_dir / "supplement-20261028" / "supplement-evaluation.sqlite3"
    args.freeze_manifest = args.freeze_manifest or args.baseline_dir / "full-work" / "freeze.json"
    args.models_config = args.models_config or args.baseline_dir / "models.yaml"
    args.output_dir = args.output_dir.resolve()
    args.baseline_dir = args.baseline_dir.resolve()
    args.bundle_dir = args.bundle_dir.resolve()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
