"""Benchmark comparison report：机器可读 JSON + 人可读 Markdown。

不做综合总分；条件指标旁始终呈现无条件 completion rates；跨 Variant 归因只报告
显式声明的单变量 pair（B−A / C−B / C2−C），D 与其他 Variant 的差异标注为多变量。
"""

from __future__ import annotations

import json
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
        hits = 0.0
        for item in available:
            hits_value = item.get("hits")
            denominator = item.get("denominator")
            if isinstance(hits_value, (int, float)) and isinstance(denominator, (int, float)) and denominator:
                hits += float(hits_value) / float(denominator)
        aggregates.append(
            {
                "name": name,
                "k": k,
                "scope": scope,
                "n": len(available),
                "value": hits / len(available) if available else None,
                "not_applicable_count": not_applicable,
                "unavailable_count": len(unavailable),
                "unavailable_reasons": sorted(
                    {str(item.get("reason")) for item in unavailable if item.get("reason")}
                ),
            }
        )
    return {"metrics": aggregates}


def _metric_label(entry: Mapping[str, object]) -> str:
    k = entry.get("k")
    suffix = f"@{k}" if isinstance(k, int) else ""
    return f"{entry.get('name')}{suffix}"


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
) -> dict[str, object]:
    """组装最终报告。

    ``end_to_end_records`` 按 split 分组：{split: [{variant_id, category, metrics}, ...]}。
    ``holdout_sealed`` 表示 holdout 是否已经运行；未运行时 holdout split 显式 not_run。
    """

    splits: dict[str, object] = {}
    for split, records in end_to_end_records.items():
        by_variant: dict[str, list[MetricRecord]] = {}
        by_variant_category: dict[str, dict[str, list[MetricRecord]]] = {}
        case_counts: dict[str, set[str]] = {}
        for record in records:
            variant_id = record.get("variant_id")
            if not isinstance(variant_id, str):
                raise EvaluationContractError("benchmark record variant_id is invalid")
            category = record.get("category")
            metrics = record.get("metrics", ())
            if not isinstance(metrics, Sequence) or isinstance(metrics, str):
                metrics = ()
            by_variant.setdefault(variant_id, []).extend(metrics)
            case_counts.setdefault(variant_id, set()).add(str(record.get("case_id")))
            if isinstance(category, str):
                by_variant_category.setdefault(variant_id, {}).setdefault(category, []).extend(metrics)
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
        }

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
            "note": "D 与其他 Variant 的差异均为多变量 full-system 差异；跨 Variant 归因只在报告层给出。",
        },
        "failures": [dict(item) for item in failures],
        "holdout_sealed": holdout_sealed,
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
            value = entry.get("value")
            n = entry.get("n")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                reasons = entry.get("unavailable_reasons") or []
                reason_texts = (
                    [str(reason) for reason in reasons]
                    if isinstance(reasons, Sequence) and not isinstance(reasons, str)
                    else []
                )
                cells.append(f"unavail({','.join(reason_texts)})" if reason_texts else "n/a")
            else:
                cells.append(f"{float(value):.3f} (n={n})")
        rows.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(rows) + "\n"


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
    module_retrieval = report.get("module_retrieval")
    if isinstance(module_retrieval, Mapping):
        lines.append("## Module-level retrieval (deterministic)")
        lines.append(f"- packet: `{module_retrieval.get('packet_id')}`")
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
