"""把 forced-path treatment 观测与 Jev route 决策按 Case 配对分析。"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationSuite
from trivae.query.contracts import QueryContext
from trivae.query.router import RouterDecisionProvider, RuleRouter


class RouterUtilityError(ValueError):
    """Route、Treatment 或人工裁决的身份不一致。"""


def _router_context(case: EvaluationCaseBundle, repetition: int) -> QueryContext:
    """与 EvaluationRunner 的生产 QueryRequest 使用同一 Router 可见投影。"""

    snapshot = case.dataset_snapshot
    return QueryContext(
        query=case.query,
        locale=case.locale,
        prior_context=(),
        data_snapshot={
            "snapshot_id": snapshot.snapshot_id,
            "schema_version": snapshot.schema_version,
            "message_count": snapshot.message_count,
            "relevant_time_range": list(snapshot.relevant_time_range),
            "evaluation_case": case.identity,
            "repetition": repetition,
        },
        available_capabilities=(
            "lexical_search", "semantic_search", "get_recent_messages",
            "get_message_context", "find_members", "get_schema", "execute_sql",
        ),
    )


async def run_jev_route_observations(
    suite: EvaluationSuite,
    cases: Mapping[str, EvaluationCaseBundle],
    provider: RouterDecisionProvider,
    *,
    repetitions: int = 1,
) -> dict[str, object]:
    """只执行 Rule gate 与 Jev Decisions；forced treatment 由原 Benchmark Runner 负责。"""

    if repetitions <= 0:
        raise RouterUtilityError("repetitions must be positive")
    rule_router = RuleRouter()
    jev_router = RuleRouter(decision_provider=provider, jev_enabled=True, provider_mode="jev")
    entries: list[dict[str, object]] = []
    # 在第一次计费请求之前校验完整 Suite，防止运行到中途才发现 Case 或 Snapshot 错误。
    selected_cases: list[EvaluationCaseBundle] = []
    for reference in suite.case_references:
        case = cases.get(reference.case_id)
        if case is None or case.identity != reference.identity:
            raise RouterUtilityError(f"suite Case identity mismatch: {reference.identity}")
        selected_cases.append(case)
    snapshot_ids = {case.dataset_snapshot.snapshot_id for case in selected_cases}
    if len(snapshot_ids) != 1:
        raise RouterUtilityError("Router Utility suite must bind one Snapshot")
    for case in selected_cases:
        for repetition in range(repetitions):
            context = _router_context(case, repetition)
            static = await rule_router.route(context)
            decision = await jev_router.route(context)
            entries.append({
                "case_id": case.case_id,
                "case_version": case.version,
                "repetition": repetition + 1,
                "static_route": static.route,
                "rule_gate": static.confidence >= 0.8,
                "predicted_route": decision.route,
                "source": decision.source,
                "degraded": decision.degraded,
                "degradation_code": decision.degradation_code,
                "provider": decision.provider,
                "model": decision.model,
                "latency_ms": decision.primary_latency_ms,
                "usage": None if decision.usage is None else dict(decision.usage),
            })
    return {
        "schema_version": 1,
        "suite_identity": suite.identity,
        "snapshot_id": next(iter(snapshot_ids)),
        "repetitions": repetitions,
        "cases": entries,
    }


def load_treatment_pairs(
    raw_path: Path,
    evaluation_database: Path,
    canonical_database: Path,
    *,
    standard_variant_id: str,
    planned_variant_id: str,
) -> list[dict[str, object]]:
    """将既有 raw 与 Evaluation DB 严格按 run_id 关联，保留原始质量轴。"""

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise RouterUtilityError("treatment raw records must be an array")
    connection = sqlite3.connect(f"file:{evaluation_database.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT run_id, case_id, variant_id, snapshot_id, started_at, trace_id FROM evaluation_runs"
        ).fetchall()
        result_ids = {str(row[0]) for row in connection.execute("SELECT run_id FROM evaluation_results")}
    finally:
        connection.close()
    run_index = {str(row[0]): row for row in rows}
    trace_ids: set[str] = set()
    grouped: dict[str, dict[str, list[tuple[str, Mapping[str, object], str]]]] = defaultdict(
        lambda: {"standard": [], "planned": []}
    )
    for item in raw:
        if not isinstance(item, Mapping):
            raise RouterUtilityError("raw record must be an object")
        run_id = item.get("run_id")
        case_id = item.get("case_id")
        variant_id = item.get("variant_id")
        trace_id = item.get("trace_id")
        if not isinstance(run_id, str) or not isinstance(case_id, str) or not isinstance(trace_id, str):
            raise RouterUtilityError("raw record requires run_id, case_id and trace_id")
        db_row = run_index.get(run_id)
        if db_row is None or db_row[1] != case_id or db_row[2] != variant_id or db_row[5] != trace_id:
            raise RouterUtilityError(f"Evaluation run identity mismatch: {run_id}")
        if run_id not in result_ids:
            raise RouterUtilityError(f"Evaluation result missing: {run_id}")
        trace_ids.add(trace_id)
        arm = "standard" if variant_id == standard_variant_id else "planned" if variant_id == planned_variant_id else None
        if arm is None:
            raise RouterUtilityError(f"unexpected treatment variant: {variant_id}")
        grouped[case_id][arm].append((str(db_row[4]), item, str(db_row[3])))
    if not trace_ids:
        raise RouterUtilityError("treatment raw contains no runs")
    # raw 与 Evaluation run 已绑定同一 trace_id；还需确认该 Trace 真正存在于 canonical Store。
    connection = sqlite3.connect(f"file:{canonical_database.resolve()}?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in trace_ids)
        stored_trace_ids = {
            str(row[0])
            for row in connection.execute(
                f"SELECT trace_id FROM traces WHERE trace_id IN ({placeholders})", tuple(trace_ids)
            )
        }
    finally:
        connection.close()
    if trace_ids != stored_trace_ids:
        raise RouterUtilityError("canonical Trace identity mismatch")
    pairs: list[dict[str, object]] = []
    for case_id, arms in sorted(grouped.items()):
        standard = sorted(arms["standard"], key=lambda row: row[0])
        planned = sorted(arms["planned"], key=lambda row: row[0])
        if len(standard) != len(planned):
            raise RouterUtilityError(f"incomplete treatment pairs: {case_id}")
        for repetition, (left, right) in enumerate(zip(standard, planned), start=1):
            if left[2] != right[2]:
                raise RouterUtilityError(f"treatment Snapshot mismatch: {case_id}")
            pairs.append({
                "case_id": case_id,
                "repetition": repetition,
                "snapshot_id": left[2],
                "standard": _treatment_projection(left[1]),
                "planned": _treatment_projection(right[1]),
            })
    return pairs


def _treatment_projection(raw: Mapping[str, object]) -> dict[str, object]:
    """只投影可比较指标、终态和已观测使用量，不搬运私有答案。"""

    metrics = raw.get("metrics")
    operational = raw.get("operational_measurements")
    if not isinstance(metrics, list) or not isinstance(operational, Mapping):
        raise RouterUtilityError("treatment record lacks metrics or operational measurements")
    available = {
        str(metric["name"]): metric["value"]
        for metric in metrics
        if isinstance(metric, Mapping) and metric.get("availability") == "available"
        and isinstance(metric.get("name"), str)
        and isinstance(metric.get("value"), (int, float))
    }
    return {
        "run_id": raw["run_id"],
        "variant_id": raw["variant_id"],
        "status": raw["run_status"],
        "metrics": available,
        "latency_ms": operational.get("latency_ms"),
        "usage": operational.get("usage"),
        "planner": operational.get("planner"),
        "citation_state": operational.get("citation_state"),
        "finalization_status": operational.get("finalization_status"),
    }


_UTILITY_LABELS = frozenset({"planned_beneficial", "standard_preferable", "indifferent", "uncertain"})


def analyze_router_utility(
    pairs: Sequence[Mapping[str, object]],
    routes: Mapping[str, object],
    adjudications: Mapping[str, object],
) -> dict[str, object]:
    """保留两种误路由方向及逐质量轴影响；未人工裁决时不伪造对错。"""

    route_rows = routes.get("cases")
    reviews = adjudications.get("cases")
    if not isinstance(route_rows, list) or not isinstance(reviews, list):
        raise RouterUtilityError("route and adjudication inputs require cases arrays")
    route_index = {(r["case_id"], r["repetition"]): r for r in route_rows if isinstance(r, Mapping)}
    review_index = {r["case_id"]: r for r in reviews if isinstance(r, Mapping)}
    observations: list[dict[str, object]] = []
    directions: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for pair in pairs:
        case_id = pair.get("case_id")
        repetition = pair.get("repetition")
        route = route_index.get((case_id, repetition))
        if route is None:
            raise RouterUtilityError(f"missing route observation: {case_id} repetition {repetition}")
        if pair.get("snapshot_id") != routes.get("snapshot_id"):
            raise RouterUtilityError(f"Router and treatment Snapshot mismatch: {case_id}")
        review = review_index.get(case_id)
        if review is None:
            raise RouterUtilityError(f"missing utility adjudication entry: {case_id}")
        label = review.get("label")
        status = review.get("review_status")
        if label not in _UTILITY_LABELS or status not in ("pending", "human_adjudicated"):
            raise RouterUtilityError(f"invalid utility adjudication: {case_id}")
        if status == "pending" and label != "uncertain":
            raise RouterUtilityError(f"pending utility cannot have a decided label: {case_id}")
        standard = pair.get("standard")
        planned = pair.get("planned")
        if not isinstance(standard, Mapping) or not isinstance(planned, Mapping):
            raise RouterUtilityError(f"missing treatment arms: {case_id}")
        standard_metrics = standard.get("metrics")
        planned_metrics = planned.get("metrics")
        if not isinstance(standard_metrics, Mapping) or not isinstance(planned_metrics, Mapping):
            raise RouterUtilityError(f"missing treatment metrics: {case_id}")
        if status == "human_adjudicated":
            # 人工结论必须绑定本次 Snapshot、两路 run 和 variant；旧标签不能跨模型复用。
            if review.get("snapshot_id") != pair.get("snapshot_id"):
                raise RouterUtilityError(f"utility adjudication Snapshot mismatch: {case_id}")
            if standard.get("run_id") not in (review.get("standard_run_ids") or ()):
                raise RouterUtilityError(f"utility adjudication standard run mismatch: {case_id}")
            if planned.get("run_id") not in (review.get("planned_run_ids") or ()):
                raise RouterUtilityError(f"utility adjudication planned run mismatch: {case_id}")
            if review.get("standard_variant_id") != standard.get("variant_id") or review.get("planned_variant_id") != planned.get("variant_id"):
                raise RouterUtilityError(f"utility adjudication variant mismatch: {case_id}")
            if not review.get("reviewer") or not review.get("rationale") or not isinstance(review.get("quality_axes"), Mapping):
                raise RouterUtilityError(f"utility adjudication lacks review evidence: {case_id}")
        # 只有两侧均 available 的同名指标做差；不同质量维度绝不合成总分。
        metric_deltas = {
            name: planned_metrics[name] - value
            for name, value in standard_metrics.items()
            if name in planned_metrics and isinstance(value, (int, float))
            and isinstance(planned_metrics[name], (int, float))
        }
        predicted = route.get("predicted_route")
        if predicted not in ("standard_execution", "planned_execution"):
            raise RouterUtilityError(f"invalid predicted route: {case_id}")
        direction = "unadjudicated"
        if status == "human_adjudicated":
            if label == "planned_beneficial" and predicted == "standard_execution":
                direction = "planned_to_standard"
            elif label == "standard_preferable" and predicted == "planned_execution":
                direction = "standard_to_planned"
            elif label == "indifferent":
                direction = "indifferent"
            elif label == "uncertain":
                direction = "uncertain"
            else:
                direction = "aligned"
        directions[direction] += 1
        source = "rule_gate" if route.get("rule_gate") else "jev_provider"
        sources[source] += 1
        observations.append({
            "case_id": case_id,
            "repetition": repetition,
            "label": label,
            "review_status": status,
            "direction": direction,
            "source": source,
            "decision_source": route.get("source"),
            "predicted_route": predicted,
            "degraded": route.get("degraded"),
            "degradation_code": route.get("degradation_code"),
            "route_latency_ms": route.get("latency_ms"),
            "route_usage": route.get("usage"),
            "standard_run_id": standard.get("run_id"),
            "planned_run_id": planned.get("run_id"),
            "standard_status": standard.get("status"),
            "planned_status": planned.get("status"),
            "metric_deltas_planned_minus_standard": metric_deltas,
            "standard_latency_ms": standard.get("latency_ms"),
            "planned_latency_ms": planned.get("latency_ms"),
            "standard_usage": standard.get("usage"),
            "planned_usage": planned.get("usage"),
            "quality_rationale": review.get("rationale"),
            "quality_axes": review.get("quality_axes"),
        })
    provider_observations = [item for item in observations if item["source"] == "jev_provider"]
    route_costs = [
        usage["cost"]
        for item in provider_observations
        for usage in (item["route_usage"],)
        if isinstance(usage, Mapping) and isinstance(usage.get("cost"), (int, float))
    ]
    return {
        "schema_version": 1,
        "suite_identity": routes.get("suite_identity"),
        "snapshot_id": routes.get("snapshot_id"),
        "observation_count": len(observations),
        "source_counts": dict(sources),
        "direction_counts": dict(directions),
        "provider_attempt_count": len(provider_observations),
        "provider_available_count": sum(item["decision_source"] == "jev" and not item["degraded"] for item in provider_observations),
        "provider_degraded_count": sum(bool(item["degraded"]) for item in provider_observations),
        "actual_returned_jev_cost": sum(route_costs) if route_costs else None,
        "actual_returned_jev_cost_observations": len(route_costs),
        "cost_policy": "actual returned usage.cost only; missing means unavailable",
        "observations": observations,
    }


def write_create_only(payload: Mapping[str, object], output: Path) -> None:
    """私有 run 投影只写入调用方选择的 create-only 输出路径。"""

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
