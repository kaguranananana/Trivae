"""零模型请求重放真实失败，隔离回复丢失层级、锚点选择与投影预算。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_reply_context_live import model_messages
from scripts.run_reply_context_live import CASES, ROOT, SOURCE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.capabilities import GetMessageContextInput, SearchMessagesInput
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.scope import scope_filters
from trivae.capabilities.search_messages import LexicalSearchCapability
from trivae.capabilities.tools import GetMessageContextTool, LexicalSearchTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import EvaluationCaseBundle
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.evidence import ToolResultProjectionError, build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.lexical import LexicalRetrieval

OUTPUT = Path("data/evaluation/reply-miss-diagnosis-20261022")


def projection_facts(envelope: Any, original: dict[str, Any], scope: Any, budget: int, target: str) -> dict[str, Any]:
    """走真实投影代码，只比较稳定消息身份，不把耗时元数据当成检索变化。"""
    record = build_tool_result_record(run_id=original["run_id"], tool_call_id=original["tool_call_id"],
        tool_result_id=original["tool_result_id"], tool_name=original["tool_name"], envelope=envelope, scope=scope)
    canonical_ids = [item.message.internal_message_id for item in record.message_items]
    try:
        payload = project_tool_result_for_model(envelope, record, token_budget=budget)
    except ToolResultProjectionError as exc:
        return {"canonical_ids": canonical_ids, "target_in_host": target in canonical_ids,
            "projection_error": type(exc).__name__, "target_visible": False, "token_budget": budget}
    ids = {record.resolve_source_handle(message["source_id"])[1].message.internal_message_id
        for message in model_messages(payload["data"])}
    return {"canonical_ids": canonical_ids, "target_in_host": target in canonical_ids,
        "target_visible": target in ids, "visible_count": len(ids), "metrics": payload["model_projection"]}


def diagnose(label: str) -> dict[str, Any]:
    """固定过去已经发生的输入，反事实正确锚点仅用于定位，不算模型自主成功。"""
    saved = read_json(ROOT / label / "result.json")
    runtime = saved["result"]["runtime_result"]
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.json")
    targets = read_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.targets.json")
    anchor_id, reply_id = (target["internal_message_id"] for target in targets)
    store = SQLiteTraceStore(ROOT / label / "trace.sqlite3")
    try:
        trace = store.read_trace(saved["result"]["trace_id"])
    finally:
        store.close()
    requests = [event.payload for event in trace.events if event.operation == "tool.call.started"]
    outputs = {item["call_id"]: item["output_projection"] for event in trace.events
        for item in event.payload.get("model_visible_context", []) if item.get("type") == "function_call_output"}
    search_payload = next(payload for payload in outputs.values() if (payload.get("data") or {}).get("strategy") == "lexical")
    context_payload = next(payload for payload in outputs.values() if (payload.get("data") or {}).get("strategy") == "context")
    original = runtime["tool_results"][0]
    repository = SQLiteCanonicalReadRepository(ROOT / "snapshot/trivae.sqlite3")
    try:
        tool = LexicalSearchTool(LexicalSearchCapability(LexicalRetrieval(repository)))
        envelope = tool.invoke(SearchMessagesInput(**requests[0]["request"]), case.data_access_scope)
        retrieval = envelope.data
        first = projection_facts(envelope, original, case.data_access_scope,
            search_payload["model_projection"]["token_budget"], reply_id)
        original_ids = [item["message"]["internal_message_id"] for item in original["message_items"]]
        if first["canonical_ids"] != original_ids:
            raise RuntimeError("replayed canonical message sequence differs from the saved run")
        hits = [hit.message.internal_message_id for hit in retrieval.hits]
        anchor = repository.read_message_by_id(anchor_id)
        reply = repository.read_message_by_id(reply_id)
        if anchor is None or reply is None:
            raise RuntimeError("fixed target missing in original snapshot")
        # 原始实际输入中的短 handle，独立于 Host 完整候选，核对模型是否有机会选中锚点。
        original_visible = {message["source_id"]: message for message in model_messages(search_payload["data"])}
        source_handle = f"m1-{original_ids.index(anchor_id) + 1}" if anchor_id in original_ids else None
        context_request = next(item["request"] for item in requests if item["tool_name"] == "get_message_context")
        chosen = repository.read_message_by_id(context_request["message_id"])
        if chosen is None:
            raise RuntimeError("chosen anchor no longer exists")
        context_tool = GetMessageContextTool(GetMessageContextCapability(repository))
        counterfactual = context_tool.invoke(GetMessageContextInput(anchor_id,
            context_before=context_request["context_before"], context_after=context_request["context_after"],
            include_replies=True), case.data_access_scope)
        context_original = runtime["tool_results"][1]
        same_budget = context_payload["model_projection"]["token_budget"]
        # 只换锚点，保留实际窗口与该次可用预算，检验锚点修正能否独立恢复回复。
        correct_anchor = projection_facts(counterfactual, context_original, case.data_access_scope, same_budget, reply_id)
        # 固定同一份正确锚点结果，只改变投影额度，隔离裁剪的影响。
        sufficient_budget = projection_facts(counterfactual, context_original, case.data_access_scope, 16_000, reply_id)
        relation_only = context_tool.invoke(GetMessageContextInput(anchor_id,
            context_before=0, context_after=0, include_replies=True), case.data_access_scope)
        no_neighbors = projection_facts(relation_only, context_original, case.data_access_scope, same_budget, reply_id)
        return {"case": label, "model_requests": 0, "original_sequence_reproduced": True,
            "share_direct_rank": hits.index(anchor_id) + 1 if anchor_id in hits else None,
            "share_source_handle": source_handle, "share_visible": source_handle in original_visible,
            "share_model_entry_fields": sorted(original_visible[source_handle]) if source_handle in original_visible else [],
            "reply_is_direct_hit": reply_id in hits, "first_search_replay": first,
            "original_projection": search_payload["model_projection"],
            "automatic_context": dict(retrieval.metadata.details),
            "original_anchor_excerpt": anchor.normalized_content, "required_reply_excerpt": reply.normalized_content,
            "chosen_anchor_excerpt": chosen.normalized_content, "chosen_anchor_is_target": chosen.internal_message_id == anchor_id,
            "target_anchor_returned_replies": counterfactual.data.metadata.details["returned_replies"],
            "chosen_anchor_reply_count_lower_bound": len(repository.read_message_replies_scoped(chosen,
                scope_filters(case.data_access_scope), 100)),
            "actual_context_window": context_request, "actual_context_token_budget": same_budget,
            "correct_anchor_same_budget": correct_anchor, "correct_anchor_16k": sufficient_budget,
            "correct_anchor_relation_only_same_budget": no_neighbors}
    finally:
        repository.close()


def main() -> None:
    """诊断可独立重放；require-delivery 用于捕获 Host 已取得却没送达的原始失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(CASES))
    parser.add_argument("--require-delivery", action="store_true")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    results = [diagnose(label) for label in ([args.case] if args.case else CASES)]
    if args.save:
        write_json(OUTPUT / "diagnosis.json", {"model_requests": 0, "cases": results}, exclusive=True)
    for result in results:
        print(json.dumps({"case": result["case"], "share_rank": result["share_direct_rank"],
            "share_visible": result["share_visible"], "reply_in_host": result["first_search_replay"]["target_in_host"],
            "reply_visible": result["first_search_replay"]["target_visible"],
            "correct_anchor_same_budget": result["correct_anchor_same_budget"]["target_visible"],
            "relation_only_same_budget": result["correct_anchor_relation_only_same_budget"]["target_visible"]}))
    if args.require_delivery:
        assert all(result["first_search_replay"]["target_visible"] for result in results), "required reply missing from model projection"


if __name__ == "__main__":
    main()
