"""零模型请求重放旧搜索输入，确认回复恢复且原始命中顺序不变。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.analyze_reply_context_live import model_messages
from scripts.run_reply_context_live import CASES, SOURCE
from scripts.run_reply_context_live import ROOT as BASELINE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.capabilities import SearchMessagesInput
from trivae.capabilities.search_messages import LexicalSearchCapability
from trivae.capabilities.tools import LexicalSearchTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import EvaluationCaseBundle
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.lexical import LexicalRetrieval


def verify(root: Path, label: str) -> dict[str, object]:
    """保持旧工具参数、快照和单次额度，只检验当前检索及投影代码。"""
    saved = read_json(BASELINE / label / "result.json")
    original = saved["result"]["runtime_result"]["tool_results"][0]
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.json")
    targets = read_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.targets.json")
    target_ids = {item["internal_message_id"] for item in targets}
    store = SQLiteTraceStore(BASELINE / label / "trace.sqlite3")
    try:
        trace = store.read_trace(saved["result"]["trace_id"])
    finally:
        store.close()
    request = next(event.payload["request"] for event in trace.events if event.operation == "tool.call.started")
    old_projection = next(item["output_projection"] for event in trace.events
        for item in event.payload.get("model_visible_context", [])
        if item.get("type") == "function_call_output")
    budget = old_projection["model_projection"]["token_budget"]
    repository = SQLiteCanonicalReadRepository(root / "snapshot/trivae.sqlite3")
    try:
        tool = LexicalSearchTool(LexicalSearchCapability(LexicalRetrieval(repository)))
        envelope = tool.invoke(SearchMessagesInput(**request), case.data_access_scope)
    finally:
        repository.close()
    record = build_tool_result_record(run_id=original["run_id"], tool_call_id=original["tool_call_id"],
        tool_result_id=original["tool_result_id"], tool_name=original["tool_name"],
        envelope=envelope, scope=case.data_access_scope)
    # 自动 context 允许改变；直接命中的身份及顺序必须与实际旧运行一致。
    old_hits = [item["message"]["internal_message_id"] for item in original["message_items"] if item["is_hit"]]
    new_hits = [item.message.internal_message_id for item in record.message_items if item.is_hit]
    assert new_hits == old_hits, "direct retrieval hits changed"
    projection = project_tool_result_for_model(envelope, record, token_budget=budget)
    messages = model_messages(projection["data"])
    visible = {record.resolve_source_handle(item["source_id"])[1].message.internal_message_id: item
        for item in messages}
    assert target_ids <= visible.keys(), "target share/reply missing from actual model projection"
    anchor_id, reply_id = (item["internal_message_id"] for item in targets)
    assert visible[reply_id]["reply_to_source_id"] == visible[anchor_id]["source_id"], "reply handle detached"
    assert len(record.message_items) <= request["limit"], "search capacity expanded"
    return {"case": label, "model_requests": 0, "direct_hits_unchanged": True,
        "hit_count": len(new_hits), "canonical_count": len(record.message_items), "visible_count": len(visible),
        "model_target_coverage": len(target_ids & visible.keys()), "target_count": len(target_ids),
        "relation_resolves": True, "projection": projection["model_projection"],
        "context": dict(envelope.data.metadata.details)}


def main() -> None:
    """独立保存修复核验，不覆盖旧失败和旧诊断结论。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root
    results = [verify(root, label) for label in CASES]
    write_json(root / "repair-replay.json", {"cases": results, "model_requests": 0}, exclusive=True)
    for result in results:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
