"""由四次冻结 Plan 的原始运行记录派生工具、引用与 usage 事实，不自动判断语义。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evaluation/planner-p1-stability"))
from run_frozen_plan_replay import CASE_ID, without_guidance  # noqa: E402
from run_p1_e2e import usage_for, write_json  # noqa: E402


def analyze(directory: Path) -> dict:
    """语义判断单列人工 audit；这里仅复核实际输入与构造完整事实索引。"""
    rows = [json.loads(line) for line in (directory / "runs.jsonl").read_text().splitlines()]
    if len(rows) != 4 or {(r["treatment"], r["attempt"]) for r in rows} != {(t, n) for t in ("low", "none") for n in (1, 2)}:
        raise ValueError("all four unique runs are required")
    plans = json.loads((directory / "plans.json").read_text())
    inputs = [r["provider_requests"][0]["serialized_request"] for r in rows]
    common = [without_guidance(body, plans[row["treatment"]]["guidance"]) for row, body in zip(rows, inputs, strict=True)]
    if any(body != common[0] for body in common):
        raise ValueError("actual initial request contamination")
    output = {"runs": [], "treatments": {}, "same_initial_body_within_guidance": {}, "input_isolation": True}
    for treatment in ("low", "none"):
        selected = [r for r in rows if r["treatment"] == treatment]
        bodies = [r["provider_requests"][0]["serialized_request"] for r in selected]
        output["same_initial_body_within_guidance"][treatment] = bodies[0] == bodies[1]
        requests = [request for row in selected for request in row["provider_requests"]]
        output["treatments"][treatment] = {"runs": 2, "completed": sum(r["evaluation_run"]["query_result"]["is_successful"] for r in selected),
            "mean_ms": mean(r["wall_clock_ms"] for r in selected), "provider_requests": len(requests), "usage": usage_for(requests)}
    for row in rows:
        trace = json.loads((directory / "traces" / f"{CASE_ID}-{row['treatment']}-r{row['attempt']}.json").read_text())
        starts = {e["operation_id"]: e for e in trace if e["operation"] == "tool.call.started"}
        ends = {e["operation_id"]: e for e in trace if e["operation"] in ("tool.call.completed", "tool.call.failed")}
        result = row["query_result"]["runtime_result"]
        artifact = row["answer_artifact"]
        retrieved = {item["message"]["internal_message_id"]: item["message"] for tr in result["tool_results"] for item in tr["message_items"]}
        evidence = {item["evidence_id"]: item for item in artifact["evidence_items"]}
        selected = {s["reference"]["internal_message_id"] for e in evidence.values() for s in e["sources"] if "internal_message_id" in s["reference"]}
        tool_results = {tr["tool_call_id"]: tr for tr in result["tool_results"]}
        provider_calls = []
        for request in row["provider_requests"]:
            # SSE 的 function 名称和 arguments 可跨 chunk；按 SDK index 合并公开调用事实。
            merged = {}
            for chunk in request["response"]["chunks"]:
                for choice in chunk.get("choices", []):
                    for call in choice.get("delta", {}).get("tool_calls", []):
                        target = merged.setdefault(call["index"], {"name": "", "arguments": ""})
                        for key in target:
                            target[key] += call.get("function", {}).get(key, "") or ""
            provider_calls.extend(merged.values())
        if [c["name"] for c in provider_calls] != [c["name"] for c in result["tool_calls"]]:
            raise ValueError("Provider and normalized tool sequence differ")
        tools = []
        seen = set()
        for call, provider_call in zip(result["tool_calls"], provider_calls, strict=True):
            identity = call["tool_call_id"]
            tr = tool_results.get(identity)
            ids = set() if tr is None else {item["message"]["internal_message_id"] for item in tr["message_items"]}
            tools.append({"name": call["name"], "arguments": starts[identity]["payload"]["request"], "status": call["status"],
                "provider_arguments": json.loads(provider_call["arguments"]),
                "error": call["error_code"], "duration_ms": ends[identity]["duration_ms"], "message_ids": sorted(ids),
                "new_message_ids": sorted(ids - seen), "final_evidence_intersection": sorted(ids & selected),
                "query_scope": None if tr is None else tr["query_scope_snapshot"],
                "limitations": [] if tr is None else tr["limitations"], "model_projection_truncated": call["model_result_truncated"]})
            seen |= ids
        # 每个 Claim 连接到明确的 Evidence 和 canonical Message，便于人工逐条核验。
        bindings = {c["content_block_id"]: c["evidence_ids"] for c in artifact["citation_bindings"]}
        claims = [{**block, "evidence_ids": bindings[block["block_id"]],
                   "source_ids": sorted({s["reference"]["internal_message_id"] for e in bindings[block["block_id"]]
                       for s in evidence[e]["sources"] if "internal_message_id" in s["reference"]})}
                  for block in artifact["content_blocks"]]
        output["runs"].append({"treatment": row["treatment"], "attempt": row["attempt"], "run_id": row["run_id"],
            "trace_id": row["trace_id"], "wall_clock_ms": row["wall_clock_ms"], "provider_requests": len(row["provider_requests"]),
            "tools": tools, "retrieved_messages": retrieved, "selected_message_ids": sorted(selected), "claims": claims,
            "final_answer": row["final_answer"], "automatic_evaluation": row["automatic_evaluation"], "usage": row["usage"],
            "tool_latency_sum_ms": sum(t["duration_ms"] for t in tools),
            "answer_generation_ms": row["provider_requests"][-1]["response"]["latency_ms"],
            "model_turn_count": sum(e["operation"] == "model.turn" and e["phase"] == "completed" for e in trace)})
    write_json(directory / "analysis.json", output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = analyze(args.directory)
    print(json.dumps({"same_initial_body": result["same_initial_body_within_guidance"],
                      "treatments": result["treatments"]}, ensure_ascii=False, indent=2))
