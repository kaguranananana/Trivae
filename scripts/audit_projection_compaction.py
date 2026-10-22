"""不删证据的投影精简候选：声明公共默认值，省略词法排序实现细节。"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from scripts.analyze_reply_context_live import model_messages
from scripts.audit_first_round_budget import SAVED
from scripts.run_reply_context_live import CASES, SOURCE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.capabilities import SearchMessagesInput
from trivae.capabilities.search_messages import LexicalSearchCapability
from trivae.capabilities.tools import LexicalSearchTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import EvaluationCaseBundle
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query import evidence
from trivae.retrieval.lexical import LexicalRetrieval


@contextmanager
def legacy_projection() -> Iterator[None]:
    """仅为实验关闭已上线的精简编码，不在产品中添加回退或兼容开关。"""
    with patch.object(evidence, "_compact_model_message_fields", lambda _data, _entries: None):
        yield


def restored_messages(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按公开默认值还原消息，逐字段核对事实，而非仅比较旧GT覆盖。"""
    defaults = payload["data"].get("message_defaults", {})
    # JSON表示统一tuple/list；真实HTTP序列化同样把URL tuple变成数组。
    import json
    return {item["source_id"]: json.loads(json.dumps({**defaults, **item}, ensure_ascii=False))
            for item in model_messages(payload["data"])}


def audit(label: str) -> dict[str, Any]:
    """固定相同原始搜索结果及15,801上限，保留每条原可见证据的全部事实。"""
    saved = read_json(SAVED / label / "result.json")
    original = saved["result"]["runtime_result"]["tool_results"][0]
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.json")
    store = SQLiteTraceStore(SAVED / label / "trace.sqlite3")
    try:
        trace = store.read_trace(saved["result"]["trace_id"])
    finally:
        store.close()
    request = next(event.payload["request"] for event in trace.events if event.operation == "tool.call.started")
    repository = SQLiteCanonicalReadRepository(SAVED / "snapshot/trivae.sqlite3")
    try:
        envelope = LexicalSearchTool(LexicalSearchCapability(LexicalRetrieval(repository))).invoke(
            SearchMessagesInput(**request), case.data_access_scope,
        )
    finally:
        repository.close()
    record = evidence.build_tool_result_record(run_id=original["run_id"], tool_call_id=original["tool_call_id"],
        tool_result_id=original["tool_result_id"], tool_name=original["tool_name"], envelope=envelope,
        scope=case.data_access_scope)
    with legacy_projection():
        baseline = evidence.project_tool_result_for_model(envelope, record, token_budget=15_801)
    candidate = evidence.project_tool_result_for_model(envelope, record, token_budget=15_801)
    before, after = restored_messages(baseline), restored_messages(candidate)
    assert before.keys() <= after.keys(), "compaction lost a visible message"
    assert all(value == after[key] for key, value in before.items()), "compaction changed message facts"
    return {"case": label, "all_original_message_facts_preserved": True,
            "baseline_tokens": baseline["model_projection"]["estimated_tokens"],
            "candidate_tokens": candidate["model_projection"]["estimated_tokens"],
            "visible_messages": [len(before), len(after)], "candidate_remaining": 16_000 - candidate["model_projection"]["estimated_tokens"]}


def main() -> None:
    """保存无模型对照；每一事实字段不变才算通过。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [audit(label) for label in CASES]
    write_json(args.output, {"model_requests": 0, "cases": results}, exclusive=True)
    for item in results:
        print(item)


if __name__ == "__main__":
    main()
