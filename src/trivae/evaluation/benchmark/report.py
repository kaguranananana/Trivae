"""Benchmark comparison report：机器可读 JSON + 人可读 Markdown。

不做综合总分；条件指标旁始终呈现无条件 completion rates；跨 Variant 归因只报告
显式声明的单变量 pair（B−A / C−B / C2−C），D 与其他 Variant 的差异标注为多变量。
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from trivae.evaluation.contracts import EvaluationContractError

REPORT_SCHEMA_VERSION = "benchmark-report-v1"

# 显式声明的单变量 pair；D 参与的对比一律标注 multi_variable。
SINGLE_VARIABLE_PAIRS = (
    ("B", "A", "semantic_uplift"),
    ("C", "B", "auto_context_expansion_uplift"),
    ("C2", "C", "explicit_context_tool_uplift"),
)

MetricRecord = Mapping[str, object]

FAILURE_ANALYSIS_CATEGORIES = (
    "provider_failure",
    "zero_result_error",
    "coverage_error",
    "context_missing",
    "retrieval_miss",
    "ranking_failure",
    "router_tool_selection_error",
    "answer_generation_error",
    "evaluation_infrastructure",
    "not_observed_within_recorded_depth",
)


def _numeric(value: object) -> float | None:
    """只接受普通数字，避免把 bool 或字符串静默算进报告。"""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _metric_values(record: MetricRecord) -> tuple[float, float, float]:
    """读取 available metric 的 numerator、denominator 和 case ratio。"""

    hits = _numeric(record.get("hits"))
    denominator = _numeric(record.get("denominator"))
    value = _numeric(record.get("value"))
    if hits is None or denominator is None or denominator <= 0 or value is None:
        raise EvaluationContractError("available metric record must contain numeric hits/denominator/value")
    return hits, denominator, value


def aggregate_metric_records(
    records: Iterable[MetricRecord],
) -> dict[str, list[dict[str, object]]]:
    """序列化 metric 记录的 macro 聚合；not_applicable 不进分母。"""

    grouped: dict[tuple[str, int | None, str], list[MetricRecord]] = {}
    for record in records:
        name = record.get("name")
        if not isinstance(name, str):
            raise EvaluationContractError("metric record name is invalid")
        k_value = record.get("k")
        k = k_value if isinstance(k_value, int) and not isinstance(k_value, bool) else None
        scope = record.get("scope")
        if not isinstance(scope, str):
            raise EvaluationContractError("metric record scope is invalid")
        grouped.setdefault((name, k, scope), []).append(record)
    aggregates: list[dict[str, object]] = []
    for (name, k, scope), items in sorted(grouped.items(), key=lambda entry: (entry[0][0], entry[0][1] or 0, entry[0][2])):
        available = [item for item in items if item.get("availability") == "available"]
        not_applicable = sum(1 for item in items if item.get("availability") == "not_applicable")
        unavailable = [item for item in items if item.get("availability") == "unavailable"]
        # numerator/denominator 是加权 rate；value 继续保留旧的 macro ratio，便于比较
        # “每个 case 等权”与“按事实条目加权”两种口径，避免只输出一个百分比。
        values = [_metric_values(item) for item in available]
        numerator = sum(item[0] for item in values)
        denominator = sum(item[1] for item in values)
        macro_values = [item[2] for item in values]
        aggregates.append(
            {
                "name": name,
                "k": k,
                "scope": scope,
                "n": len(available),
                "numerator": numerator if values else None,
                "denominator": denominator if values else None,
                "rate": numerator / denominator if values else None,
                "value": sum(macro_values) / len(macro_values) if macro_values else None,
                "not_applicable_count": not_applicable,
                "unavailable_count": len(unavailable),
                "unavailable_reasons": sorted(
                    {str(item.get("reason")) for item in unavailable if item.get("reason")}
                ),
            }
        )
    return {"metrics": aggregates}


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    """按 nearest-rank 规则计算确定性的 P50/P95，不依赖外部统计库。"""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _series_stats(values: Sequence[float], total_count: int) -> dict[str, object]:
    """汇总一个 operational 数列，并显式保留没有观测值的数量。"""

    return {
        "n": len(values),
        "unavailable_count": total_count - len(values),
        "mean": sum(values) / len(values) if values else None,
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
    }


def _aggregate_operational(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """按 split/variant 或 category 汇总 latency、tool calls 和 token usage。"""

    total_count = len(records)
    latencies: list[float] = []
    tool_calls: list[float] = []
    tool_rounds: list[float] = []
    token_values: dict[str, list[float]] = {
        "input_tokens": [],
        "output_tokens": [],
        "total_tokens": [],
    }
    for record in records:
        measurements = record.get("operational_measurements")
        if not isinstance(measurements, Mapping):
            continue
        latency = _numeric(measurements.get("latency_ms"))
        if latency is not None:
            latencies.append(latency)
        calls = _numeric(measurements.get("tool_calls"))
        if calls is not None:
            tool_calls.append(calls)
        rounds = _numeric(measurements.get("tool_rounds"))
        if rounds is not None:
            tool_rounds.append(rounds)
        usage = measurements.get("usage")
        if isinstance(usage, Mapping):
            for name, value in usage.items():
                if not isinstance(name, str):
                    continue
                token_values.setdefault(name, [])
                numeric = _numeric(value)
                if numeric is not None:
                    token_values[name].append(numeric)
    tokens = {
        name: {
            **_series_stats(values, total_count),
            "total": sum(values) if values else None,
        }
        for name, values in sorted(token_values.items())
    }
    return {
        "run_count": total_count,
        "latency_ms": _series_stats(latencies, total_count),
        "tool_calls": _series_stats(tool_calls, total_count),
        "tool_rounds": _series_stats(tool_rounds, total_count),
        "tokens": tokens,
    }


def _metric_key(metric: Mapping[str, object]) -> tuple[str, int | None, str]:
    """为单 case metric 建立稳定的 name/k/scope identity。"""

    name = metric.get("name")
    scope = metric.get("scope")
    k_value = metric.get("k")
    k = k_value if isinstance(k_value, int) and not isinstance(k_value, bool) else None
    if not isinstance(name, str) or not isinstance(scope, str):
        raise EvaluationContractError("comparison metric identity is invalid")
    return name, k, scope


def _metric_map(record: Mapping[str, object]) -> dict[tuple[str, int | None, str], Mapping[str, object]]:
    """把一个 run 的 metrics 转成唯一索引；重复 metric 不静默覆盖。"""

    raw_metrics = record.get("metrics", ())
    if not isinstance(raw_metrics, Sequence) or isinstance(raw_metrics, str):
        raise EvaluationContractError("comparison run record metrics must be an array")
    output: dict[tuple[str, int | None, str], Mapping[str, object]] = {}
    for raw_metric in raw_metrics:
        if not isinstance(raw_metric, Mapping):
            raise EvaluationContractError("comparison metric must be an object")
        key = _metric_key(raw_metric)
        if key in output:
            raise EvaluationContractError(f"duplicate metric in run record: {key!r}")
        output[key] = raw_metric
    return output


def _available_metric_value(metric: Mapping[str, object] | None) -> tuple[float, float, float] | None:
    """返回 available metric 的数值；不可比较的状态保持显式 None。"""

    if metric is None or metric.get("availability") != "available":
        return None
    return _metric_values(metric)


def _record_index(
    records: Sequence[Mapping[str, object]],
    variant_id: str,
) -> dict[str, Mapping[str, object]]:
    """按 case_id 对齐同一 variant 的单 repetition 记录。"""

    indexed: dict[str, Mapping[str, object]] = {}
    for record in records:
        if record.get("variant_id") != variant_id:
            continue
        case_id = record.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise EvaluationContractError("comparison record case_id is invalid")
        if case_id in indexed:
            raise EvaluationContractError(f"duplicate comparison record for {variant_id}/{case_id}")
        indexed[case_id] = record
    return indexed


def _pair_metric_comparison(
    candidate_records: Mapping[str, Mapping[str, object]],
    baseline_records: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """对齐 common cases，输出每个 metric 的 paired delta 与分母。"""

    common_case_ids = sorted(set(candidate_records) & set(baseline_records))
    all_keys: set[tuple[str, int | None, str]] = set()
    candidate_metric_maps = {case_id: _metric_map(record) for case_id, record in candidate_records.items()}
    baseline_metric_maps = {case_id: _metric_map(record) for case_id, record in baseline_records.items()}
    for case_id in common_case_ids:
        all_keys.update(candidate_metric_maps[case_id])
        all_keys.update(baseline_metric_maps[case_id])
    metrics: list[dict[str, object]] = []
    for name, k, scope in sorted(all_keys, key=lambda item: (item[0], item[1] or 0, item[2])):
        key = (name, k, scope)
        candidate_values: list[tuple[float, float, float]] = []
        baseline_values: list[tuple[float, float, float]] = []
        candidate_available_count = 0
        baseline_available_count = 0
        candidate_better = 0
        baseline_better = 0
        ties = 0
        for case_id in common_case_ids:
            candidate_value = _available_metric_value(candidate_metric_maps[case_id].get(key))
            baseline_value = _available_metric_value(baseline_metric_maps[case_id].get(key))
            if candidate_value is not None:
                candidate_available_count += 1
            if baseline_value is not None:
                baseline_available_count += 1
            if candidate_value is None or baseline_value is None:
                continue
            candidate_values.append(candidate_value)
            baseline_values.append(baseline_value)
            if candidate_value[2] > baseline_value[2]:
                candidate_better += 1
            elif baseline_value[2] > candidate_value[2]:
                baseline_better += 1
            else:
                ties += 1

        def side(values: Sequence[tuple[float, float, float]]) -> dict[str, object]:
            numerator = sum(item[0] for item in values)
            denominator = sum(item[1] for item in values)
            macro = sum(item[2] for item in values) / len(values) if values else None
            return {
                "numerator": numerator if values else None,
                "denominator": denominator if values else None,
                "rate": numerator / denominator if values else None,
                "macro_value": macro,
            }

        candidate_side = side(candidate_values)
        baseline_side = side(baseline_values)
        candidate_rate = _numeric(candidate_side["rate"])
        baseline_rate = _numeric(baseline_side["rate"])
        candidate_macro = _numeric(candidate_side["macro_value"])
        baseline_macro = _numeric(baseline_side["macro_value"])
        metrics.append(
            {
                "name": name,
                "k": k,
                "scope": scope,
                "common_case_count": len(common_case_ids),
                "paired_n": len(candidate_values),
                "candidate_available_count": candidate_available_count,
                "baseline_available_count": baseline_available_count,
                "unavailable_pair_count": len(common_case_ids) - len(candidate_values),
                "candidate": candidate_side,
                "baseline": baseline_side,
                "delta": {
                    "rate": None
                    if candidate_rate is None or baseline_rate is None
                    else candidate_rate - baseline_rate,
                    "macro_value": None
                    if candidate_macro is None or baseline_macro is None
                    else candidate_macro - baseline_macro,
                },
                "candidate_better": candidate_better,
                "baseline_better": baseline_better,
                "ties": ties,
                "interpretation": (
                    "candidate_uplift"
                    if candidate_rate is not None
                    and baseline_rate is not None
                    and candidate_rate > baseline_rate
                    else "candidate_regression"
                    if candidate_rate is not None
                    and baseline_rate is not None
                    and candidate_rate < baseline_rate
                    else "tie"
                    if candidate_rate is not None and baseline_rate is not None
                    else "unavailable"
                ),
            }
        )
    return metrics


def _variant_alias_map(
    variants: Sequence[Mapping[str, object]],
    records: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, str]:
    """从受控 variant 的显式 ablation_role 读取 A/B/C/C2 身份。"""

    known_ids = {
        str(record.get("variant_id"))
        for split_records in records.values()
        for record in split_records
        if isinstance(record.get("variant_id"), str)
    }
    aliases: dict[str, str] = {}
    for variant in variants:
        variant_id = variant.get("variant_id")
        if not isinstance(variant_id, str) or variant_id not in known_ids:
            continue
        extra = variant.get("extra_configuration")
        role = extra.get("ablation_role") if isinstance(extra, Mapping) else None
        alias = role.split(":", 1)[0].strip() if isinstance(role, str) and ":" in role else None
        if alias not in {"A", "B", "C", "C2", "D"}:
            alias = variant_id if variant_id in {"A", "B", "C", "C2", "D"} else None
        if alias is not None:
            previous = aliases.get(alias)
            if previous is not None and previous != variant_id:
                raise EvaluationContractError(f"variant alias is ambiguous: {alias}")
            aliases[alias] = variant_id
    return aliases


def build_cross_variant_comparisons(
    *,
    variants: Sequence[Mapping[str, object]],
    end_to_end_records: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    """生成真实的 B−A/C−B/C2−C paired comparison，而不是只输出声明。"""

    aliases = _variant_alias_map(variants, end_to_end_records)
    comparisons: list[dict[str, object]] = []
    for candidate, baseline, label in SINGLE_VARIABLE_PAIRS:
        candidate_id = aliases.get(candidate)
        baseline_id = aliases.get(baseline)
        comparison: dict[str, object] = {
            "candidate": candidate,
            "baseline": baseline,
            "candidate_variant_id": candidate_id,
            "baseline_variant_id": baseline_id,
            "label": label,
            "multi_variable": False,
        }
        if candidate_id is None or baseline_id is None:
            comparison["status"] = "unavailable"
            comparison["reason"] = "variant_ablation_role_not_resolved"
            comparisons.append(comparison)
            continue
        split_results: list[dict[str, object]] = []
        for split, records in end_to_end_records.items():
            candidate_records = _record_index(records, candidate_id)
            baseline_records = _record_index(records, baseline_id)
            split_results.append(
                {
                    "split": split,
                    "candidate_case_count": len(candidate_records),
                    "baseline_case_count": len(baseline_records),
                    "metrics": _pair_metric_comparison(candidate_records, baseline_records),
                }
            )
        comparison["status"] = "available"
        comparison["splits"] = split_results
        comparisons.append(comparison)
    return comparisons


def summarize_failures(failures: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """汇总 acceptance failure；低 Recall/MRR 不自动冒充 failure。"""

    counts = {category: 0 for category in FAILURE_ANALYSIS_CATEGORIES}
    unknown: dict[str, int] = {}
    for failure in failures:
        category = failure.get("category")
        if not isinstance(category, str):
            continue
        if category in counts:
            counts[category] += 1
        else:
            unknown[category] = unknown.get(category, 0) + 1
    return {
        "observed_failure_artifact_count": len(failures),
        "by_category": {
            category: {
                "count": count,
                "status": "observed" if count else "not_observed",
            }
            for category, count in counts.items()
        },
        "unknown_categories": unknown,
        "notes": [
            "Low Recall/MRR alone remains a quality result and is not classified as a failure artifact.",
            "ranking_failure and router_tool_selection_error require direct Trace evidence; zero here means not observed in the artifact.",
            "semantic/context uplift is reported in cross_variant comparisons, not folded into acceptance failures.",
        ],
    }


def _metric_label(entry: Mapping[str, object]) -> str:
    k = entry.get("k")
    suffix = f"@{k}" if isinstance(k, int) else ""
    return f"{entry.get('name')}{suffix}"


def _number_text(value: object) -> str:
    """以紧凑文本渲染报告中的整数/浮点事实。"""

    numeric = _numeric(value)
    if numeric is None:
        return "n/a"
    return str(int(numeric)) if numeric.is_integer() else f"{numeric:.3f}"


def _metric_cell(entry: Mapping[str, object]) -> str:
    """渲染 rate、numerator/denominator、macro 和 case n，避免只展示百分比。"""

    rate = _numeric(entry.get("rate"))
    macro = _numeric(entry.get("value"))
    if rate is None:
        reasons = entry.get("unavailable_reasons") or []
        reason_texts = (
            [str(reason) for reason in reasons]
            if isinstance(reasons, Sequence) and not isinstance(reasons, str)
            else []
        )
        return f"unavail({','.join(reason_texts)})" if reason_texts else "n/a"
    counts = f"{_number_text(entry.get('numerator'))}/{_number_text(entry.get('denominator'))}"
    macro_text = "n/a" if macro is None else f"{macro:.3f}"
    return f"{rate:.3f} ({counts}; macro={macro_text}; n={entry.get('n')})"


def build_report(
    *,
    benchmark: str,
    environment: Mapping[str, object],
    variants: Sequence[Mapping[str, object]],
    case_stats: Mapping[str, object],
    end_to_end_records: Mapping[str, Sequence[Mapping[str, object]]],
    module_retrieval: Mapping[str, object] | None,
    failures: Sequence[Mapping[str, object]],
    holdout_sealed: bool,
    report_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """组装最终报告。

    ``end_to_end_records`` 按 split 分组：{split: [{variant_id, category, metrics}, ...]}。
    ``holdout_sealed`` 表示 holdout 是否已经运行；未运行时 holdout split 显式 not_run。
    """

    splits: dict[str, object] = {}
    for split, records in end_to_end_records.items():
        by_variant: dict[str, list[MetricRecord]] = {}
        by_variant_category: dict[str, dict[str, list[MetricRecord]]] = {}
        by_variant_records: dict[str, list[Mapping[str, object]]] = {}
        by_variant_category_records: dict[str, dict[str, list[Mapping[str, object]]]] = {}
        case_counts: dict[str, set[str]] = {}
        for record in records:
            variant_id = record.get("variant_id")
            if not isinstance(variant_id, str):
                raise EvaluationContractError("benchmark record variant_id is invalid")
            category = record.get("category")
            metrics = record.get("metrics", ())
            if not isinstance(metrics, Sequence) or isinstance(metrics, str):
                raise EvaluationContractError("benchmark record metrics must be an array")
            by_variant.setdefault(variant_id, []).extend(metrics)
            by_variant_records.setdefault(variant_id, []).append(record)
            case_counts.setdefault(variant_id, set()).add(str(record.get("case_id")))
            if isinstance(category, str):
                by_variant_category.setdefault(variant_id, {}).setdefault(category, []).extend(metrics)
                by_variant_category_records.setdefault(variant_id, {}).setdefault(category, []).append(record)
        splits[split] = {
            "cases": {variant_id: len(case_ids) for variant_id, case_ids in case_counts.items()},
            "overall": {
                variant_id: aggregate_metric_records(metric_records)
                for variant_id, metric_records in by_variant.items()
            },
            "by_category": {
                variant_id: {
                    category: aggregate_metric_records(category_records)
                    for category, category_records in categories.items()
                }
                for variant_id, categories in by_variant_category.items()
            },
            "operational": {
                variant_id: _aggregate_operational(variant_records)
                for variant_id, variant_records in by_variant_records.items()
            },
            "operational_by_category": {
                variant_id: {
                    category: _aggregate_operational(category_records)
                    for category, category_records in categories.items()
                }
                for variant_id, categories in by_variant_category_records.items()
            },
        }

    failure_items = [dict(item) for item in failures]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "benchmark": benchmark,
        "environment": dict(environment),
        "variants": [dict(item) for item in variants],
        "case_stats": dict(case_stats),
        "splits": splits,
        "module_retrieval": dict(module_retrieval) if module_retrieval is not None else None,
        "cross_variant": {
            "single_variable_pairs": [
                {"candidate": candidate, "baseline": baseline, "label": label, "multi_variable": False}
                for candidate, baseline, label in SINGLE_VARIABLE_PAIRS
            ],
            "comparisons": build_cross_variant_comparisons(
                variants=variants,
                end_to_end_records=end_to_end_records,
            ),
            "note": "D 与其他 Variant 的差异均为多变量 full-system 差异；跨 Variant 归因只在报告层给出。",
        },
        "failure_analysis": summarize_failures(failure_items),
        "failures": failure_items,
        "holdout_sealed": holdout_sealed,
        "metadata": dict(report_metadata) if report_metadata is not None else {},
    }


def _variant_matrix(
    split_payload: Mapping[str, object],
    metric_names: Sequence[str],
) -> str:
    overall = split_payload.get("overall", {})
    if not isinstance(overall, Mapping) or not overall:
        return "_no runs_\n"
    variant_ids = sorted(overall)
    values: dict[tuple[str, str], Mapping[str, object]] = {}
    for variant_id, aggregate in overall.items():
        if not isinstance(aggregate, Mapping):
            continue
        for entry in aggregate.get("metrics", ()):
            if isinstance(entry, Mapping):
                values[(variant_id, _metric_label(entry))] = entry
    labels = sorted({label for _, label in values}, key=lambda label: (metric_names.index(label.split("@")[0]) if label.split("@")[0] in metric_names else len(metric_names), label))
    header = "| metric | " + " | ".join(str(item) for item in variant_ids) + " |"
    separator = "|---" * (len(variant_ids) + 1) + "|"
    rows = [header, separator]
    for label in labels:
        cells = []
        for variant_id in variant_ids:
            entry = values.get((variant_id, label))
            if entry is None:
                cells.append("n/a")
                continue
            cells.append(_metric_cell(entry))
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n"


def _series_text(value: object) -> str:
    """渲染 operational series 的样本量、缺失量、均值与分位数。"""

    if not isinstance(value, Mapping):
        return "unavailable"
    return (
        f"n={value.get('n')}; unavailable={value.get('unavailable_count')}; "
        f"mean={_number_text(value.get('mean'))}; p50={_number_text(value.get('p50'))}; "
        f"p95={_number_text(value.get('p95'))}"
    )


def _signed_text(value: object) -> str:
    """以带符号形式显示跨 Variant 的 rate delta。"""

    numeric = _numeric(value)
    return "n/a" if numeric is None else f"{numeric:+.3f}"


def render_markdown(report: Mapping[str, object]) -> str:
    """渲染人可读报告；无数据的指标显示 unavail/n/a，绝不编造数字。"""

    lines: list[str] = []
    lines.append(f"# Benchmark Report: {report.get('benchmark')}")
    environment = report.get("environment", {})
    if isinstance(environment, Mapping):
        lines.append(f"- snapshot: `{environment.get('canonical_snapshot_id')}`")
        lines.append(f"- git commit: `{environment.get('git_commit')}`")
        lines.append(f"- semantic index: `{environment.get('semantic_index')}`")
    lines.append(f"- holdout sealed: {report.get('holdout_sealed')}")
    metadata = report.get("metadata")
    if isinstance(metadata, Mapping):
        for key, label in (
            ("stage", "stage"),
            ("split", "split"),
            ("stage3_final_execution_commit", "stage3 final execution commit"),
            ("dev_case_count", "dev cases"),
            ("run_count", "runs"),
            ("calibration_excluded", "calibration excluded"),
            ("holdout_absent", "holdout absent"),
            ("gt_adjudicated", "GT adjudicated"),
            ("final_rerun_identity", "final rerun identity"),
            ("final_rerun_timestamp", "final rerun timestamp"),
        ):
            if key in metadata:
                lines.append(f"- {label}: `{metadata.get(key)}`")
        fingerprints = metadata.get("variant_fingerprints")
        if isinstance(fingerprints, Mapping):
            lines.append("- variant fingerprints:")
            for variant_id in sorted(fingerprints):
                lines.append(f"  - `{variant_id}`: `{fingerprints[variant_id]}`")
    lines.append("")
    case_stats = report.get("case_stats", {})
    if isinstance(case_stats, Mapping):
        lines.append("## Case stats")
        for key, value in case_stats.items():
            lines.append(f"- {key}: {value}")
        lines.append("")
    splits = report.get("splits", {})
    if isinstance(splits, Mapping):
        ordered = ("development", "full", "holdout")
        for split in ordered + tuple(key for key in splits if key not in ordered):
            payload = splits.get(split)
            if not isinstance(payload, Mapping):
                continue
            lines.append(f"## Split: {split}")
            cases = payload.get("cases", {})
            if isinstance(cases, Mapping):
                lines.append(f"- cases per variant: {dict(sorted(cases.items()))}")
            lines.append("")
            lines.append(_variant_matrix(payload, _TIER1_METRIC_ORDER))
            operational = payload.get("operational")
            if isinstance(operational, Mapping):
                lines.append("### Operational")
                for variant_id in sorted(operational):
                    entry = operational[variant_id]
                    if not isinstance(entry, Mapping):
                        continue
                    lines.append(
                        f"- {variant_id}: latency_ms [{_series_text(entry.get('latency_ms'))}]; "
                        f"tool_calls [{_series_text(entry.get('tool_calls'))}]; "
                        f"tool_rounds [{_series_text(entry.get('tool_rounds'))}]"
                    )
                    tokens = entry.get("tokens")
                    if isinstance(tokens, Mapping):
                        for token_name in sorted(tokens):
                            token_entry = tokens[token_name]
                            total = token_entry.get("total") if isinstance(token_entry, Mapping) else None
                            lines.append(
                                f"  - {variant_id} / {token_name}: total={_number_text(total)}; "
                                f"[{_series_text(token_entry)}]"
                            )
                lines.append("")
            by_category = payload.get("by_category", {})
            if isinstance(by_category, Mapping):
                for variant_id in sorted(by_category):
                    categories = by_category[variant_id]
                    if not isinstance(categories, Mapping):
                        continue
                    for category in sorted(categories):
                        lines.append(f"### {split} / {variant_id} / {category}")
                        category_payload = categories[category]
                        if isinstance(category_payload, Mapping):
                            lines.append(_variant_matrix({"overall": {variant_id: category_payload}}, _TIER1_METRIC_ORDER))
    cross_variant = report.get("cross_variant")
    if isinstance(cross_variant, Mapping):
        comparisons = cross_variant.get("comparisons")
        if isinstance(comparisons, Sequence) and not isinstance(comparisons, str):
            lines.append("## Cross-variant comparisons")
            for comparison in comparisons:
                if not isinstance(comparison, Mapping):
                    continue
                lines.append(
                    f"### {comparison.get('candidate')} − {comparison.get('baseline')} "
                    f"({comparison.get('label')})"
                )
                if comparison.get("status") != "available":
                    lines.append(f"- unavailable: {comparison.get('reason')}")
                    continue
                split_results = comparison.get("splits", ())
                if not isinstance(split_results, Sequence) or isinstance(split_results, str):
                    continue
                for split_result in split_results:
                    if not isinstance(split_result, Mapping):
                        continue
                    lines.append(
                        f"- split={split_result.get('split')}; "
                        f"candidate_cases={split_result.get('candidate_case_count')}; "
                        f"baseline_cases={split_result.get('baseline_case_count')}"
                    )
                    metrics = split_result.get("metrics", ())
                    if not isinstance(metrics, Sequence) or isinstance(metrics, str):
                        continue
                    for metric in metrics:
                        if not isinstance(metric, Mapping):
                            continue
                        delta = metric.get("delta")
                        delta_rate = delta.get("rate") if isinstance(delta, Mapping) else None
                        lines.append(
                            f"  - {_metric_label(metric)}: delta(rate)={_signed_text(delta_rate)}; "
                            f"paired_n={metric.get('paired_n')}; "
                            f"interpretation={metric.get('interpretation')}"
                        )
            lines.append("")
    module_retrieval = report.get("module_retrieval")
    if isinstance(module_retrieval, Mapping):
        lines.append("## Module-level retrieval (deterministic)")
        lines.append(f"- packet: `{module_retrieval.get('packet_id')}`")
        lines.append("")
    failure_analysis = report.get("failure_analysis")
    if isinstance(failure_analysis, Mapping):
        lines.append("## Failure analysis summary")
        lines.append(
            f"- observed failure artifacts: {failure_analysis.get('observed_failure_artifact_count')}"
        )
        categories = failure_analysis.get("by_category")
        if isinstance(categories, Mapping):
            for category in sorted(categories):
                item = categories[category]
                if isinstance(item, Mapping):
                    lines.append(f"- {category}: {item.get('count')} ({item.get('status')})")
        lines.append("")
    failures = report.get("failures", [])
    if isinstance(failures, Sequence) and not isinstance(failures, str):
        lines.append(f"## Failures ({len(failures)})")
        for failure in failures:
            if isinstance(failure, Mapping):
                lines.append(
                    f"- {failure.get('category')} / {failure.get('case_id')} / {failure.get('variant_id')}: {failure.get('detail')}"
                )
        lines.append("")
    return "\n".join(lines)


_TIER1_METRIC_ORDER = (
    "execution_completed",
    "valid_answer",
    "recall_at_k",
    "hit_at_k",
    "mrr_at_k",
    "evidence_recall",
    "context_recovery",
    "coverage_status_accuracy",
    "truncation_accuracy",
    "expected_fact_answer_coverage",
    "false_zero_result",
    "verified_zero_result",
)


def write_report_outputs(
    report: Mapping[str, object],
    *,
    json_path: Path,
    markdown_path: Path | None = None,
) -> None:
    """落盘 JSON（机器可读）与 Markdown（人可读）；目录不存在则创建。"""

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
