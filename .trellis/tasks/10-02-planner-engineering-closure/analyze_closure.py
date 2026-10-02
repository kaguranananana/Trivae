"""复用既有 usage/GT 契约，从正式 raw 派生事实与逐 Claim 来源检查包。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evaluation/planner-p1-stability"))
from run_engineering_closure import TREATMENTS, verify_initial_requests  # noqa: E402
from run_p1_e2e import usage_for, write_json  # noqa: E402

from trivae.evaluation.benchmark.judge import canonical_message_excerpt  # noqa: E402


def provider_calls(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按每次公开 SSE 的 index 拼接原始 function arguments，不用 normalized Trace 替代。"""
    calls = []
    for request in requests:
        # 每个 HTTP response 的 SSE index 独立，不能跨模型轮次拼接参数。
        merged = {}
        response = request["response"]
        if response is None:
            # 收口分析须暴露缺失响应，不能跳过失败来缩小实际分母。
            raise ValueError("formal Provider request has no recorded response")
        for chunk in response["chunks"]:
            for choice in chunk.get("choices", []):
                for call in choice.get("delta", {}).get("tool_calls", []):
                    target = merged.setdefault(call["index"], {"name": "", "arguments": ""})
                    for key in target:
                        # 公开 delta 按到达顺序拼接；随后才解析原始 JSON 参数。
                        target[key] += call.get("function", {}).get(key, "") or ""
        calls.extend({"name": c["name"], "arguments": json.loads(c["arguments"])} for c in merged.values())
    return calls


def analyze(directory: Path) -> dict[str, Any]:
    """只给出确定性事实；语义审核单列，不用 Tool 次数生成质量总分。"""
    rows = [json.loads(s) for s in (directory / "runs.jsonl").read_text().splitlines()]
    preflight = json.loads((directory / "preflight.json").read_text())
    truths = {c["case"]["case_id"]: c["ground_truth"] for c in preflight["cases"]}
    # 正式分母固定为八个 Case 的两路配对；不接受删失败或追加重复的数据。
    if len(rows) != 16 or len({(r["case_id"], r["treatment"]) for r in rows}) != 16:
        raise ValueError("requires the 16 unique formal runs; cannot hide a failed attempt")
    output: dict[str, Any] = {"cases": {}, "treatments": {}, "isolation": [], "monetary_cost": "unavailable"}
    review = []
    for treatment in TREATMENTS:
        selected = [r for r in rows if r["treatment"] == treatment]
        requests = [p for r in selected for p in r["provider_requests"]]
        planner_requests = [p for p in requests if not p["serialized_request"].get("stream", False)]
        runtime_requests = [p for p in requests if p["serialized_request"].get("stream", False)]
        # usage_for 沿用既有缺失值语义，Provider 未返回的 reasoning 不补零。
        tools = [
            c
            for r in selected
            if r["query_result"] is not None
            for c in r["query_result"]["runtime_result"]["tool_calls"]
        ]
        planner_ms = [
            r["planner"]["observation"]["latency_ms"]
            for r in selected
            if r["planner"] is not None and r["planner"]["observation"] is not None
        ]
        output["treatments"][treatment] = {
            "runs": len(selected),
            "successful_e2e": sum(r["evaluation_run"]["query_result"]["is_successful"] for r in selected),
            "e2e_mean_ms": mean(r["wall_clock_ms"] for r in selected),
            "e2e_median_ms": median(r["wall_clock_ms"] for r in selected),
            "planner_mean_ms": None if not planner_ms else mean(planner_ms),
            "provider_requests": len(requests),
            "planner_requests": len(planner_requests),
            "runtime_requests": len(runtime_requests),
            "planner_valid": sum(r["planner"] is not None and r["planner"]["plan"] is not None for r in selected),
            "tool_calls": len(tools),
            "tool_errors": dict(Counter(c["error_code"] for c in tools if c["error_code"])),
            "partial_calls": sum(c["status"] == "partial" for c in tools),
            "usage": {
                "planner": usage_for(planner_requests),
                "runtime": usage_for(runtime_requests),
                "total": usage_for(requests),
            },
        }
    for case_id in truths:
        pair = {r["treatment"]: r for r in rows if r["case_id"] == case_id}
        first = {
            t: next(
                p["serialized_request"] for p in r["provider_requests"] if p["serialized_request"].get("stream", False)
            )
            for t, r in pair.items()
        }
        verify_initial_requests(first["standard"], first["planned"], pair["planned"]["rendered_guidance"])
        # 比较实际首次 Runtime HTTP，唯一允许的差异是生产 renderer 的软指导。
        output["isolation"].append({"case_id": case_id, "initial_runtime_equal_except_guidance": True})
        output["cases"][case_id] = {}
        for treatment, row in pair.items():
            events = json.loads((directory / "traces" / f"{case_id}-{treatment}.json").read_text())
            starts = {e["operation_id"]: e for e in events if e["operation"] == "tool.call.started"}
            result = row["query_result"]["runtime_result"]
            artifact = row["answer_artifact"]
            raw_calls = provider_calls(row["provider_requests"])
            # 原始 function 序列与 normalized Tool 序列对齐，但不覆盖原始字段。
            if [c["name"] for c in raw_calls] != [c["name"] for c in result["tool_calls"]]:
                raise ValueError(f"Provider/normalized sequence mismatch for {case_id}/{treatment}")
            returned = {tr["tool_call_id"]: tr for tr in result["tool_results"]}
            retrieved = {
                i["message"]["internal_message_id"]: i["message"]
                for tr in result["tool_results"]
                for i in tr["message_items"]
            }
            selected_ids = {
                s["reference"]["internal_message_id"]
                for e in artifact["evidence_items"]
                for s in e["sources"]
                if "internal_message_id" in s["reference"]
            }
            tools = []
            seen = set()
            for call, raw in zip(result["tool_calls"], raw_calls, strict=True):
                identity = call["tool_call_id"]
                tr = returned.get(identity)
                ids = set() if tr is None else {i["message"]["internal_message_id"] for i in tr["message_items"]}
                tools.append(
                    {
                        "name": call["name"],
                        "provider_arguments": raw["arguments"],
                        "normalized_arguments": None
                        if identity not in starts
                        else starts[identity]["payload"]["request"],
                        "status": call["status"],
                        "error": call["error_code"],
                        "returned_messages": len(ids),
                        "new_message_ids": sorted(ids - seen),
                        "final_evidence_ids": sorted(ids & selected_ids),
                        "query_scope": None if tr is None else tr["query_scope_snapshot"],
                        "limitations": [] if tr is None else tr["limitations"],
                    }
                )
                seen |= ids
            evidence = {e["evidence_id"]: e for e in artifact["evidence_items"]}
            bindings = {c["content_block_id"]: c["evidence_ids"] for c in artifact["citation_bindings"]}
            claims = []
            for block in artifact["content_blocks"]:
                supporting = [evidence[e] for e in bindings.get(block["block_id"], [])]
                # 按 Claim 的真实 Citation binding 展开来源，不能把所有取回消息当作已引用。
                facts = []
                for item in supporting:
                    for source in item["sources"]:
                        ref = source["reference"]
                        if "internal_message_id" in ref:
                            snap = ref["snapshot"]
                            # 时间与发送者分别保留；finding 的关系描述不能替代 canonical 事实。
                            facts.append(
                                {
                                    "canonical_id": ref["internal_message_id"],
                                    "author_display": snap["author_display"],
                                    "session_display": snap["session_display"],
                                    "source": canonical_message_excerpt(
                                        timestamp_ms=snap["timestamp_ms"], content=snap["excerpt"]
                                    ),
                                }
                            )
                        else:
                            facts.append({"structured_reference": ref})
                claims.append({**block, "evidence": supporting, "canonical_source_facts": facts})
            truth = truths[case_id]
            targets = set(truth["relevant_message_ids"]) | set(truth["required_context_message_ids"])
            case_result = {
                "run_id": row["run_id"],
                "trace_id": row["trace_id"],
                "status": row["evaluation_run"]["terminal_status"],
                "wall_clock_ms": row["wall_clock_ms"],
                "planner_ms": None if row["planner"] is None else row["planner"]["observation"]["latency_ms"],
                "provider_requests": len(row["provider_requests"]),
                "tools": tools,
                "retrieved_messages": retrieved,
                "selected_message_ids": sorted(selected_ids),
                "missing_gt_retrieval": sorted(targets - set(retrieved)),
                "missing_gt_evidence": sorted(targets - selected_ids),
                "model_turns": sum(e["operation"] == "model.turn" and e["phase"] == "completed" for e in events),
                "claims": claims,
                "final_answer": row["final_answer"],
                "automatic_evaluation": row["automatic_evaluation"],
                "usage": row["usage"],
            }
            output["cases"][case_id][treatment] = case_result
            review.append(
                {
                    "case_id": case_id,
                    "treatment": treatment,
                    "query": next(c["case"]["query"] for c in preflight["cases"] if c["case"]["case_id"] == case_id),
                    "claims": claims,
                    "final_answer": row["final_answer"],
                    "limits": "root source audit, unblinded; not human adjudication or independent blind review",
                }
            )
    write_json(directory / "analysis.json", output)
    write_json(
        directory / "semantic-review-packet.json",
        {
            "temporal_regression": json.loads(
                (ROOT / "evaluation/regressions/archify-temporal-relation.json").read_text()
            ),
            "runs": review,
        },
    )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = analyze(args.directory)
    print(json.dumps(result["treatments"], ensure_ascii=False, indent=2))
