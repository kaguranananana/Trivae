"""从冻结 raw artifacts 派生分层指标和逐 tool Evidence 贡献候选，不重跑 Provider。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import mean, median

# 复用原 runner 的 usage/JSON 落盘逻辑，不建立第二套 token accounting。
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evaluation/planner-p1-stability"))
from run_p1_e2e import usage_for, write_json  # noqa: E402

RETRIEVAL = {"lexical_search", "semantic_search", "get_recent_messages", "get_message_context", "execute_sql"}


def analyze(directory: Path) -> dict:
    """自动部分只表达可验证事实；具体 tool 必要性和事实 entailment 不自动猜测。"""
    rows = [json.loads(s) for s in (directory / "runs.jsonl").read_text().splitlines()]
    if len(rows) != 16 or len({(r["case_id"], r["treatment"], r["attempt"]) for r in rows}) != 16:
        raise ValueError("expected all 16 unique attempts")
    output = {"treatments": {}, "cases": {}, "isolation": [], "failures": []}
    for effort in ("low", "none"):
        selected = [r for r in rows if r["treatment"] == effort]
        requests = [p for r in selected for p in r["provider_requests"]]
        failures = [r for r in selected if r["planner"]["failure"] is not None]
        calls = [c for r in selected for c in r["query_result"]["runtime_result"]["tool_calls"]]
        output["treatments"][effort] = {
            "runs": len(selected), "successful_e2e": sum(r["evaluation_run"]["query_result"]["is_successful"] for r in selected),
            "failed_e2e": sum(not r["evaluation_run"]["query_result"]["is_successful"] for r in selected),
            "planner_valid": len(selected) - len(failures),
            "planner_failures": dict(Counter(r["planner"]["failure"]["detail_code"] or r["planner"]["failure"]["code"] for r in failures)),
            "tool_calls": len(calls), "retrieval_calls": sum(c["name"] in RETRIEVAL for c in calls),
            "tool_failed_calls": sum(c["status"] == "error" for c in calls),
            "runs_with_tool_errors": sum(any(c["status"] == "error" for c in r["query_result"]["runtime_result"]["tool_calls"]) for r in selected),
            "tool_partial_calls": sum(c["status"] == "partial" for c in calls),
            "model_projection_truncated_calls": sum(c["model_result_truncated"] for c in calls),
            "provider_requests": len(requests), "retry_count": 0, "timeout_count": 0,
            "e2e_mean_ms": mean(r["wall_clock_ms"] for r in selected),
            "e2e_median_ms": median(r["wall_clock_ms"] for r in selected),
            "planner_mean_ms": mean(r["planner"]["observation"]["latency_ms"] for r in selected),
            "planner_median_ms": median(r["planner"]["observation"]["latency_ms"] for r in selected),
            "usage": {"planner": usage_for([r["provider_requests"][0] for r in selected]),
                      "downstream": usage_for([p for r in selected for p in r["provider_requests"][1:]]),
                      "total": usage_for(requests)},
        }
    for case_id in dict.fromkeys(r["case_id"] for r in rows):
        pair = {r["treatment"]: r for r in rows if r["case_id"] == case_id}
        # 真实首个请求必须与 SDK preflight 一样，所有字段只有 effort 差异。
        serialized = {e: r["provider_requests"][0]["serialized_request"] for e, r in pair.items()}
        differences = sorted(k for k in set(serialized["low"]) | set(serialized["none"]) if serialized["low"].get(k) != serialized["none"].get(k))
        if differences != ["reasoning_effort"]:
            raise ValueError(f"actual Planner contamination: {case_id} {differences}")
        # 下游的 plan guidance、Tool history 是中介变量；请求参数与 schema 必须共同固定。
        runtime_configs = {e: {k: v for k, v in r["provider_requests"][1]["serialized_request"].items() if k != "messages"} for e, r in pair.items()}
        if runtime_configs["low"] != runtime_configs["none"]:
            raise ValueError(f"downstream request config contamination: {case_id}")
        output["isolation"].append({"case_id": case_id, "actual_planner_diff": differences, "first_runtime_config_equal": True,
                                    "planner_input_usage_delta": pair["low"]["provider_requests"][0]["response"]["chunks"][0]["usage"]["prompt_tokens"] - pair["none"]["provider_requests"][0]["response"]["chunks"][0]["usage"]["prompt_tokens"]})
        output["cases"][case_id] = {}
        for effort, row in pair.items():
            events = json.loads((directory / "traces" / f"{case_id}-{effort}-a{row['attempt']}.json").read_text())
            starts = {e["operation_id"]: e for e in events if e["operation"] == "tool.call.started"}
            ends = {e["operation_id"]: e for e in events if e["operation"] in {"tool.call.completed", "tool.call.failed"}}
            result = row["query_result"]["runtime_result"]
            artifact = row["answer_artifact"]
            evidence_ids = {s["reference"]["internal_message_id"] for item in artifact["evidence_items"] for s in item["sources"] if "internal_message_id" in s["reference"]}
            gt = next(c["case"] for c in json.loads((directory / "preflight.json").read_text())["cases"] if c["case_id"] == case_id)
            target_ids = {ref["locator"]["internal_message_id"] for f in gt["reference_findings"] for ref in f["reference_evidence"] if "internal_message_id" in ref["locator"]}
            seen, args_seen, tool_records = set(), set(), []
            returned = {t["tool_call_id"]: t for t in result["tool_results"]}
            for call in result["tool_calls"]:
                call_id = call["tool_call_id"]
                tool_result = returned.get(call_id)
                messages = [] if tool_result is None else tool_result["message_items"]
                ids = {m["message"]["internal_message_id"] for m in messages}
                args = starts[call_id]["payload"]["request"]
                arg_key = (call["name"], json.dumps(args, sort_keys=True))
                new_ids = ids - seen
                # 两个候选条件都只作为人工核验线索，不自动标记 redundant/harmful。
                tool_records.append({"name": call["name"], "arguments": args, "status": call["status"], "error": call["error_code"],
                    "duration_ms": ends[call_id]["duration_ms"], "message_ids": sorted(ids), "new_message_ids": sorted(new_ids),
                    "final_evidence_intersection": sorted(ids & evidence_ids), "exact_duplicate_arguments_candidate": arg_key in args_seen,
                    "no_new_message_candidate": bool(ids) and not new_ids,
                    "structured_items": [] if tool_result is None else tool_result["structured_items"],
                    "query_scope": None if tool_result is None else tool_result["query_scope_snapshot"],
                    "limitations": [] if tool_result is None else tool_result["limitations"],
                    "model_projection_truncated": call["model_result_truncated"]})
                seen |= ids
                args_seen.add(arg_key)
            output["cases"][case_id][effort] = {
                "run_id": row["run_id"], "trace_id": row["trace_id"], "query": gt["query"], "planner": row["planner"],
                "tools": tool_records, "retrieved_message_ids": sorted(seen), "evidence_message_ids": sorted(evidence_ids),
                "expected_evidence_hits": sorted(target_ids & evidence_ids), "expected_evidence_misses": sorted(target_ids - evidence_ids),
                "evidence_ids": [item["evidence_id"] for item in artifact["evidence_items"]], "citations": artifact["citation_bindings"],
                "coverage": artifact["retrieval_coverage"], "resolved_time_range": artifact["resolved_time_range"],
                "answer": row["final_answer"], "evaluation": row["automatic_evaluation"],
                "planner_latency_ms": row["planner"]["observation"]["latency_ms"],
                "tool_latency_sum_ms": sum(t["duration_ms"] for t in tool_records),
                "answer_generation_ms": row["provider_requests"][-1]["response"]["latency_ms"],
                "e2e_ms": row["wall_clock_ms"], "provider_requests": len(row["provider_requests"]), "usage": row["usage"],
            }
            if row["planner"]["failure"] is not None:
                output["failures"].append({"case_id": case_id, "treatment": effort, "stage": "planner_provider_length", "failure": row["planner"]["failure"], "e2e_completed": True})
            output["failures"].extend({"case_id": case_id, "treatment": effort, "stage": "tool_execution_failure", "tool": t["name"], "arguments": t["arguments"], "error": t["error"]} for t in tool_records if t["error"])
    write_json(directory / "analysis.json", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = analyze(args.directory)
    print(json.dumps(result["treatments"], ensure_ascii=False, indent=2))
