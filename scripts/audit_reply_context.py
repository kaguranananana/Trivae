"""零模型请求地对照固定锚点邻居窗口与显式回复补查。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agents.tool_context import ToolContext

from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.tools import GetMessageContextTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.query.evidence import finalize_answer
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import GetMessageContextSDKToolAdapter


async def audit_case(repository: SQLiteCanonicalReadRepository, targets_path: Path) -> dict[str, object]:
    """仅检查调用者明确指定的 Development 目标，不搜索或打开其他套件。"""
    targets = json.loads(targets_path.read_text())
    messages = [repository.read_message_by_id(target["internal_message_id"]) for target in targets]
    if any(message is None for message in messages):
        raise ValueError(f"target missing in canonical snapshot: {targets_path.name}")
    # 以真实关系确认分享与回复，不假定目标文件中的消息顺序或依赖关键词特例。
    pairs = [(anchor, reply) for anchor in messages for reply in messages
        if anchor is not None and reply is not None and anchor != reply
        and anchor.session_id == reply.session_id
        and anchor.source_message_id is not None
        and reply.reply_to_source_message_id == anchor.source_message_id]
    if len(pairs) != 1:
        raise ValueError(f"expected one explicit anchor/reply pair: {targets_path.name}")
    anchor, reply = pairs[0]
    scope = ExecutionScope(allowed_session_ids=(anchor.session_id,), max_results=100)
    registry = CapabilityRegistry()
    registry.register(GetMessageContextTool(GetMessageContextCapability(repository)))
    sdk_tool = GetMessageContextSDKToolAdapter(registry).as_sdk_tool()
    variants = []
    for name, arguments in (
        ("neighbors_2_2", {"context_before": 2, "context_after": 2}),
        ("neighbors_3_5", {"context_before": 3, "context_after": 5}),
        ("neighbors_2_2_with_replies", {"context_before": 2, "context_after": 2, "include_replies": True}),
        ("direct_replies", {"context_before": 0, "context_after": 0, "include_replies": True}),
    ):
        # 每组使用独立的原 16k 预算池，经过真实 SDK、Capability、模型投影与来源解析。
        context = RuntimeContext(scope=scope, capability_registry=registry,
            available_capabilities=("get_message_context",), run_id=f"reply-audit-{name}")
        context.allocate_tool_call_id("context")
        wrapper = ToolContext(context=context, tool_name="get_message_context", tool_call_id="context",
            tool_arguments=json.dumps({"message_id": anchor.internal_message_id, **arguments}))
        payload = await sdk_tool.on_invoke_tool(wrapper, wrapper.tool_arguments)
        if payload["status"] == "error":
            raise RuntimeError(f"context query failed: {targets_path.name}/{name}: {payload['error']['code']}")
        record = context.tool_results[0]
        visible = {context.resolve_message_source_handle(message["source_id"]): message
            for message in payload["data"]["messages"]}
        target_ids = {message.internal_message_id for message in messages if message is not None}
        citation_validated = False
        if reply.internal_message_id in visible:
            # Host 只验证已送达来源的绑定，不伪造真实模型答案质量分数。
            candidate = json.dumps({"claims": [{"text": "固定目标回复已恢复。", "finding": "固定目标回复已恢复。",
                "criterion": "来源是当前工具返回的真实回复", "sufficiency": "partial",
                "sources": [visible[reply.internal_message_id]["source_id"]], "limitations": []}], "limitations": []})
            artifact = finalize_answer(candidate, run_id=context.run_id, tool_results=tuple(context.tool_results), scope=scope)
            citation_validated = artifact.evidence_items[0].sources[0].reference.internal_message_id == reply.internal_message_id
        variants.append({
            "variant": name,
            "canonical_returned": len(record.message_items),
            "canonical_target_coverage": len(target_ids & {item.message.internal_message_id for item in record.message_items}),
            "model_returned": len(visible),
            "model_target_coverage": len(target_ids & visible.keys()),
            "required_reply_visible": reply.internal_message_id in visible,
            "reply_relation_visible": reply.internal_message_id in visible
                and anchor.internal_message_id in visible
                and visible[reply.internal_message_id].get("reply_to_source_message_id") == anchor.source_message_id
                and visible[reply.internal_message_id].get("reply_to_source_id") == visible[anchor.internal_message_id]["source_id"],
            "citation_validated": citation_validated,
            "projection": payload["model_projection"],
            "truncated": payload["data"]["truncated"],
            "reply_details": payload["data"]["metadata"]["details"],
        })
    return {"case": targets_path.name, "target_count": len(targets), "variants": variants}


def main() -> None:
    """使用只读 canonical 连接；审计输出只能写到新目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--targets", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=False)
    before = arguments.database.stat()
    repository = SQLiteCanonicalReadRepository(arguments.database)
    try:
        results = [asyncio.run(audit_case(repository, targets)) for targets in arguments.targets]
    finally:
        repository.close()
    after = arguments.database.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("canonical snapshot changed during read-only audit")
    # 输出只含覆盖、预算和关系事实；没有模型请求或最终答案质量推断。
    summary = {"model_requests": 0, "snapshot_unchanged": True, "cases": results}
    (arguments.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    for result in results:
        print(result["case"])
        for variant in result["variants"]:
            print(f"  {variant['variant']}: target={variant['model_target_coverage']}/{result['target_count']}, "
                f"reply={variant['required_reply_visible']}, citation={variant['citation_validated']}")
    # 先保存全部事实，再让目标回复、关系或引用未恢复时以非零状态退出。
    for result in results:
        relation = result["variants"][-1]
        if not all(relation[name] for name in ("required_reply_visible", "reply_relation_visible", "citation_validated")):
            raise RuntimeError(f"direct reply recovery failed: {result['case']}")


if __name__ == "__main__":
    main()
