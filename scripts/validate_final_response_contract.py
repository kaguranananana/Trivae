"""重放真实空结果失败的工具决策，只让最终综合交给真实模型；不声称自主检索验收。"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from trivae.bootstrap.application import create_application
from trivae.conversation import SQLiteConversationStore
from trivae.evaluation.contracts import DatasetSnapshot, EvaluationCaseBundle
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path("data/evaluation/final-response-contract-20261022")
SOURCE = Path("data/evaluation/quality-optimization-20261020")
HISTORY = SOURCE / "validation/quality-dev-zero-empty-2/candidate/quality-dev-zero-empty-2.json"
CASE = SOURCE / "cases/quality-dev-zero-empty-2.json"


def replay_steps(saved: dict[str, Any]) -> list[ModelStep]:
    """按保存的轮次组合原工具参数，不注入新的查询或目标证据。"""
    runtime = saved["result"]["runtime_result"]
    rounds: dict[int, list[Any]] = {}
    for index, (call, record) in enumerate(zip(runtime["tool_calls"], runtime["tool_results"], strict=True)):
        scope = record["query_scope_snapshot"]
        if call["name"] == "get_schema":
            arguments = {}
        elif call["name"] == "execute_sql":
            arguments = scope["query"]
        else:
            # 历史recent调用已有明确绝对时间窗，直接保留，不重新计算日期。
            arguments = {key: scope[key] for key in ("start_timestamp", "end_timestamp", "limit")}
        rounds.setdefault(call["round"], []).append(function_call(
            # Plan通过公开trivae namespace分发；回放也必须保留同一SDK接口契约。
            call["name"], arguments, call_id=f"recorded-{index}", namespace="trivae",
        ))
    return [ModelStep(output=calls) for calls in rounds.values()]


async def run(mode: str, output_dir: Path | None = None) -> None:
    """offline保留原错误答案；live只运行一次真实最终综合，失败也不重试。"""
    output = output_dir or ROOT / mode
    output.mkdir(parents=True, exist_ok=False)
    saved = read_json(HISTORY)
    case = EvaluationCaseBundle.from_json(CASE)
    # 从同一冻结源克隆，不写回历史数据库或语义索引。
    database = output / "trivae.sqlite3"
    subprocess.run(["cp", "-c", str(SOURCE / "trivae.sqlite3"), str(database)], check=True)
    snapshot = DatasetSnapshot.from_database(database)
    if snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
        raise RuntimeError("historical case snapshot changed")
    runtime = configured_runtime()
    real_model = runtime._model
    record: dict[str, Any] = {"mode": mode, "transport": [], "history_replayed": True}
    steps = replay_steps(saved)
    if mode == "live":
        # 目录预检不是推理；旧实验账本保持只读，新账本只允许一次真实综合请求。
        await real_model._validate_model()
        ledger = output / "http-ledger.json"
        write_json(ledger, {"maximum": 1, "maximum_per_case": 1, "used": 0,
                            "attempts": [], "blocked": []}, exclusive=True)
        real_model._client.event_hooks["request"].append(RequestLedger(ledger, "zero-empty-2").before_request)
        observer = real_model._observer

        def observe(value: Any) -> None:
            record["transport"].append(dict(value))
            write_json(output / "result.json", record)
            observer(value)

        real_model._observer = observe

        def stream_final(call: Any) -> Any:
            # 原工具历史占满3轮后，真实模型必须在无工具状态下选择输出格式。
            assert not call.tools, "final synthesis unexpectedly exposes tools"
            assert "Host-verified no_result eligibility: unavailable." in call.system_instructions
            write_json(output / "final-model-input.json", {"instructions": call.system_instructions,
                       "input": call.input}, exclusive=True)
            fields = ("system_instructions", "input", "model_settings", "tools", "output_schema",
                      "handoffs", "tracing", "previous_response_id", "conversation_id", "prompt")
            return real_model.stream_response(**{key: getattr(call, key) for key in fields})

        steps.append(ModelStep(stream_events=stream_final))
    else:
        steps.append(ModelStep(output=[assistant_message(saved["result"]["runtime_result"]["final_answer"])]))
    runtime._model = ScriptedModel(steps)
    application = create_application(
        database, agent_runtime=runtime,
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    runtime.capability_registry = application.capability_registry
    # 协议明确区分固定历史与自主检索，保存当前执行版本和可读脚本。
    write_json(output / "protocol.json", {"mode": mode, "case": case.to_dict(),
        "code_version": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "system_prompt": SYSTEM_PROMPT, "runtime": runtime.safe_configuration(),
        "fixed_tool_history": True, "real_synthesis_http_maximum": 1 if mode == "live" else 0}, exclusive=True)
    (output / "runner.py").write_text(Path(__file__).read_text(), encoding="utf-8")
    try:
        result = await application.query(QueryRequest(
            query=case.query, scope=case.data_access_scope,
            execution_override=ExecutionOverride(forced_route="standard_execution"),
        ))
        record.update(status=result.execution_status, result=asdict(result))
        print({"mode": mode, "status": result.execution_status, "finalization": result.finalization_status,
               "real_responses": len(record["transport"])}, flush=True)
        if mode == "offline":
            assert result.runtime_result.termination == "completed", "tool-history replay failed before finalization"
            assert result.finalization_error is not None, "historical invalid no_result was silently accepted"
        else:
            assert result.is_successful, "real synthesis did not produce a deliverable answer"
            assert result.answer_artifact.citation_bindings, "statistics answer lacks citations"
    finally:
        write_json(output / "result.json", record)
        await application.aclose()


def main() -> None:
    """两个模式独立留档，不自动补跑真实请求。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("offline", "live"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.output))


if __name__ == "__main__":
    main()
