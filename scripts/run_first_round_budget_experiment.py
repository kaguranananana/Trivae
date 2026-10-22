"""同一总池的首轮8k对照；候选限制只在实验进程生效，不修改生产默认。"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping
from unittest.mock import patch

from scripts.run_runtime_budget_followup import (
    CASES as BUDGET_CASES,
)
from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.bootstrap.application import create_application
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationCaseBundle
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.variant import ControlledVariant
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime import openai_tools
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path("data/evaluation/first-round-budget-20261022/live")
SOURCE = Path("data/evaluation/quality-optimization-20261020")
TOOLS = ("lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
         "find_members", "get_schema", "execute_sql")
CASES = {
    "archify": SOURCE / "cases/quality-dev-context-archify.json",
    "matt1": SOURCE / "cases/quality-dev-context-mattpocock-1.json",
    "miner": BUDGET_CASES["miner"][0],
}
# 交替A/B顺序，避免所有候选总在基线之后；每个unit只运行一次。
ORDER = ("archify-baseline", "archify-candidate", "matt1-candidate", "matt1-baseline",
         "miner-baseline", "miner-candidate")


@contextmanager
def first_round_limit(limit: int | None) -> Iterator[None]:
    """在真实SDK准入入口设置同轮总额；第二轮起仍使用原共享账本。"""
    if limit is None:
        yield
        return
    reserve = openai_tools.reserve_budget_stop_results
    resolve = openai_tools._tool_runtime_context
    limits: dict[str, int] = {}

    def reserve_round(context: Any, calls: list[tuple[str, str]]) -> None:
        # 先执行原有协议预留，保证每个工具调用都能得到合法响应。
        reserve(context, calls)
        if context.current_tool_round == 1:
            # 同轮多个请求均分上限，不能让每个请求各自领取完整8k。
            quota = limit // len(calls)
            limits.update((context.resolve_tool_call_id(provider_id), quota) for _, provider_id in calls)

    def resolve_call(context: Any, name: str) -> Any:
        runtime, call_id, trace, reservation = resolve(context, name)
        if runtime.current_tool_round == 1:
            # 原入口尚未执行能力；归还其预留后，按本轮份额重新预留。
            runtime.tool_result_budget_policy.cancel_call(reservation)
            minimum = openai_tools.minimum_budget_stop_tokens(runtime, name, call_id)
            reservation = runtime.tool_result_budget_policy.begin_call(
                minimum_budget=minimum, maximum_budget=limits[call_id],
            )
        return runtime, call_id, trace, reservation

    # adapter引用的是导入后的函数，两个入口都需替换；作用域结束恢复原函数。
    with patch("trivae.query.runtime.openai_adapter.reserve_budget_stop_results", reserve_round), \
         patch.object(openai_tools, "_tool_runtime_context", resolve_call):
        yield


def open_application(unit: str, runtime: Any) -> Any:
    """各unit独立保存会话与Trace，共享本轮独立克隆的数据及既有语义索引。"""
    output = ROOT / unit
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


def inspect(application: Any, label: str) -> tuple[Any, Any, Any]:
    """核对原题与快照身份，索引不完整时显式失败，不重建或重绑GT。"""
    case = EvaluationCaseBundle.from_json(CASES[label])
    snapshot = DatasetSnapshot.from_database(ROOT / "snapshot/trivae.sqlite3")
    semantic = application.semantic_index_status().to_dict()
    if snapshot.snapshot_id != case.dataset_snapshot.snapshot_id or semantic["status"] != "completed":
        raise RuntimeError("original case/snapshot or completed semantic index changed")
    return case, snapshot, semantic


async def prepare() -> None:
    """先保存条件和独立请求账本，旧实验工件不覆盖。"""
    ROOT.mkdir(parents=True, exist_ok=False)
    (ROOT / "snapshot").mkdir()
    for name in ("trivae.sqlite3", "trivae.semantic.sqlite3"):
        subprocess.run(["cp", "-c", str(SOURCE / name), str(ROOT / "snapshot" / name)], check=True)
    protocol: dict[str, Any] = {
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "system_prompt": SYSTEM_PROMPT, "order": ORDER, "first_round_candidate_budget": 8_000,
        "total_tool_result_pool": 16_000, "max_tool_rounds": 3, "max_turns": 8,
        "provider": "chatgpt-plan", "model": "gpt-6.1-sol", "effort": "medium",
        "automatic_retries": False, "judge": False, "cases": {},
    }
    for label in CASES:
        runtime = configured_runtime()
        application = open_application(f"{label}-baseline", runtime)
        try:
            case, snapshot, semantic = inspect(application, label)
            protocol["cases"][label] = {"case": case.to_dict(), "snapshot": snapshot.to_dict(),
                "semantic": semantic, "runtime": runtime.safe_configuration()}
        finally:
            await application.aclose()
    write_json(ROOT / "protocol.json", protocol, exclusive=True)
    write_json(ROOT / "http-ledger.json", {"maximum": 48, "maximum_per_case": 8, "used": 0,
        "attempts": [], "blocked": [], "attempted_cases": []}, exclusive=True)
    # 保存实际执行脚本原文，使用可读内容而非额外摘要算法标识条件。
    (ROOT / "runner.py").write_text(Path(__file__).read_text(), encoding="utf-8")
    print({"prepared_units": len(ORDER), "http_maximum": 48}, flush=True)


async def run_unit(unit: str) -> None:
    """真实模型自己选择工具及证据；不得因结果不好而重复同一unit。"""
    label, arm = unit.rsplit("-", 1)
    protocol = read_json(ROOT / "protocol.json")
    ledger = read_json(ROOT / "http-ledger.json")
    if unit in ledger["attempted_cases"]:
        raise RuntimeError("unit already attempted")
    runtime = configured_runtime()
    application = open_application(unit, runtime)
    record: dict[str, Any] = {"unit": unit, "transport": []}
    output = ROOT / unit
    captured: dict[str, Any] = {}
    try:
        case, snapshot, semantic = inspect(application, label)
        frozen = protocol["cases"][label]
        if (json.dumps(case.to_dict(), sort_keys=True) != json.dumps(frozen["case"], sort_keys=True)
                or semantic != frozen["semantic"]
                or runtime.safe_configuration() != frozen["runtime"] or SYSTEM_PROMPT != protocol["system_prompt"]
                or Path(__file__).read_text() != (ROOT / "runner.py").read_text()):
            raise RuntimeError("frozen execution conditions changed")
        await runtime._model._validate_model()
        ledger["attempted_cases"].append(unit)
        write_json(ROOT / "http-ledger.json", ledger)
        before = ledger["used"]
        runtime._model._client.event_hooks["request"].append(RequestLedger(ROOT / "http-ledger.json", unit).before_request)
        observer = runtime._model._observer

        def observe(value: Mapping[str, object]) -> None:
            # 真实流和Usage先落盘，后续解析失败也保留发送事实。
            record["transport"].append(dict(value))
            write_json(output / "result.json", record)
            observer(value)

        runtime._model._observer = observe

        async def query(request: QueryRequest) -> Any:
            captured["result"] = await application.query(request)
            return captured["result"]

        variant = ControlledVariant(
            variant_id=f"first-round-budget:{arm}", code_version=protocol["code_version"],
            provider="chatgpt-plan", model="gpt-6.1-sol", available_tools=TOOLS,
            model_parameters={"reasoning_effort": "medium"}, prompt_identity="production-system-prompt",
            budget={"max_tool_rounds": 3, "max_turns": 8, "first_round_budget": 8_000 if arm == "candidate" else 16_000},
            execution_override=ExecutionOverride(forced_route="standard_execution"),
        )
        runner = EvaluationRunner(query_executor=query, trace_reader=application.read_trace,
                                  store=application.evaluation_store, snapshot_resolver=lambda: snapshot)
        with first_round_limit(8_000 if arm == "candidate" else None):
            evaluation = (await runner.run_case(case, variant, suite_id="first-round-budget-development"))[0]
        result = captured["result"]
        record.update(status=result.execution_status, result=asdict(result), evaluation=evaluation.to_dict(),
                      http_requests=read_json(ROOT / "http-ledger.json")["used"] - before)
        print({"unit": unit, "status": result.execution_status, "http_requests": record["http_requests"]}, flush=True)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        raise
    finally:
        write_json(output / "result.json", record)
        await application.aclose()


def main() -> None:
    """预检与每条unit分开，失败后先定位，不启动自动补跑。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", *ORDER))
    action = parser.parse_args().action
    asyncio.run(prepare() if action == "prepare" else run_unit(action))


if __name__ == "__main__":
    main()
