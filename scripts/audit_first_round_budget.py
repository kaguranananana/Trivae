"""零模型重放原始搜索及实际补查，隔离首轮投影额度的收益与证据损失。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from scripts.analyze_reply_context_live import model_messages
from scripts.run_reply_context_live import CASES, SOURCE
from scripts.run_runtime_budget_followup import read_json, write_json
from trivae.capabilities import GetMessageContextInput, SearchMessagesInput
from trivae.capabilities.get_message_context import GetMessageContextCapability
from trivae.capabilities.search_messages import LexicalSearchCapability
from trivae.capabilities.tools import GetMessageContextTool, LexicalSearchTool
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.evaluation.contracts import EvaluationCaseBundle
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.evidence import ToolResultProjectionError, build_tool_result_record, project_tool_result_for_model
from trivae.retrieval.lexical import LexicalRetrieval

SAVED = Path("data/evaluation/reply-repair-20261022")


def project(envelope: Any, original: dict[str, Any], scope: Any, budget: int) -> dict[str, Any]:
    """固定检索结果，只改变模型投影上限；预算失败保留错误类型。"""
    record = build_tool_result_record(
        run_id=original["run_id"], tool_call_id=original["tool_call_id"],
        tool_result_id=original["tool_result_id"], tool_name=original["tool_name"], envelope=envelope, scope=scope,
    )
    try:
        payload = project_tool_result_for_model(envelope, record, token_budget=budget)
    except ToolResultProjectionError as exc:
        return {"budget": budget, "error": type(exc).__name__, "visible_ids": [], "tokens": 0}
    # 使用真实短handle解析身份，不能把Host取得的全部消息冒充模型可见消息。
    ids = [record.resolve_source_handle(item["source_id"])[1].message.internal_message_id
           for item in model_messages(payload["data"])]
    return {"budget": budget, "error": None, "visible_ids": ids,
            "tokens": payload["model_projection"]["estimated_tokens"], "metrics": payload["model_projection"]}


def audit(label: str, first_round_budget: int) -> dict[str, Any]:
    """对照原输入和半池候选，不替模型选择更好的锚点。"""
    saved = read_json(SAVED / label / "result.json")
    runtime = saved["result"]["runtime_result"]
    case = EvaluationCaseBundle.from_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.json")
    targets = {item["internal_message_id"] for item in
               read_json(SOURCE / f"cases/quality-dev-context-{CASES[label]}.targets.json")}
    store = SQLiteTraceStore(SAVED / label / "trace.sqlite3")
    try:
        trace = store.read_trace(saved["result"]["trace_id"])
    finally:
        store.close()
    # tool.call.started记录的是已解析的真实参数；不注入GT消息或新查询。
    requests = [event.payload for event in trace.events if event.operation == "tool.call.started"]
    search = next(item["request"] for item in requests if item["tool_name"] == "lexical_search")
    repository = SQLiteCanonicalReadRepository(SAVED / "snapshot/trivae.sqlite3")
    try:
        tool = LexicalSearchTool(LexicalSearchCapability(LexicalRetrieval(repository)))
        envelope = tool.invoke(SearchMessagesInput(**search), case.data_access_scope)
        original = runtime["tool_results"][0]
        # 直接命中顺序必须一致，保证比较对象确实来自同一检索输入。
        hits = [hit.message.internal_message_id for hit in envelope.data.hits]
        old_hits = [item["message"]["internal_message_id"] for item in original["message_items"] if item["is_hit"]]
        assert hits == old_hits, "direct hit identity/order changed"
        # 同轮控制预留不改；单次原始可用上限取保存的运行账本。
        original_budget = runtime["tool_calls"][0]["tool_result_budget"]["effective_per_call_tool_result_budget"]
        baseline = project(envelope, original, case.data_access_scope, original_budget)
        candidate = project(envelope, original, case.data_access_scope, min(first_round_budget, original_budget))
        artifact = saved["result"]["answer_artifact"]
        cited = {source["reference"]["internal_message_id"] for evidence in artifact["evidence_items"]
                 for source in evidence["sources"]}
        for arm in (baseline, candidate):
            visible = set(arm["visible_ids"])
            arm["fixed_targets_visible"] = len(targets & visible)
            arm["original_cited_sources_visible"] = len(cited & visible)
            arm["remaining_run_budget"] = 16_000 - arm["tokens"]
        contexts = [item["request"] for item in requests if item["tool_name"] == "get_message_context"]
        if contexts:
            # 重放模型原本选中的首个补查，既不换锚点，也不增加上下文窗口。
            context_envelope = GetMessageContextTool(GetMessageContextCapability(repository)).invoke(
                GetMessageContextInput(**contexts[0]), case.data_access_scope,
            )
            second_round = [call for call in runtime["tool_calls"] if call["round"] == 2]
            controls = sum(call["model_result_estimated_tokens"] for call in second_round)
            for arm in (baseline, candidate):
                # 两个控制错误的实际成本仍预留；只让首个数据补查消费剩余额度。
                available = arm["remaining_run_budget"] - controls
                arm["actual_followup"] = project(
                    context_envelope, runtime["tool_results"][1], case.data_access_scope, available,
                )
        return {"case": label, "model_requests": 0, "direct_hits_unchanged": True,
                "fixed_target_count": len(targets), "original_cited_source_count": len(cited),
                "baseline": baseline, "candidate": candidate}
    finally:
        repository.close()


def main() -> None:
    """可用require-followup捕获原始补查无法返回证据的失败，不运行模型。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-round-budget", type=int, default=8_000)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-followup", choices=("baseline", "candidate"))
    args = parser.parse_args()
    results = [audit(label, args.first_round_budget) for label in CASES]
    write_json(args.output, {"model_requests": 0, "cases": results}, exclusive=True)
    for item in results:
        print({"case": item["case"], **{arm: {key: value for key, value in item[arm].items()
              if key not in {"visible_ids", "metrics", "actual_followup"}} for arm in ("baseline", "candidate")},
               "followup_counts": {arm: len(item[arm].get("actual_followup", {}).get("visible_ids", []))
                                    for arm in ("baseline", "candidate")}})
    if args.require_followup:
        archify = next(item for item in results if item["case"] == "archify")
        assert archify[args.require_followup]["actual_followup"]["visible_ids"], "actual followup delivered no messages"


if __name__ == "__main__":
    main()
