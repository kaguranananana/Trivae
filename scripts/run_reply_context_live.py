"""在终端执行三个 Development 原问题，验证真实 Plan Medium 的自主回复调查。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.bootstrap.application import create_application
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationCaseBundle
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path("data/evaluation/reply-context-live-20261022")
SOURCE = Path("data/evaluation/quality-optimization-20261020")
CASES = {"archify": "archify", "matt1": "mattpocock-1", "matt2": "mattpocock-2"}
TOOLS = ("lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
         "find_members", "get_schema", "execute_sql")


def open_application(label: str, runtime: Any) -> Any:
    """只在本轮独立快照与工件目录上写入，原实验数据库保持原状。"""
    output = ROOT / label
    output.mkdir(exist_ok=True)
    application = create_application(
        ROOT / "snapshot/trivae.sqlite3", agent_runtime=runtime,
        semantic_index_path=ROOT / "snapshot/trivae.semantic.sqlite3",
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    return application


def inspect(application: Any, label: str) -> tuple[EvaluationCaseBundle, DatasetSnapshot, dict[str, object]]:
    """核对原 Case 快照与现有索引，不改 GT 或重建索引。"""
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.json")
    snapshot = DatasetSnapshot.from_database(ROOT / "snapshot/trivae.sqlite3")
    if snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
        raise RuntimeError("original Case and experiment snapshot do not match")
    semantic = application.semantic_index_status().to_dict()
    if semantic["status"] != "completed" or semantic["indexed_message_count"] != snapshot.message_count:
        raise RuntimeError("existing semantic index is not ready")
    return case, snapshot, semantic


async def prepare() -> None:
    """先冻结问题、代码、Prompt 和次数，再发送任何推理请求。"""
    ROOT.mkdir(parents=True, exist_ok=False)
    snapshot_dir = ROOT / "snapshot"
    snapshot_dir.mkdir()
    # macOS 的文件克隆隔离后续写入，同时避免重复占用数 GB 的历史快照空间。
    for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
        subprocess.run(["cp", "-c", str(SOURCE / name), str(snapshot_dir / name)], check=True)
    protocol: dict[str, Any] = {
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "system_prompt": SYSTEM_PROMPT, "tools": TOOLS, "order": list(CASES),
        "provider": "chatgpt-plan", "model": "gpt-6.1-sol", "effort": "medium",
        "max_tool_rounds": 3, "max_turns": 8, "total_http_maximum": 24, "maximum_per_case": 8,
        "forced_route": "standard_execution", "judge": False, "automatic_retries": False,
        "cases": {},
    }
    for label in CASES:
        runtime = configured_runtime()
        application = open_application(label, runtime)
        try:
            case, snapshot, semantic = inspect(application, label)
            protocol["cases"][label] = {"case": case.to_dict(), "snapshot": snapshot.to_dict(),
                "semantic": semantic, "runtime": runtime.safe_configuration()}
            print(json.dumps({"preflight": label, "messages": snapshot.message_count,
                "semantic": semantic["status"]}), flush=True)
        finally:
            await application.aclose()
    write_json(ROOT / "protocol.json", protocol, exclusive=True)
    write_json(ROOT / "http-ledger.json", {"maximum": 24, "maximum_per_case": 8, "used": 0,
        "attempts": [], "blocked": [], "attempted_cases": []}, exclusive=True)


async def run_case(label: str) -> None:
    """每题只执行一次原始问题；模型自行选择工具、锚点与 include_replies。"""
    protocol = read_json(ROOT / "protocol.json")
    runtime = configured_runtime()
    application = open_application(label, runtime)
    output = ROOT / label
    record: dict[str, Any] = {"case": label, "transport": [], "events": []}
    started = perf_counter()
    try:
        case, snapshot, semantic = inspect(application, label)
        frozen = protocol["cases"][label]
        current = {"case": case.to_dict(), "snapshot": frozen["snapshot"],
            "semantic": semantic, "runtime": runtime.safe_configuration()}
        if (json.dumps(current, sort_keys=True) != json.dumps(frozen, sort_keys=True)
                or SYSTEM_PROMPT != protocol["system_prompt"]):
            raise RuntimeError("experiment conditions changed after freezing")
        ledger = read_json(ROOT / "http-ledger.json")
        if label in ledger["attempted_cases"]:
            raise RuntimeError("Case was already attempted; no automatic repeat")
        # 目录预检不消耗推理次数；实际推理每次在 HTTP 发送前持久化计数。
        await runtime._model._validate_model()
        ledger["attempted_cases"].append(label)
        write_json(ROOT / "http-ledger.json", ledger)
        before = ledger["used"]
        runtime._model._client.event_hooks["request"].append(RequestLedger(ROOT / "http-ledger.json", label).before_request)
        original_observer = runtime._model._observer

        def transport_observer(observation: Mapping[str, object]) -> None:
            # 即使解析或 Finalizer 随后失败，也先保留已收到的 Provider 终态与 Usage。
            record["transport"].append(dict(observation))
            write_json(output / "result.json", record)
            original_observer(observation)

        runtime._model._observer = transport_observer
        captured: dict[str, Any] = {}

        async def query(request: QueryRequest) -> Any:
            def event_observer(event: Any) -> None:
                record["events"].append({"type": event.type, "sequence": event.sequence, "tool_name": event.tool_name})
                if event.type in ("tool.started", "tool.completed", "query.failed"):
                    print(json.dumps({"case": label, "event": event.type, "tool": event.tool_name}), flush=True)
            result = await application.query(request, on_event=event_observer)
            captured["result"] = result
            return result

        runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
            store=application.evaluation_store, snapshot_resolver=lambda: snapshot)
        variant = ControlledVariant(variant_id="reply-context-live-20261022:medium", code_version=protocol["code_version"],
            provider="chatgpt-plan", model="gpt-6.1-sol", available_tools=TOOLS,
            model_parameters={"reasoning_effort": "medium"}, prompt_identity="production-system-prompt",
            budget={"max_tool_rounds": 3, "max_turns": 8}, runtime_configuration={"trace_profile": "debug"},
            execution_override=ExecutionOverride(forced_route="standard_execution"))
        evaluation = (await runner.run_case(case, variant, suite_id="reply-context-live-development"))[0]
        result = captured["result"]
        record.update(status=result.execution_status, evaluation=evaluation.to_dict(), result=asdict(result))
        if result.trace_id is not None:
            application.export_trace_log(result.trace_id, output_path=output / "trace.log", context_mode="full")
        record["http_requests"] = read_json(ROOT / "http-ledger.json")["used"] - before
        print(json.dumps({"case": label, "status": result.execution_status,
            "http_requests": record["http_requests"], "tool_rounds": result.runtime_result.tool_rounds,
            "error": result.runtime_result.error.code if result.runtime_result.error else None}), flush=True)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        write_json(output / "result.json", record)
        raise
    finally:
        record["wall_seconds"] = perf_counter() - started
        write_json(output / "result.json", record)
        await application.aclose()


def main() -> None:
    """终端逐题运行，失败先定位，禁止为了好结果自动补跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", *CASES))
    action = parser.parse_args().action
    asyncio.run(prepare() if action == "prepare" else run_case(action))


if __name__ == "__main__":
    main()
