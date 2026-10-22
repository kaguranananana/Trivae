"""按冻结Case运行质量修复迭代；每个unit一次，记录全部真实发送尝试。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.audit_projection_compaction import compact_projection
from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.bootstrap.application import create_application
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationCaseBundle
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride
from trivae.query.runtime.prompt import SYSTEM_PROMPT

SOURCE = Path("data/evaluation/quality-optimization-20261020")
CASES = {"owner": "para-intern-owner", "advice": "para-resume-advice", "written": "para-written-test",
         "miner": "lexical-resume-miner", "archify": "context-archify", "matt": "context-mattpocock-1",
         "zero": "zero-empty-2"}
TOOLS = ("lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
         "find_members", "get_schema", "execute_sql")


def application_for(root: Path, label: str, runtime: Any) -> Any:
    """各题独立存储会话、Trace和评测；语料及索引来自本轮克隆。"""
    output = root / label
    output.mkdir(exist_ok=True)
    application = create_application(
        root / "snapshot/trivae.sqlite3", agent_runtime=runtime,
        semantic_index_path=root / "snapshot/trivae.semantic.sqlite3",
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    return application


def inspect(root: Path, label: str, application: Any) -> tuple[Any, Any, Any]:
    """保留原题和GT，只接受与之匹配且索引完整的原快照。"""
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-{CASES[label]}.json")
    snapshot = DatasetSnapshot.from_database(root / "snapshot/trivae.sqlite3")
    semantic = application.semantic_index_status().to_dict()
    if snapshot.snapshot_id != case.dataset_snapshot.snapshot_id or semantic["status"] != "completed":
        raise RuntimeError("case snapshot or completed semantic index changed")
    return case, snapshot, semantic


async def prepare(root: Path, labels: list[str], *, compact: bool = False) -> None:
    """真实请求前冻结条件，每题预留最多8次发送但不自动重试。"""
    root.mkdir(parents=True, exist_ok=False)
    (root / "snapshot").mkdir()
    for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
        subprocess.run(["cp", "-c", str(SOURCE / name), str(root / "snapshot" / name)], check=True)
    protocol: dict[str, Any] = {"cases": {}, "order": labels, "system_prompt": SYSTEM_PROMPT,
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "automatic_retries": False, "judge": False, "tools": TOOLS, "projection_compaction": compact}
    for label in labels:
        runtime = configured_runtime()
        application = application_for(root, label, runtime)
        try:
            case, snapshot, semantic = inspect(root, label, application)
            protocol["cases"][label] = {"case": case.to_dict(), "snapshot": snapshot.to_dict(),
                "semantic": semantic, "runtime": runtime.safe_configuration()}
        finally:
            await application.aclose()
    write_json(root / "protocol.json", protocol, exclusive=True)
    write_json(root / "http-ledger.json", {"maximum": 8 * len(labels), "maximum_per_case": 8,
        "used": 0, "attempts": [], "blocked": [], "attempted_cases": []}, exclusive=True)
    (root / "runner.py").write_text(Path(__file__).read_text(), encoding="utf-8")
    print({"prepared": labels, "http_maximum": 8 * len(labels)}, flush=True)


async def run(root: Path, label: str) -> None:
    """只运行登记题一次，失败保留原始结果，由下一轮修复决定是否新建实验。"""
    protocol = read_json(root / "protocol.json")
    ledger_path = root / "http-ledger.json"
    ledger = read_json(ledger_path)
    if label not in protocol["cases"] or label in ledger["attempted_cases"]:
        raise RuntimeError("case is not registered or already attempted")
    runtime = configured_runtime()
    application = application_for(root, label, runtime)
    output = root / label
    record: dict[str, Any] = {"case": label, "transport": []}
    captured: dict[str, Any] = {}
    try:
        case, snapshot, semantic = inspect(root, label, application)
        # created_at是本次观察的采集时间，不属于数据库身份；复用首次冻结的观察时间。
        snapshot_value = snapshot.to_dict()
        snapshot_value["created_at"] = protocol["cases"][label]["snapshot"]["created_at"]
        current = {"case": case.to_dict(), "snapshot": snapshot_value, "semantic": semantic,
                   "runtime": runtime.safe_configuration()}
        if (json.dumps(current, sort_keys=True) != json.dumps(protocol["cases"][label], sort_keys=True)
                or SYSTEM_PROMPT != protocol["system_prompt"]
                or Path(__file__).read_text() != (root / "runner.py").read_text()):
            raise RuntimeError("frozen conditions changed")
        # 此前真实发生过预检后继续修改源码；推理前核对执行版本，避免把不同实现混成一组。
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        source_changes = subprocess.check_output(["git", "diff", "--name-only", "--", "src"], text=True).strip()
        if revision != protocol["code_version"] or source_changes:
            raise RuntimeError("source revision changed after experiment preparation")
        await runtime._model._validate_model()
        ledger["attempted_cases"].append(label)
        write_json(ledger_path, ledger)
        before = ledger["used"]
        runtime._model._client.event_hooks["request"].append(RequestLedger(ledger_path, label).before_request)
        observer = runtime._model._observer

        def observe(value: Any) -> None:
            record["transport"].append(dict(value))
            write_json(output / "result.json", record)
            observer(value)

        runtime._model._observer = observe

        async def query(request: Any) -> Any:
            captured["result"] = await application.query(request)
            return captured["result"]

        variant = ControlledVariant(
            variant_id=root.name, code_version=protocol["code_version"], provider="chatgpt-plan", model="gpt-6.1-sol",
            available_tools=TOOLS, model_parameters={"reasoning_effort": "medium"},
            prompt_identity="production-system-prompt", budget={"max_tool_rounds": 3, "max_turns": 8},
            runtime_configuration={"projection_compaction": protocol["projection_compaction"]},
            execution_override=ExecutionOverride(forced_route="standard_execution"),
        )
        runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                                  store=application.evaluation_store, snapshot_resolver=lambda: snapshot)
        # 候选只更改投影编码，查询、正文、排序、Prompt和16k共享预算均不动。
        with compact_projection() if protocol["projection_compaction"] else nullcontext():
            evaluation = (await runner.run_case(case, variant, suite_id="quality-repair-development"))[0]
        result = captured["result"]
        record.update(status=result.execution_status, result=asdict(result), evaluation=evaluation.to_dict(),
                      http_requests=read_json(ledger_path)["used"] - before)
        print({"case": label, "status": result.execution_status, "http_requests": record["http_requests"]}, flush=True)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        raise
    finally:
        write_json(output / "result.json", record)
        await application.aclose()


def main() -> None:
    """通过不同root保存每轮迭代，不覆盖旧失败或重置其账本。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--case", choices=CASES, action="append", required=True)
    parser.add_argument("--compact-projection", action="store_true", help="仅prepare时冻结投影精简候选")
    args = parser.parse_args()
    if args.action == "run" and len(args.case) != 1:
        parser.error("run accepts exactly one case")
    asyncio.run(prepare(args.root, args.case, compact=args.compact_projection)
                if args.action == "prepare" else run(args.root, args.case[0]))


if __name__ == "__main__":
    main()
