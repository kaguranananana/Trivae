"""零模型重放真实反问问题，比较原顺序与精确词检索的证据送达。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from agents.tool_context import ToolContext

from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope
from trivae.config.model_capabilities import resolve_context_window
from trivae.conversation import SQLiteConversationStore
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.runtime.budget import ToolResultBudgetConfig
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import (
    GetMessageContextSDKToolAdapter,
    LexicalSearchSDKToolAdapter,
    SemanticSearchSDKToolAdapter,
    protect_tool_result_budget,
    reserve_budget_stop_results,
)

TRACE = "trace-f1115af93ba4485bb7d2b0de982bace1"
# 独立人工核对的真人原文；分别覆盖初创尽调、团队工作、技术追问与短期产出。
TARGETS = {
    "startup": "产品（pmf",
    "team": "正式员工和实习生的比例",
    "technical": "现在采用什么记忆范式",
    "milestone": "里程碑成果",
}


def messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """只读取实际模型投影正文，不把Host命中数当作模型已读消息数。"""
    data = payload["data"]
    return ([hit["message"] for hit in data.get("hits", []) if "message" in hit]
            + data.get("expanded_messages", []) + data.get("messages", []))


async def audit(database: Path, output: Path) -> dict[str, Any]:
    """保留同一语料、参数和16k共享池；仅比较先读哪条已有检索路径。"""
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        # 原Trace不包含完整投影正文，因此必须重走真实Capability及SDK投影。
        events = [(op, json.loads(raw)) for op, raw in connection.execute(
            "SELECT operation, payload_json FROM trace_events WHERE trace_id=? ORDER BY sequence", (TRACE,)
        )]
    received = next(payload for op, payload in events if op == "query.received")
    calls = [item for op, payload in events if op == "model.output"
             for item in payload["observable_output"] if item.get("type") == "function_call"]
    application = create_application(
        database, semantic_index_path=database.with_name("trivae.semantic.sqlite3"),
        conversation_store=SQLiteConversationStore(output / "conversation.sqlite3"),
        trace_store=SQLiteTraceStore(output / "trace.sqlite3"),
        evaluation_database_path=output / "evaluation.sqlite3", feedback_database_path=output / "feedback.sqlite3",
    )
    try:
        report: dict[str, Any] = {"trace_id": TRACE, "query": received["query"], "model_requests": 0, "arms": {}}
        for arm, selected in (("original", calls), ("lexical_first", [calls[1]]), ("registered_and_reads", calls)):
            # 每组创建独立预算账本，禁止复用另一组已消费的额度或来源handle。
            context = RuntimeContext(scope=ExecutionScope(**received["scope"]),
                capability_registry=application.capability_registry,
                available_capabilities=("lexical_search", "semantic_search", "get_message_context"), run_id=arm)
            if arm == "registered_and_reads":
                resolution = resolve_context_window(explicit_context_window_tokens=None,
                                                    provider="chatgpt-plan", model_name="gpt-6.1-sol")
                context.tool_result_budget_policy = ToolResultBudgetConfig(
                    context_window_tokens=resolution.context_window_tokens,
                    context_window_source=resolution.source).new_policy()
            results = []
            names = []
            for ordinal, call in enumerate(selected, 1):
                adapter = (SemanticSearchSDKToolAdapter if call["name"] == "semantic_search"
                           else LexicalSearchSDKToolAdapter)(application.capability_registry)
                tool = adapter.as_sdk_tool(trusted_max_results=context.scope.max_results)
                protect_tool_result_budget(tool)
                call_id = f"{arm}-{ordinal}"
                context.allocate_tool_call_id(call_id)
                # 与生产同样预留每轮控制结果，不能省略这笔开销使离线重放虚增可用额度。
                reserve_budget_stop_results(context, [(call["name"], call_id)])
                wrapper = ToolContext(context=context, tool_name=call["name"], tool_call_id=call_id,
                                      tool_arguments=call["arguments"])
                # 走真实解析、检索、来源绑定和投影，预算错误直接暴露。
                result = await tool.on_invoke_tool(wrapper, call["arguments"])
                if result["status"] == "error":
                    raise RuntimeError(result["error"])
                results.append(result)
                names.append(call["name"])
            if arm == "registered_and_reads":
                # 已知原文目标只用于验证补读能力，不冒充模型自主选择来源的结果。
                visible_text = "\n".join(message["content"] for result in results for message in messages(result))
                missing = [phrase for phrase in TARGETS.values() if phrase not in visible_text]
                anchors = dict.fromkeys(
                    f"m{record.model_scope_id}-{index + 1}"
                    for record in context.tool_results for index, item in enumerate(record.message_items)
                    if any(phrase in item.message.normalized_content for phrase in missing)
                )
                for handle in anchors:
                    tool = GetMessageContextSDKToolAdapter(application.capability_registry).as_sdk_tool()
                    protect_tool_result_budget(tool)
                    call_id = f"{arm}-{len(results) + 1}"
                    context.allocate_tool_call_id(call_id)
                    reserve_budget_stop_results(context, [("get_message_context", call_id)])
                    arguments = json.dumps({"source_id": handle, "context_before": 0, "context_after": 0})
                    wrapper = ToolContext(context=context, tool_name="get_message_context", tool_call_id=call_id,
                                          tool_arguments=arguments)
                    result = await tool.on_invoke_tool(wrapper, arguments)
                    if result["status"] == "error":
                        raise RuntimeError(result["error"])
                    results.append(result)
                    names.append("get_message_context")
            (output / f"{arm}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            visible = [message for result in results for message in messages(result)]
            report["arms"][arm] = {
                "calls": [{"name": name, **result["model_projection"]}
                          for name, result in zip(names, results, strict=True)],
                "targets": {name: any(phrase in message["content"] for message in visible)
                            for name, phrase in TARGETS.items()},
            }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    finally:
        await application.aclose()


def main() -> None:
    """允许用原顺序的缺失触发失败；该断言验证证据覆盖而非Prompt字面。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/trivae.sqlite3"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-coverage", choices=("original", "lexical_first", "registered_and_reads"))
    args = parser.parse_args()
    report = asyncio.run(audit(args.database, args.output))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_coverage:
        assert all(report["arms"][args.require_coverage]["targets"].values()), "真人反问清单未全部送达模型"


if __name__ == "__main__":
    main()
