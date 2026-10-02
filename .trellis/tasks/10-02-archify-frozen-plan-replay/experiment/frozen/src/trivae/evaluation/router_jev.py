"""针对 RuleRouter ambiguous cases 的 LLM/OpenRouter Jev paired diagnostics。"""

from __future__ import annotations

import asyncio
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Literal, Mapping, cast

from trivae.query.completion import CompletionCallback
from trivae.query.contracts import QueryContext
from trivae.query.router import RouteDecision, RouteName, RouterDecisionProvider, RuleRouter
from trivae.query.runtime.contracts import ModelContextMessage


class RouterEvaluationError(ValueError):
    """Router evaluation case 或结果违反其本地 contract。"""


@dataclass(frozen=True)
class RouterEvaluationCase:
    """只承载 Router 可见 context 与 provisional route hypothesis。"""

    case_id: str
    slice: str
    query: str
    locale: str
    prior_context: tuple[ModelContextMessage, ...]
    data_snapshot: Mapping[str, object]
    route_hypothesis: RouteName
    provenance: str
    adjudication_status: str

    def to_context(self) -> QueryContext:
        """构造与生产 Router 相同的 provider-neutral context。"""

        return QueryContext(
            query=self.query,
            locale=self.locale,
            prior_context=self.prior_context,
            data_snapshot=self.data_snapshot,
            available_capabilities=(),
        )


def load_router_evaluation_cases(path: Path) -> tuple[str, tuple[RouterEvaluationCase, ...]]:
    """读取 versioned case manifest，并拒绝重复 ID 或缺失 adjudication 信息。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouterEvaluationError(f"Router case manifest cannot be read: {path}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise RouterEvaluationError("Router case manifest schema_version must be 1")
    suite_id = payload.get("suite_id")
    raw_cases = payload.get("cases")
    if not isinstance(suite_id, str) or not suite_id.strip() or not isinstance(raw_cases, list):
        raise RouterEvaluationError("Router case manifest requires suite_id and a cases array")
    cases: list[RouterEvaluationCase] = []
    seen_ids: set[str] = set()
    for raw_case in raw_cases:
        case = _parse_case(raw_case)
        if case.case_id in seen_ids:
            raise RouterEvaluationError("Router case IDs must be unique")
        seen_ids.add(case.case_id)
        cases.append(case)
    if not cases:
        raise RouterEvaluationError("Router case manifest must contain at least one case")
    return suite_id, tuple(cases)


async def run_paired_router_evaluation(
    *,
    suite_id: str,
    cases: tuple[RouterEvaluationCase, ...],
    llm_completion: CompletionCallback,
    jev_provider: RouterDecisionProvider,
    llm_identity: Mapping[str, str],
    jev_model: str,
    repetitions: int = 1,
) -> dict[str, object]:
    """在相同 QueryContext 上配对运行 baseline 与 Jev，不执行 Planner/Runtime。"""

    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions <= 0:
        raise RouterEvaluationError("repetitions must be a positive integer")
    # A/B runner 固定两种 Provider；每个 Case 都经过相同的确定性 Rule gate。
    llm_router = RuleRouter(completion=llm_completion, provider_mode="existing_llm")
    jev_router = RuleRouter(
        decision_provider=jev_provider,
        jev_enabled=True,
        provider_mode="jev",
    )
    entries: list[dict[str, object]] = []
    for repetition in range(1, repetitions + 1):
        for case in cases:
            # 两个 Provider 接收同一不可变 QueryContext，只对同一 ambiguous 分支发起请求。
            context = case.to_context()
            rule = await RuleRouter().route(context)
            llm_decision, jev_decision = await asyncio.gather(
                llm_router.route(context),
                jev_router.route(context),
            )
            entries.append(
                {
                    "case_id": case.case_id,
                    "repeat": repetition,
                    "slice": case.slice,
                    "ambiguous": rule.confidence < 0.8,
                    "static_route": rule.route,
                    "route_hypothesis": case.route_hypothesis,
                    "provenance": case.provenance,
                    "adjudication_status": case.adjudication_status,
                    "llm": _decision_projection(llm_decision),
                    "jev": _decision_projection(jev_decision),
                }
            )
    # 混淆矩阵、分歧和成本只使用有界的决定投影计算。
    llm_metrics = _variant_metrics(entries, "llm", expected_source="llm")
    jev_metrics = _variant_metrics(entries, "jev", expected_source="jev")
    disagreement_matrix, disagreements = _disagreement(entries)
    adjudication_counts = dict(Counter(case.adjudication_status for case in cases))
    ambiguous_case_count = sum(
        1 for entry in entries if entry["ambiguous"]
    ) // repetitions
    # 所有标签尚未人工确认时，报告只能给出诊断值，不能宣称 Router benchmark 结论。
    promotion = {
        "recommendation": "continue_shadow",
        "promoted": False,
        "quality_gate": "not_adjudicated",
        "reasons": [
            "Route labels are provisional hypotheses pending human adjudication.",
            "The diagnostic case count does not establish generalization or confidence calibration.",
            "Promotion also requires forced-path Planner utility results and review of planned_execution-to-standard_execution errors, latency, cost, and failure rates.",
        ],
    }
    return {
        "schema_version": 1,
        "status": "completed",
        "suite_id": suite_id,
        "provider": "openrouter",
        "configured_decision_model": jev_model,
        "resolved_jev_models": sorted(
            {
                str(output["model"])
                for entry in entries
                for output in (entry["jev"],)
                if isinstance(output, Mapping) and isinstance(output.get("model"), str)
            }
        ),
        "transport": "openrouter_alpha_decisions",
        "baseline": dict(llm_identity),
        "case_summary": {
            "case_count": len(cases),
            "ambiguous_case_count": ambiguous_case_count,
            "repetitions": repetitions,
            "label_status": "provisional_not_ground_truth",
            "adjudication_counts": adjudication_counts,
            "provider_calls_per_variant": sum(1 for entry in entries if entry["ambiguous"]),
        },
        "metrics": {"existing_llm": llm_metrics, "jev": jev_metrics},
        "disagreement": {
            "matrix": disagreement_matrix,
            "cases": disagreements,
        },
        "promotion_recommendation": promotion,
        "limitations": [
            "Route-hypothesis accuracy is not human-adjudicated ground-truth accuracy.",
            "Confidence buckets are descriptive and do not establish calibration.",
            "Baseline cost is unavailable unless its provider returns actual cost metadata.",
            "Jev cost is copied only from OpenRouter usage.cost; no model-price estimate is synthesized.",
            "Latency uses local monotonic wall-clock measurements for ambiguous Router calls.",
        ],
        "cases": entries,
    }


def write_router_evaluation_report(payload: Mapping[str, object], output_path: Path) -> None:
    """以 create-only 语义写入 bounded JSON，避免覆盖已存在实验结果。"""

    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 使用独占创建保证并发评测也不会覆盖先写入的实验结果。
        with output_path.open("x", encoding="utf-8") as output_file:
            output_file.write(serialized)
    except FileExistsError as exc:
        raise RouterEvaluationError(f"Router evaluation output already exists: {output_path}") from exc
    except OSError as exc:
        raise RouterEvaluationError(f"Router evaluation output cannot be written: {output_path}") from exc


def _parse_case(raw_case: object) -> RouterEvaluationCase:
    """将一个 JSON object 校验为普通 RouteContext 与明示 hypothesis。"""

    if not isinstance(raw_case, Mapping):
        raise RouterEvaluationError("each Router case must be an object")
    case_id = _required_text(raw_case, "case_id")
    case_slice = _required_text(raw_case, "slice")
    query = _required_text(raw_case, "query")
    locale = _required_text(raw_case, "locale")
    provenance = _required_text(raw_case, "provenance")
    adjudication_status = _required_text(raw_case, "adjudication_status")
    route_hypothesis = raw_case.get("route_hypothesis")
    if route_hypothesis not in ("standard_execution", "planned_execution"):
        raise RouterEvaluationError("route_hypothesis must be one of the two Router routes")
    raw_history = raw_case.get("prior_context", [])
    if not isinstance(raw_history, list):
        raise RouterEvaluationError("prior_context must be an array")
    history: list[ModelContextMessage] = []
    for item in raw_history:
        if not isinstance(item, Mapping):
            raise RouterEvaluationError("prior_context items must be objects")
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise RouterEvaluationError("prior_context items require user/assistant role and text content")
        history.append(ModelContextMessage(role=role, content=content))
    snapshot = raw_case.get("data_snapshot", {})
    if not isinstance(snapshot, Mapping):
        raise RouterEvaluationError("data_snapshot must be an object")
    return RouterEvaluationCase(
        case_id=case_id,
        slice=case_slice,
        query=query,
        locale=locale,
        prior_context=tuple(history),
        data_snapshot=dict(snapshot),
        route_hypothesis=route_hypothesis,
        provenance=provenance,
        adjudication_status=adjudication_status,
    )


def _required_text(payload: Mapping[str, object], field_name: str) -> str:
    """读取非空 manifest 文本字段，不在错误中回显用户 query。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RouterEvaluationError(f"Router case requires non-empty {field_name}")
    return value.strip()


def _decision_projection(decision: RouteDecision) -> dict[str, object]:
    """只保存 RouteDecision 的 bounded fields，不记录 reason 或原始响应。"""

    return {
        "route": decision.route,
        "source": decision.source,
        "confidence": decision.confidence,
        "probabilities": None if decision.probabilities is None else dict(decision.probabilities),
        "provider": decision.provider,
        "model": decision.model,
        "latency_ms": decision.primary_latency_ms,
        "usage": None if decision.usage is None else dict(decision.usage),
        "degraded": decision.degraded,
        "degradation_code": decision.degradation_code,
        "provider_error_type": decision.provider_error_type,
    }


def _variant_metrics(
    entries: list[dict[str, object]],
    variant_name: Literal["llm", "jev"],
    *,
    expected_source: Literal["llm", "jev"],
) -> dict[str, object]:
    """汇总 hypothesis quality、confidence、时延、错误、usage 与可验证成本。"""

    predictions: list[tuple[dict[str, object], Mapping[str, object]]] = []
    for entry in entries:
        output = entry.get(variant_name)
        if isinstance(output, Mapping):
            predictions.append((entry, cast(Mapping[str, object], output)))
    ambiguous = [(entry, output) for entry, output in predictions if entry["ambiguous"] is True]
    hypothesis_accuracy = _accuracy(predictions)
    ambiguous_accuracy = _accuracy(ambiguous)
    route_counts: dict[RouteName, Counter[RouteName]] = {
        "standard_execution": Counter(),
        "planned_execution": Counter(),
    }
    false_standard_ids: list[str] = []
    false_planned_ids: list[str] = []
    false_standard_observations: list[dict[str, object]] = []
    false_planned_observations: list[dict[str, object]] = []
    # 错误数按重复运行逐次计数，同时单独保存去重后的受影响 Case ID。
    for entry, output in predictions:
        expected = cast(RouteName, entry["route_hypothesis"])
        predicted = cast(RouteName, output["route"])
        route_counts[expected][predicted] += 1
        if expected == "planned_execution" and predicted == "standard_execution":
            false_standard_ids.append(str(entry["case_id"]))
            false_standard_observations.append(
                {"case_id": entry["case_id"], "repeat": entry["repeat"]}
            )
        if expected == "standard_execution" and predicted == "planned_execution":
            false_planned_ids.append(str(entry["case_id"]))
            false_planned_observations.append(
                {"case_id": entry["case_id"], "repeat": entry["repeat"]}
            )
    route_names: tuple[RouteName, RouteName] = ("standard_execution", "planned_execution")
    matrix = {
        expected: {
            predicted: route_counts[expected][predicted]
            for predicted in route_names
        }
        for expected in route_names
    }
    standard_true = matrix["standard_execution"]["standard_execution"]
    planned_true = matrix["planned_execution"]["planned_execution"]
    standard_predicted = standard_true + matrix["planned_execution"]["standard_execution"]
    planned_predicted = planned_true + matrix["standard_execution"]["planned_execution"]
    standard_actual = standard_true + matrix["standard_execution"]["planned_execution"]
    planned_actual = planned_true + matrix["planned_execution"]["standard_execution"]
    # 只把真正调用 Provider 且来源匹配的 confidence 纳入描述区间统计。
    confidence_values: list[float] = []
    confidence_errors: list[Mapping[str, object]] = []
    for entry, output in ambiguous:
        confidence = output.get("confidence")
        if (
            output.get("source") == expected_source
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
        ):
            confidence_values.append(float(confidence))
            if confidence >= 0.8 and output["route"] != entry["route_hypothesis"]:
                confidence_errors.append(output)
    latency_values: list[float] = []
    for _, output in ambiguous:
        latency = output.get("latency_ms")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            latency_values.append(float(latency))
    codes = [
        str(output["degradation_code"])
        for _, output in ambiguous
        if output.get("degradation_code") is not None
    ]
    attempted = len(ambiguous)
    successful = sum(output["source"] == expected_source for _, output in ambiguous)
    timeout_count = sum(1 for code in codes if code.endswith("_TIMEOUT"))
    invalid_count = sum(
        1 for code in codes if code.endswith("_INVALID") or code.endswith("_INVALID_RESPONSE")
    )
    provider_error_names = {
        "ROUTER_COMPLETION_PROVIDER_ERROR",
        "JEV_ROUTER_AUTH_ERROR",
        "JEV_ROUTER_API_KEY_MISSING",
        "JEV_ROUTER_RATE_LIMITED",
        "JEV_ROUTER_NETWORK_ERROR",
        "JEV_ROUTER_MODEL_UNAVAILABLE",
        "JEV_ROUTER_PROVIDER_UNAVAILABLE",
        "JEV_ROUTER_PROVIDER_ERROR",
    }
    provider_error_count = sum(1 for code in codes if code in provider_error_names)
    degraded_count = sum(output["degraded"] is True for _, output in ambiguous)
    # 只聚合实际返回的普通数值 usage，不从模型目录价格推算成本。
    input_tokens = _usage_total(ambiguous, "input_tokens")
    output_tokens = _usage_total(ambiguous, "output_tokens")
    total_tokens = _usage_total(ambiguous, "total_tokens")
    cost_values: list[float] = []
    for _, output in ambiguous:
        usage = output.get("usage")
        if not isinstance(usage, Mapping):
            continue
        cost = usage.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cost_values.append(float(cost))
    observed_cost = math.fsum(cost_values) if cost_values else None
    mean_cost = mean(cost_values) if cost_values else None
    return {
        "quality": {
            "label_basis": "provisional_route_hypothesis",
            "overall_route_accuracy": hypothesis_accuracy,
            "ambiguous_case_accuracy": ambiguous_accuracy,
            "standard_precision": _ratio(standard_true, standard_predicted),
            "standard_recall": _ratio(standard_true, standard_actual),
            "planned_precision": _ratio(planned_true, planned_predicted),
            "planned_recall": _ratio(planned_true, planned_actual),
            "false_standard": len(false_standard_ids),
            "false_standard_case_ids": sorted(set(false_standard_ids)),
            "false_standard_observations": false_standard_observations,
            "false_planned": len(false_planned_ids),
            "false_planned_case_ids": sorted(set(false_planned_ids)),
            "false_planned_observations": false_planned_observations,
            "confusion_matrix": matrix,
            "evaluated_count": len(predictions),
            "ambiguous_count": attempted,
        },
        "confidence": {
            "provider_success_count": len(confidence_values),
            "distribution": _distribution(confidence_values),
            "descriptive_bins": _confidence_bins(ambiguous, expected_source),
            "high_confidence_error_count_at_0_8": len(confidence_errors),
            "calibration_claim": "not_established",
        },
        "performance": {
            "latency_scope": "ambiguous_cases_only; primary route call; nearest-rank percentiles",
            "mean_latency_ms": _rounded(mean(latency_values)) if latency_values else None,
            "p50_latency_ms": _percentile(latency_values, 0.50),
            "p95_latency_ms": _percentile(latency_values, 0.95),
            "provider_attempts": attempted,
            "provider_successes": successful,
            "provider_availability_rate": _ratio(successful, attempted),
            "timeout_rate": _ratio(timeout_count, attempted),
            "provider_error_rate": _ratio(provider_error_count, attempted),
            "invalid_response_rate": _ratio(invalid_count, attempted),
            "degradation_rate": _ratio(degraded_count, attempted),
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd_actual": None if observed_cost is None else _rounded(observed_cost, digits=12),
            "cost_reported_request_count": len(cost_values),
            "cost_coverage_rate": _ratio(len(cost_values), attempted),
            "cost_source": "provider_usage.cost_only" if cost_values else "unavailable",
            "successful_request_cost_usd_per_100_estimate": (
                None if mean_cost is None else _rounded(mean_cost * 100, digits=9)
            ),
            "successful_request_cost_usd_per_1000_estimate": (
                None if mean_cost is None else _rounded(mean_cost * 1000, digits=9)
            ),
            "estimate_basis": (
                "mean of observed per-request cost multiplied by route count"
                if mean_cost is not None
                else "unavailable_without_provider_cost"
            ),
        },
    }


def _accuracy(entries: list[tuple[dict[str, object], Mapping[str, object]]]) -> float | None:
    """按 route hypothesis 计算比例，不把空集伪装成零准确率。"""

    if not entries:
        return None
    correct = sum(1 for entry, output in entries if output["route"] == entry["route_hypothesis"])
    return _ratio(correct, len(entries))


def _disagreement(
    entries: list[dict[str, object]],
) -> tuple[dict[str, dict[str, int]], list[dict[str, object]]]:
    """输出 LLM→Jev route matrix 与只有 ID/分片的 disagreement inventory。"""

    matrix = {
        route: {candidate: 0 for candidate in ("standard_execution", "planned_execution")}
        for route in ("standard_execution", "planned_execution")
    }
    cases: list[dict[str, object]] = []
    for entry in entries:
        llm_value = entry.get("llm")
        jev_value = entry.get("jev")
        if not isinstance(llm_value, Mapping) or not isinstance(jev_value, Mapping):
            continue
        llm = cast(Mapping[str, object], llm_value)
        jev = cast(Mapping[str, object], jev_value)
        llm_route = cast(RouteName, llm["route"])
        jev_route = cast(RouteName, jev["route"])
        matrix[llm_route][jev_route] += 1
        if llm_route != jev_route:
            cases.append(
                {
                    "case_id": entry["case_id"],
                    "repeat": entry["repeat"],
                    "slice": entry["slice"],
                    "route_hypothesis": entry["route_hypothesis"],
                    "llm_route": llm_route,
                    "jev_route": jev_route,
                    "jev_confidence": jev["confidence"],
                    "jev_probabilities": jev["probabilities"],
                    "jev_degradation_code": jev["degradation_code"],
                }
            )
    return matrix, cases


def _distribution(values: list[float]) -> dict[str, float | None]:
    """输出只来自实际 provider answer 的 confidence 分布。"""

    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": _rounded(mean(values)),
        "min": _rounded(min(values)),
        "max": _rounded(max(values)),
    }


def _confidence_bins(
    entries: list[tuple[dict[str, object], Mapping[str, object]]],
    expected_source: Literal["llm", "jev"],
) -> dict[str, dict[str, float | int | None]]:
    """按固定描述性区间展示 confidence 与 correctness，不声称校准。"""

    bins: dict[str, list[tuple[float, bool]]] = {
        "0.0-0.5": [],
        "0.5-0.8": [],
        "0.8-1.0": [],
    }
    for entry, output in entries:
        confidence = output.get("confidence")
        if output.get("source") != expected_source or not isinstance(confidence, (int, float)):
            continue
        value = float(confidence)
        bucket = "0.0-0.5" if value < 0.5 else "0.5-0.8" if value < 0.8 else "0.8-1.0"
        bins[bucket].append((value, output["route"] == entry["route_hypothesis"]))
    return {
        name: {
            "count": len(items),
            "mean_confidence": None if not items else _rounded(mean(value for value, _ in items)),
            "accuracy": None if not items else _ratio(sum(int(correct) for _, correct in items), len(items)),
        }
        for name, items in bins.items()
    }


def _usage_total(
    entries: list[tuple[dict[str, object], Mapping[str, object]]],
    field_name: str,
) -> int | float | None:
    """汇总实际返回的 usage 字段，并保留字段完全缺失时的 unknown。"""

    values: list[int | float] = []
    for _, output in entries:
        usage = output.get("usage")
        if not isinstance(usage, Mapping):
            continue
        value = usage.get(field_name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(value)
    return None if not values else _rounded(math.fsum(float(value) for value in values))


def _percentile(values: list[float], percentile: float) -> float | None:
    """用 nearest-rank 计算小样本 p50/p95，并在报告中公开该定义。"""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return _rounded(ordered[index])


def _ratio(numerator: int, denominator: int) -> float | None:
    """样本数为零时返回 null，避免把 unavailable 编成 0%。"""

    return None if denominator == 0 else _rounded(numerator / denominator)


def _rounded(value: float, *, digits: int = 6) -> float:
    """统一控制报告精度，不参与上游决定或 provider usage 改写。"""

    return round(value, digits)
