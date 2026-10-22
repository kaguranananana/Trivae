"""真实模型消费远距离回复的隔离合成控制，不冒充真实群聊质量 A/B。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Mapping

from scripts.run_reply_context_live import ROOT
from scripts.run_runtime_budget_followup import RequestLedger, configured_runtime, read_json, write_json
from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.conversation import SQLiteConversationStore
from trivae.interfaces.cli import _print_query_result
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.evidence import answer_source_summaries


async def run() -> None:
    """保留前三题和旧账本，只增加一个预先登记的独立控制。"""
    output = ROOT / "control"
    output.mkdir(exist_ok=False)
    raw = output / "raw"
    raw.mkdir()
    messages = [make_message("anchor", 0, 1_000, "有人试过 NebulaKit 吗？想了解实际体验。", sender_uid="asker")]
    # 反馈没有项目关键词，必须依靠明确回复关系或更深调查恢复。
    messages.extend(make_message(f"noise-{index}", index, 1_000 + index, "今天讨论其他无关事项。")
        for index in range(1, 144))
    messages.append(make_message("reply", 144, 2_000,
        "已经在测试项目跑过，图结构清楚，但导出偶尔缺节点。", sender_uid="reviewer", reply_to="anchor"))
    write_export(raw, "control(100).json", messages, chat_name="合成回复控制", peer_uid=None, version="5.5.64")
    query = "NebulaKit 有人实际试用过吗？反馈如何？"
    # 单独冻结控制条件，不覆盖三条真实 Case 的原始协议。
    write_json(output / "protocol.json", {"synthetic": True, "query": query, "message_count": len(messages),
        "intervening_noise_messages": 143, "expected_reply_id": "qq:100:reply",
        "tools": ["lexical_search", "get_message_context"], "same_global_http_ledger": True,
        "http_maximum": 24, "maximum_per_case": 8, "repetitions": 1}, exclusive=True)
    runtime = configured_runtime()
    application = create_application(output / "control.sqlite3", agent_runtime=runtime,
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3")
    runtime.capability_registry = application.capability_registry
    record = {"synthetic": True, "transport": [], "events": []}
    try:
        application.import_directory(raw)
        application.rebuild_lexical_index()
        await runtime._model._validate_model()
        ledger = read_json(ROOT / "http-ledger.json")
        ledger["attempted_cases"].append("control")
        before = ledger["used"]
        write_json(ROOT / "http-ledger.json", ledger)
        runtime._model._client.event_hooks["request"].append(RequestLedger(ROOT / "http-ledger.json", "control").before_request)
        original_observer = runtime._model._observer

        def observer(observation: Mapping[str, object]) -> None:
            record["transport"].append(dict(observation))
            write_json(output / "result.json", record)
            original_observer(observation)

        runtime._model._observer = observer
        result = await application.query(QueryRequest(query, ExecutionScope(allowed_session_ids=("qq:100",)),
            available_capabilities=("lexical_search", "get_message_context"), trace_profile="debug",
            execution_override=ExecutionOverride(forced_route="standard_execution")))
        record.update(status=result.execution_status, result=asdict(result),
            http_requests=read_json(ROOT / "http-ledger.json")["used"] - before)
        if result.trace_id is not None:
            application.export_trace_log(result.trace_id, output_path=output / "trace.log", context_mode="full")
        # 调用生产 plain CLI 的最终结果渲染器，把实际终端文本保存到独立工件。
        with (output / "terminal.txt").open("x") as stream:
            summaries = answer_source_summaries(result.answer_artifact) if result.answer_artifact is not None else ()
            _print_query_result(result, output_fn=lambda line: stream.write(line + "\n"), source_summaries=summaries)
        print("control_status:", result.execution_status, "http_requests:", record["http_requests"])
        print("control_answer:", result.final_answer)
    except Exception as exc:
        record.update(status="exception", error_type=type(exc).__name__)
        raise
    finally:
        write_json(output / "result.json", record)
        await application.aclose()


if __name__ == "__main__":
    asyncio.run(run())
