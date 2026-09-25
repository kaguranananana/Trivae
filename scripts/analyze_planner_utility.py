"""分析单次 Development forced-path 配对实验；正文审阅包只写本地 ignored 目录。"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

QUALITY_METRICS = (
    "valid_answer",
    "evidence_recall",
    "context_recovery",
    "coverage_status_accuracy",
    "truncation_accuracy",
    "expected_fact_answer_coverage",
    "false_zero_result",
    "verified_zero_result",
)
TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "cost")


def _quantile(values: list[float], fraction: float) -> float | None:
    """小样本使用 nearest-rank，与既有 Router 实验口径一致。"""

    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _stats(values: list[float]) -> dict[str, float | int | None]:
    """同时给出分母和分布，避免仅凭均值判断延迟。"""

    return {
        "n": len(values),
        "mean": None if not values else mean(values),
        "p50": _quantile(values, 0.5),
        "p95": _quantile(values, 0.95),
    }


def _numeric_delta(standard: object, planned: object) -> float | None:
    """仅在两路都有实测数值时计算差值，缺失不假设为零。"""

    if isinstance(standard, (int, float)) and isinstance(planned, (int, float)):
        return float(planned - standard)
    return None


def _metrics(row: dict[str, Any]) -> dict[str, float]:
    """只读取 Harness 明确标为 available 的已有质量指标。"""

    return {
        item["name"]: float(item["value"])
        for item in row["metrics"]
        if item["name"] in QUALITY_METRICS and item["availability"] == "available" and item["value"] is not None
    }


def _provider_failure(payload: dict[str, Any]) -> bool:
    """Provider/transport 故障单独归因，不宣称 Planner 改善或损害了答案质量。"""

    if payload.get("exception_type") is not None:
        return True
    runtime = (payload.get("query_result") or {}).get("runtime") or {}
    error = runtime.get("error") or {}
    return error.get("diagnostic_type") in {
        "APIConnectionError", "APITimeoutError", "RemoteProtocolError", "RateLimitError", "AuthenticationError"
    }


def _paired_quality(
    standard: dict[str, Any], planned: dict[str, Any],
    standard_payload: dict[str, Any], planned_payload: dict[str, Any],
) -> tuple[str, dict[str, str]]:
    """对可比较 GT 指标做 Pareto 判定；冲突和 Provider 故障保留独立状态。"""

    if _provider_failure(standard_payload) or _provider_failure(planned_payload):
        return "provider_confounded", {}
    a, b = _metrics(standard), _metrics(planned)
    deltas = {
        name: "better" if b[name] > a[name] else "worse" if b[name] < a[name] else "same"
        for name in a.keys() & b.keys()
    }
    # 没有可比较的质量维度就不能凭答案措辞或 Tool 变化判定优劣。
    if not deltas:
        return "unavailable", deltas
    directions = set(deltas.values()) - {"same"}
    if len(directions) > 1:
        return "mixed", deltas
    return next(iter(directions), "same"), deltas


def _usage(rows: list[dict[str, Any]], part: str) -> dict[str, object]:
    """只累计 Provider 实际返回的字段，并公开每个字段的可用 run 数。"""

    usage_values = []
    for row in rows:
        operational = row["operational_measurements"]
        value = operational.get("usage") if part == "runtime" else operational["planner"].get("usage")
        usage_values.append(value if isinstance(value, dict) else {})
    result: dict[str, object] = {}
    for field in TOKEN_FIELDS:
        numbers = [float(value[field]) for value in usage_values if isinstance(value.get(field), (int, float))]
        result[field] = {"n": len(numbers), "sum": sum(numbers) if numbers else None}
    return result


def _metric_summary(rows: list[dict[str, Any]], name: str) -> dict[str, object]:
    """保留可用 Case 数、加权分子/分母和 Case macro，不混入 unavailable。"""

    available = [
        item for row in rows for item in row["metrics"]
        if item["name"] == name and item["availability"] == "available" and item["value"] is not None
    ]
    hits = sum(float(item["hits"]) for item in available if item["hits"] is not None)
    denominator = sum(int(item["denominator"]) for item in available)
    return {
        "available": len(available), "hits": hits, "denominator": denominator,
        "weighted": hits / denominator if denominator else None,
        "case_macro": mean(float(item["value"]) for item in available) if available else None,
    }


def analyze(records_path: Path, evaluation_db: Path, canonical_db: Path, cases_dir: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    """交叉核验三层身份，生成不含正文的摘要与仅本地使用的审阅包。"""

    if output_dir.exists():
        raise ValueError(f"analysis output already exists: {output_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    execution_commit = manifest["git_commit"]
    rows = json.loads(records_path.read_text(encoding="utf-8"))
    if len(rows) != 74:
        raise ValueError(f"expected 74 main records, got {len(rows)}")
    # 同一个 run_id 必须恰好对应一个 raw、Evaluation result 和 canonical Trace。
    raw_ids = {row["run_id"] for row in rows}
    if len(raw_ids) != 74:
        raise ValueError("duplicate raw run_id")
    with sqlite3.connect(evaluation_db) as db:
        payloads = {run_id: json.loads(payload) for run_id, payload in db.execute("SELECT run_id,payload_json FROM evaluation_runs")}
        result_ids = {run_id for (run_id,) in db.execute("SELECT run_id FROM evaluation_results")}
    trace_ids = {row["trace_id"] for row in rows}
    with sqlite3.connect(canonical_db) as db:
        stored_traces = {trace_id for (trace_id,) in db.execute(
            f"SELECT trace_id FROM traces WHERE trace_id IN ({','.join('?' for _ in trace_ids)})", tuple(trace_ids)
        )}
    if raw_ids != set(payloads) or raw_ids != result_ids or trace_ids != stored_traces or len(trace_ids) != 74:
        raise ValueError("raw, Evaluation and Trace identities do not align")

    groups: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    route_violations: list[str] = []
    invocation_violations: list[str] = []
    identity_violations: list[str] = []
    for row in rows:
        arm = "standard" if "-standard-" in row["variant_id"] else "planned"
        case_id = row["case_id"]
        if arm in groups[case_id]:
            raise ValueError(f"duplicate case/arm: {case_id}/{arm}")
        groups[case_id][arm] = row
        payload = payloads[row["run_id"]]
        query = payload.get("query_result") or {}
        expected_route = f"{arm}_execution"
        if query.get("route") != expected_route or query.get("route_source") != "evaluation_override":
            route_violations.append(row["run_id"])
        planner_called = row["operational_measurements"]["planner"].get("called")
        if planner_called is not (arm == "planned"):
            invocation_violations.append(row["run_id"])
        operational = row["operational_measurements"]
        if operational.get("provider") != "deepseek" or operational.get("model") != "deepseek-flash":
            identity_violations.append(row["run_id"])
        if payload.get("execution_override", {}).get("forced_route") != expected_route:
            identity_violations.append(row["run_id"])
        if payload.get("snapshot_id") != manifest["canonical_snapshot_id"]:
            identity_violations.append(row["run_id"])
        if arm == "planned":
            planner = operational["planner"]
            if planner.get("provider") != "deepseek" or planner.get("model") != "deepseek-flash":
                identity_violations.append(row["run_id"])
    if len(groups) != 37 or any(set(group) != {"standard", "planned"} for group in groups.values()):
        raise ValueError("37 complete case pairs are required")

    by_arm = {arm: [group[arm] for group in groups.values()] for arm in ("standard", "planned")}
    pair_counts: Counter[str] = Counter()
    per_metric: dict[str, Counter[str]] = defaultdict(Counter)
    category_pairs: dict[str, Counter[str]] = defaultdict(Counter)
    pair_records: list[dict[str, Any]] = []
    review_packet: list[dict[str, Any]] = []
    for case_id, group in sorted(groups.items()):
        standard, planned = group["standard"], group["planned"]
        a, b = payloads[standard["run_id"]], payloads[planned["run_id"]]
        classification, metric_deltas = _paired_quality(standard, planned, a, b)
        pair_counts[classification] += 1
        category_pairs[standard["category"]][classification] += 1
        for name, direction in metric_deltas.items():
            per_metric[name][direction] += 1
        am, bm = standard["operational_measurements"], planned["operational_measurements"]
        at, bt = am["agent_tool_behavior"], bm["agent_tool_behavior"]
        pair = {
            "case_id": case_id, "category": standard["category"], "classification": classification,
            "metric_deltas": metric_deltas,
            "standard_status": standard["run_status"], "planned_status": planned["run_status"],
            "latency_delta_ms": None if am["latency_ms"] is None or bm["latency_ms"] is None else bm["latency_ms"] - am["latency_ms"],
            "first_tool_changed": at["first_selected_tool"] != bt["first_selected_tool"],
            "tool_sequence_changed": at["tool_sequence"] != bt["tool_sequence"],
            "tool_round_delta": _numeric_delta(at["tool_rounds"], bt["tool_rounds"]),
            "context_tool_call_delta": bt["context_tool_sequence"].count("get_message_context") - at["context_tool_sequence"].count("get_message_context"),
            "retrieval_count_delta": _numeric_delta(am["retrieval_count"], bm["retrieval_count"]),
            "evidence_count_delta": _numeric_delta(am["evidence_count"], bm["evidence_count"]),
            "answer_text_changed": (a.get("query_result") or {}).get("answer_text") != (b.get("query_result") or {}).get("answer_text"),
            "planner_status": bm["planner"]["status"],
        }
        pair_records.append(pair)
        # 审阅包保留 GT/答案/证据正文，仅写 data/evaluation 下的 ignored 本地目录。
        if classification != "same" or pair["tool_sequence_changed"]:
            case = json.loads((cases_dir / f"{case_id}.json").read_text(encoding="utf-8"))
            review_packet.append({
                "case_id": case_id, "category": standard["category"], "paired": pair,
                "query": case["query"], "reference_findings": case["reference_findings"],
                "standard": {"answer": (a.get("query_result") or {}).get("answer_text"),
                             "evidence": (a.get("query_result") or {}).get("evidence_sources"),
                             "citations": (a.get("query_result") or {}).get("citation_bindings"),
                             "tools": at["tool_sequence"], "metrics": _metrics(standard)},
                "planned": {"answer": (b.get("query_result") or {}).get("answer_text"),
                            "evidence": (b.get("query_result") or {}).get("evidence_sources"),
                            "citations": (b.get("query_result") or {}).get("citation_bindings"),
                            "tools": bt["tool_sequence"], "planner": bm["planner"],
                            "metrics": _metrics(planned)},
            })

    summary: dict[str, Any] = {
        "identity": {"runs": 74, "cases": 37, "execution_commit": execution_commit,
                     "snapshot": manifest["canonical_snapshot_id"],
                     "variants": sorted({row["variant_id"] for row in rows})},
        "integrity": {"raw": len(rows), "evaluation_runs": len(payloads), "evaluation_results": len(result_ids),
                      "traces": len(stored_traces), "route_violations": route_violations,
                      "planner_invocation_violations": invocation_violations, "identity_violations": identity_violations},
        "arms": {}, "paired_quality": dict(pair_counts),
        "paired_by_category": {category: dict(counts) for category, counts in category_pairs.items()},
        "paired_by_metric": {name: dict(counts) for name, counts in per_metric.items()},
        "paired_cases": pair_records,
        "behavior": {"first_tool_changed": sum(pair["first_tool_changed"] for pair in pair_records),
                     "tool_sequence_changed": sum(pair["tool_sequence_changed"] for pair in pair_records),
                     "answer_text_changed": sum(pair["answer_text_changed"] for pair in pair_records),
                     "context_tool_call_changed": sum(pair["context_tool_call_delta"] != 0 for pair in pair_records),
                     "evidence_count_changed": sum(pair["evidence_count_delta"] is not None and pair["evidence_count_delta"] != 0 for pair in pair_records),
                     "round_delta": dict(Counter(pair["tool_round_delta"] for pair in pair_records))},
        "latency": {"paired_delta_all": _stats([float(pair["latency_delta_ms"]) for pair in pair_records if pair["latency_delta_ms"] is not None]),
                    "paired_delta_both_completed": _stats([float(pair["latency_delta_ms"]) for pair in pair_records if pair["latency_delta_ms"] is not None and pair["standard_status"] == pair["planned_status"] == "completed"])},
        "review_packet_cases": [item["case_id"] for item in review_packet],
    }
    for arm, arm_rows in by_arm.items():
        latencies = [float(row["operational_measurements"]["latency_ms"]) for row in arm_rows if row["operational_measurements"]["latency_ms"] is not None]
        completed = [row for row in arm_rows if row["run_status"] == "completed"]
        summary["arms"][arm] = {
            "statuses": dict(Counter(row["run_status"] for row in arm_rows)),
            "planner_statuses": dict(Counter(row["operational_measurements"]["planner"]["status"] for row in arm_rows)),
            "planner_failure_categories": dict(Counter(row["operational_measurements"]["planner"].get("failure_category") for row in arm_rows if row["operational_measurements"]["planner"].get("failure_category"))),
            "runtime_errors": [
                {"case_id": row["case_id"], "error": (payloads[row["run_id"]].get("query_result") or {}).get("runtime", {}).get("error")}
                for row in arm_rows if (payloads[row["run_id"]].get("query_result") or {}).get("runtime", {}).get("error")
            ],
            "citation_states": dict(Counter(row["operational_measurements"]["citation_state"] for row in arm_rows)),
            "finalization_states": dict(Counter(row["operational_measurements"]["finalization_state"] for row in arm_rows)),
            "latency_all": _stats(latencies),
            "latency_completed": _stats([float(row["operational_measurements"]["latency_ms"]) for row in completed if row["operational_measurements"]["latency_ms"] is not None]),
            "tool_calls": _stats([float(row["operational_measurements"]["tool_calls"]) for row in arm_rows if isinstance(row["operational_measurements"]["tool_calls"], int)]),
            "tool_rounds": _stats([float(row["operational_measurements"]["tool_rounds"]) for row in arm_rows if isinstance(row["operational_measurements"]["tool_rounds"], int)]),
            "retrieval_count": _stats([float(row["operational_measurements"]["retrieval_count"]) for row in arm_rows if isinstance(row["operational_measurements"]["retrieval_count"], int)]),
            "planner_latency": _stats([float(row["operational_measurements"]["planner"]["latency_ms"]) for row in arm_rows if isinstance(row["operational_measurements"]["planner"].get("latency_ms"), (int, float))]),
            "planner_steps": _stats([float(row["operational_measurements"]["planner"]["step_count"]) for row in arm_rows if isinstance(row["operational_measurements"]["planner"].get("step_count"), int)]),
            "suggested_tools": dict(Counter(tool for row in arm_rows for tool in row["operational_measurements"]["planner"].get("suggested_tools", []))),
            "runtime_usage": _usage(arm_rows, "runtime"), "planner_usage": _usage(arm_rows, "planner"),
            "quality_metrics": {name: _metric_summary(arm_rows, name) for name in QUALITY_METRICS},
        }
    output_dir.mkdir(parents=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "review-packet.json").write_text(json.dumps(review_packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Trace 正文仍在原 Trace Store；索引只保留可审计的 run/case/arm 关联和完整度。
    trace_index = [
        {"run_id": row["run_id"], "case_id": row["case_id"], "variant_id": row["variant_id"],
         "trace_id": row["trace_id"], "execution_commit": execution_commit,
         "completeness": row["operational_measurements"]["trace_completeness"]}
        for row in rows
    ]
    (output_dir / "trace-index.json").write_text(json.dumps(trace_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Ledger 逐 run 固定身份与 bounded 操作字段，便于审核时无需合并整份 Trace 正文。
    ledger = [
        {"case_id": row["case_id"], "run_id": row["run_id"], "variant_id": row["variant_id"],
         "execution_commit": execution_commit, "trace_id": row["trace_id"], "status": row["run_status"],
         "route": (payloads[row["run_id"]].get("query_result") or {}).get("route"),
         "planner": row["operational_measurements"]["planner"],
         "latency_ms": row["operational_measurements"]["latency_ms"],
         "runtime_provider": row["operational_measurements"]["provider"],
         "runtime_model": row["operational_measurements"]["model"],
         "runtime_usage": row["operational_measurements"]["usage"],
         "tool_behavior": row["operational_measurements"]["agent_tool_behavior"],
         "retrieval_count": row["operational_measurements"]["retrieval_count"],
         "evidence_count": row["operational_measurements"]["evidence_count"],
         "citation_state": row["operational_measurements"]["citation_state"],
         "metrics": row["metrics"]}
        for row in rows
    ]
    (output_dir / "run-ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--evaluation-db", type=Path, required=True)
    parser.add_argument("--canonical-db", type=Path, required=True)
    parser.add_argument("--cases-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.records, args.evaluation_db, args.canonical_db, args.cases_dir, args.manifest, args.output_dir)
    print(json.dumps({"integrity": result["integrity"], "paired_quality": result["paired_quality"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
