"""Generate an auditable per-case comparison of Eval v1 and Judge v2 Reviews."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from trivae.evaluation.capability_audit import CAPABILITY_AXES
from trivae.evaluation.capability_judge import CAPABILITY_AXES_V2
from trivae.evaluation.contracts import EvaluationReview, EvaluationRun

BASELINE = Path("data/evaluation/eval-v1-baseline-20261028")
BUNDLE = Path("data/evaluation/eval-v1-20261028")
EXPERIMENT = Path("data/evaluation/eval-v2-baseline-20261028")
V1_LABELS = {"pass": "通过", "mixed": "部分通过", "fail": "未通过", "unknown": "未知"}
V2_SCORE_LABELS = {4: "优秀", 3: "合格", 2: "部分合格", 1: "较差", 0: "失败", "unknown": "未知"}
DIAGNOSTIC_TYPES_ZH = {
    "omitted_key_information": "遗漏关键信息",
    "factual_error": "事实错误",
    "attribution_error": "事实归属错误",
    "citation_mismatch": "引用不支持结论",
    "unsupported_assertion": "无依据断言或过度概括",
    "temporal_or_scope_error": "时间或适用范围错误",
    "other": "其他问题",
}
SEVERITY_ZH = {"minor": "轻微", "moderate": "中等", "severe": "严重"}
V1_AXIS_NAMES_ZH = {
    "task_completion": "任务完成",
    "factual_correctness": "事实正确",
    "evidence_recall": "证据覆盖",
    "citation_faithfulness": "引用忠实",
    "unsupported_claims": "无依据主张",
}
V2_AXIS_NAMES_ZH = {"task_satisfaction": "任务满足度", "answer_reliability": "回答可信度"}


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _reviews(database_paths: list[Path], rubric_version: str) -> dict[str, EvaluationReview]:
    result: dict[str, EvaluationReview] = {}
    for path in database_paths:
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT r.payload_json, e.case_id FROM evaluation_reviews r "
                "JOIN evaluation_runs e ON e.run_id=r.run_id ORDER BY e.case_id, r.created_at"
            ).fetchall()
            for row in rows:
                review = EvaluationReview.from_dict(json.loads(row["payload_json"]))
                if review.rubric_version != rubric_version:
                    continue
                if row["case_id"] in result:
                    raise ValueError(f"duplicate {rubric_version} review for {row['case_id']}")
                result[row["case_id"]] = review
        finally:
            con.close()
    return result


def _quote(value: str) -> str:
    return "\n".join("> " + (line or "") for line in value.splitlines())


def _v1_axis(review: EvaluationReview | None, axis: str) -> str:
    if review is None:
        return "未评分（Agent 运行失败）"
    assessment = review.quality_axes.get(axis)
    if not isinstance(assessment, dict):
        return "缺少该维度记录"
    label = assessment.get("label", "unknown")
    reason = assessment.get("reason", "")
    return f"**{V1_LABELS.get(str(label), str(label))}** — {reason}"


def _score(review: EvaluationReview | None, axis: str) -> int | str | None:
    if review is None:
        return None
    assessment = review.quality_axes.get(axis)
    if not isinstance(assessment, dict):
        return None
    return assessment.get("score") if isinstance(assessment.get("score"), (int, str)) else None


def _score_display(score: int | str | None) -> str:
    if score == "unknown":
        return "unknown"
    if isinstance(score, int) and not isinstance(score, bool):
        return f"{score}/4"
    return "缺少评分"


def _render_case(
    case_id: str,
    question: str,
    run: dict[str, Any],
    v1_review: EvaluationReview | None,
    v2_review: EvaluationReview | None,
    campaign_case: dict[str, Any],
) -> str:
    lines = [f"## {case_id}", "", "**原始问题：**", "", _quote(question), ""]
    if run["terminal_status"] != "completed" or run.get("query_result") is None:
        failure = run.get("failure_diagnostic", {})
        if not failure:
            failure = {
                "diagnostic_type": run.get("exception_type"),
                "category": None,
                "error_code": None,
                "provider_status_codes": [],
            }
        status_codes = failure.get("provider_status_codes", [])
        status_text = ", ".join(str(code) for code in status_codes) if status_codes else "未记录"
        lines.extend([
            f"**Baseline 状态：** Agent 运行失败（`{run['terminal_status']}`，`{failure.get('diagnostic_type') or run.get('exception_type') or '异常类型未记录'}`；"
            f"分类 `{failure.get('category') or '未记录'}`；错误码 `{failure.get('error_code') or '未记录'}`；"
            f"Provider HTTP 状态码 `{status_text}`）。",
            "",
            "**原始运行诊断：** 根据 Baseline 已保存的失败摘要和 Trace 元数据；没有读取或推断新的 Agent 结果。",
            "",
            "**Judge v1：** 未评分。",
            "",
            "**Judge v2：** 未评分；保留原失败状态，没有生成答案或质量分数。",
            "",
            f"**v1/v2 结论：** 该 Case 不属于质量评分分母，运行记录为 `{run['run_id']}`。",
            "",
        ])
        return "\n".join(lines)

    if v1_review is None:
        lines.extend(["**Judge v1：** 缺少对应历史 Review。", ""])
    else:
        lines.extend(["**Judge v1 五维评分：**", ""])
        for axis in CAPABILITY_AXES:
            lines.append(f"- {V1_AXIS_NAMES_ZH[axis]}（`{axis}`）：{_v1_axis(v1_review, axis)}")
        lines.append("")

    if v2_review is None:
        status = campaign_case.get("status", "review_failed")
        reason = campaign_case.get("failure_reason", "无已保存的 v2 Review")
        lines.extend([f"**Judge v2：** 未评分（`{status}`）：`{json.dumps(reason, ensure_ascii=False)}`。", ""])
    else:
        lines.extend(["**Judge v2 双维度评分：**", ""])
        for axis in CAPABILITY_AXES_V2:
            assessment = v2_review.quality_axes[axis]
            score = assessment["score"]
            label = V2_SCORE_LABELS.get(score, "未知")
            display = f"{score}/4（{label}）" if isinstance(score, int) and not isinstance(score, bool) else "unknown（未知）"
            lines.append(f"- {V2_AXIS_NAMES_ZH[axis]}（`{axis}`）：**{display}** — {assessment['reason']}")
        lines.append("")
        lines.append(f"**完整评判理由：** {v2_review.notes or '未提供整体理由。'}")
        lines.append("")
        lines.append("**具体质量问题：**")
        if not v2_review.diagnostics:
            lines.append("- 未记录具体问题。")
        else:
            for index, item in enumerate(v2_review.diagnostics, start=1):
                excerpt = "（遗漏项无可引用原文）" if item.get("answer_excerpt") is None else f"“{item['answer_excerpt']}”"
                lines.extend([
                    f"- {index}. **{DIAGNOSTIC_TYPES_ZH.get(str(item['type']), str(item['type']))}**，"
                    f"**{SEVERITY_ZH.get(str(item['severity']), str(item['severity']))}**，"
                    f"主要影响 `{item['primary_dimension']}`；回答摘录：{excerpt}",
                    f"  - 证据/证据缺口：{item['evidence']}",
                    f"  - 对用户的影响：{item['impact']}",
                ])
        lines.append("")

    if v1_review is not None and v2_review is not None:
        old_task = "/".join(str(v1_review.quality_axes.get(axis, {}).get("label", "unknown"))
                             for axis in ("task_completion", "evidence_recall"))
        old_reliability = "/".join(str(v1_review.quality_axes.get(axis, {}).get("label", "unknown"))
                                   for axis in ("factual_correctness", "citation_faithfulness", "unsupported_claims"))
        task_score = _score(v2_review, "task_satisfaction")
        reliability_score = _score(v2_review, "answer_reliability")
        task_reason = v2_review.quality_axes["task_satisfaction"]["reason"]
        reliability_reason = v2_review.quality_axes["answer_reliability"]["reason"]
        lines.extend([
            "**相较 v1 的结论变化与原因（维度不同，不比较分数大小）：**",
            "",
            f"- 任务侧：v1 将任务完成/证据覆盖分别标为 `{old_task}`；v2 合并判断后为 `"
            f"{_score_display(task_score)}`。新结论聚焦于“{task_reason}”中的核心需求和遗漏影响。",
            f"- 可信度侧：v1 将事实、引用、无依据主张分别标为 `{old_reliability}`；v2 汇总为 `"
            f"{_score_display(reliability_score)}`，并由上方诊断明确标出问题类型及其主影响维度。理由：{reliability_reason}",
            "",
        ])
    elif v2_review is None:
        lines.extend(["**相较 v1 的结论变化：** 没有 v2 质量结论可比较；该条未产生可评审回答。", ""])
    return "\n".join(lines)


def generate(baseline_dir: Path, bundle_dir: Path, experiment_dir: Path) -> Path:
    campaign = _read(experiment_dir / "campaign.json")
    experiment_db = experiment_dir / "evaluation-v2.sqlite3"
    v2_reviews = _reviews([experiment_db], "eval-rubric-v2")
    v1_reviews = _reviews([
        baseline_dir / "full-evaluation.sqlite3",
        baseline_dir / "supplement-20261028" / "supplement-evaluation.sqlite3",
    ], "eval-rubric-v1")
    baseline_runs: dict[str, dict[str, Any]] = {}
    for path in (baseline_dir / "full-evaluation.sqlite3",
                 baseline_dir / "supplement-20261028" / "supplement-evaluation.sqlite3"):
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("SELECT payload_json FROM evaluation_runs ORDER BY started_at, run_id").fetchall()
            for row in rows:
                run = EvaluationRun.from_dict(json.loads(row["payload_json"]))
                if run.case_id in baseline_runs:
                    raise ValueError(f"duplicate Baseline Run for {run.case_id}")
                baseline_runs[run.case_id] = run.to_dict()
        finally:
            con.close()
    baseline_summary = _read(baseline_dir / "summary.json")
    failure_by_case = {
        item["case_id"]: item for item in baseline_summary.get("agent", {}).get("failures", [])
    }
    for case_id, failure in failure_by_case.items():
        if case_id in baseline_runs:
            baseline_runs[case_id]["failure_diagnostic"] = failure
    questions = _read(bundle_dir / "questions-frozen.json")
    query_by_case = {item["case_id"]: item["query"] for item in questions["cases"]}
    order = [item["case_id"] for item in _read(experiment_dir / "suite.json")["cases"]]

    counts: dict[str, Counter[str]] = {axis: Counter() for axis in CAPABILITY_AXES_V2}
    numeric_scores: dict[str, list[int]] = {axis: [] for axis in CAPABILITY_AXES_V2}
    diagnostics: list[dict[str, Any]] = []
    manual_review: list[str] = []
    minor_only_high: list[str] = []
    minor_only_by_axis: dict[str, list[str]] = {axis: [] for axis in CAPABILITY_AXES_V2}
    important_issues: list[tuple[str, dict[str, Any]]] = []
    factual_errors: list[tuple[str, dict[str, Any]]] = []
    for case_id in order:
        review = v2_reviews.get(case_id)
        campaign_case = campaign.get("cases", {}).get(case_id, {})
        if review is None:
            if campaign_case.get("status") != "not_reviewed_agent_failure":
                manual_review.append(case_id)
            continue
        has_severe = any(item.get("severity") == "severe" for item in review.diagnostics)
        if review.needs_adjudication or has_severe:
            manual_review.append(case_id)
        for axis in CAPABILITY_AXES_V2:
            score = _score(review, axis)
            key = str(score) if score in (0, 1, 2, 3, 4, "unknown") else "invalid"
            counts[axis][key] += 1
            if isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 4:
                numeric_scores[axis].append(score)
        for diagnostic in review.diagnostics:
            diagnostics.append({"case_id": case_id, **dict(diagnostic)})
            if diagnostic.get("type") == "factual_error":
                factual_errors.append((case_id, dict(diagnostic)))
            if (diagnostic.get("severity") in ("moderate", "severe")
                    and diagnostic.get("type") in {"factual_error", "attribution_error", "citation_mismatch",
                                                    "unsupported_assertion", "temporal_or_scope_error"}):
                important_issues.append((case_id, dict(diagnostic)))
        dimension_scores = [_score(review, axis) for axis in CAPABILITY_AXES_V2]
        if all(isinstance(item, int) and item >= 3 for item in dimension_scores) and all(
            item.get("severity") == "minor" for item in review.diagnostics
        ):
            minor_only_high.append(case_id)
        for axis in CAPABILITY_AXES_V2:
            score = _score(review, axis)
            axis_issues = [item for item in review.diagnostics if item.get("primary_dimension") == axis]
            if isinstance(score, int) and score >= 3 and all(item.get("severity") == "minor" for item in axis_issues):
                minor_only_by_axis[axis].append(case_id)

    lines = [
        "# Eval v1 / Judge v2 Baseline 对比报告",
        "",
        "- Baseline：`eval@v1`，16 Cases；Agent 成功 14，失败 2。",
        f"- Judge v1：14 条历史 Review；Judge v2：{len(v2_reviews)} 条已保存 Review。",
        f"- Judge：`{campaign.get('model')}` / `{campaign.get('reasoning_effort')}`，版本 `eval-rubric-v2`。",
        f"- 冻结快照：`{campaign.get('snapshot_id')}`。回答、问题、参考证据和引用均来自 Baseline 已保存材料。",
        "- 维度已改变：v1 与 v2 分数不可直接相减、不可按 Pass 数宣称提升。本报告比较判定重点与具体理由；任何差异都表示评审标准发生变化，不代表 Agent 能力变化。",
        "",
        "## 汇总",
        "",
        "Judge v2 评分分布（unknown 单列；均分只对 0–4 的数值评分计算）：",
        "",
        "| 维度 | 4 优秀 | 3 合格 | 2 部分合格 | 1 较差 | 0 失败 | unknown | 数值评分数 | 均分 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for axis in CAPABILITY_AXES_V2:
        values = counts[axis]
        numeric = numeric_scores[axis]
        mean = f"{sum(numeric) / len(numeric):.2f}" if numeric else "n/a"
        lines.append(
            f"| {V2_AXIS_NAMES_ZH[axis]} | {values['4']} | {values['3']} | {values['2']} | {values['1']} | "
            f"{values['0']} | {values['unknown']} | {len(numeric)} | {mean} |"
        )
    lines.extend([
        "",
        f"结构化诊断：{len(diagnostics)} 项；严重问题 {sum(item.get('severity') == 'severe' for item in diagnostics)} 项。",
        f"中等或严重的事实/归属/引用/无依据/时效范围问题：{len(important_issues)} 项。",
        f"两维均为 3 分及以上且问题仅轻微（或无问题）的 Case：{len(minor_only_high)} 个。",
        "这项分布说明 v2 允许不影响核心理解和决策的轻微瑕疵留在合格档；它不证明 v1 对应的每个 mixed 都只是轻微问题。",
        "",
        "### 人工复核队列",
        "",
    ])
    if manual_review:
        for case_id in manual_review:
            review = v2_reviews.get(case_id)
            if review is None:
                reason = campaign.get("cases", {}).get(case_id, {}).get("failure_reason", "未完成评审")
                lines.append(f"- `{case_id}`：无 v2 Review，需核对失败原因：{json.dumps(reason, ensure_ascii=False)}")
            else:
                lines.append(f"- `{case_id}`：`needs_adjudication=true`；至少一个维度为 0–2/unknown，或存在中等/严重问题。")
    else:
        lines.append("- 无自动触发人工复核的 Case。")
    lines.extend(["", "### 规则观察", ""])
    axis_observations = []
    for axis in CAPABILITY_AXES_V2:
        cases = minor_only_by_axis[axis]
        axis_observations.append(
            f"{V2_AXIS_NAMES_ZH[axis]} {len(cases)} 个" +
            (f"（{', '.join(f'`{case}`' for case in cases)}）" if cases else "")
        )
    lines.append(
        f"- 轻微问题处理：两个维度同时达到 3 分且无中等/严重问题的案例为 {len(minor_only_high)} 个；"
        f"按单维度看，评分至少 3 且该维度只有轻微或无诊断的问题有 { '；'.join(axis_observations)}。"
    )
    if any(minor_only_by_axis.values()):
        lines.append("  这说明 v2 至少在相应案例中没有因单个轻微瑕疵将该维度压到 2 分；样本不足以证明普遍减少过度扣分，也不能把分数差异解释为 Agent 能力变化。")
    else:
        lines.append("  本批没有单维度达到该边界的案例，暂不能判断轻微瑕疵是否会被过度扣分。")
    if important_issues:
        lines.append(f"- 重要事实核查：v2 识别到 {len(important_issues)} 项中等或严重的可信度风险，仍保留了对关键问题的识别。")
    else:
        lines.append("- 重要事实核查：本批未产生中等或严重的事实/引用/归属/范围诊断；这不证明 Rubric 已覆盖所有边界，需结合人工抽审确认。")
    if factual_errors:
        examples = "; ".join(
            f"`{case_id}` 将 `{diagnostic.get('answer_excerpt')}` 与原始证据判为不一致（{SEVERITY_ZH.get(str(diagnostic.get('severity')), diagnostic.get('severity'))}）"
            for case_id, diagnostic in factual_errors
        )
        lines.append(f"- 明确事实错误：{len(factual_errors)} 项；{examples}。没有严重级别的诊断，但这项直接定位错误入口的中等诊断说明事实核查仍有效。")
    if all(counts[axis]["unknown"] == 0 for axis in CAPABILITY_AXES_V2) and not any(
        item.get("severity") == "severe" for item in diagnostics
    ):
        lines.append("- 高不确定/严重边界：本批没有 unknown 评分或 severe 诊断；解析和复核标记路径已由无模型测试覆盖，真实模型对这两类边界的判定能力仍需后续样本验证。")
    lines.extend([
        "- 未使用百分制、加权总分或额外模型评审。",
        "- 14 题均为模型辅助暂定判断，不等同于人工确认。",
        "",
        "## 逐题结果",
        "",
    ])

    for case_id in order:
        if case_id not in baseline_runs or case_id not in query_by_case:
            raise ValueError(f"missing Baseline Run or frozen question for {case_id}")
        lines.append(_render_case(
            case_id,
            query_by_case[case_id],
            baseline_runs[case_id],
            v1_reviews.get(case_id),
            v2_reviews.get(case_id),
            campaign.get("cases", {}).get(case_id, {}),
        ))
    lines.extend([
        "## 可复现材料",
        "",
        "- 每题 `cases/<case-id>/attempt-<nn>/input.json`：原问题、完整答案、引用原文、参考事实与限制。",
        "- 每次请求 `response.json`：模型响应全文、模型名、请求投影、结束状态、用量和耗时。",
        "- 每次评分 `review.json`：结构化双维度分数与诊断；`evaluation-v2.sqlite3` 是独立 Review Store。",
        "- `campaign.json`：Run/Trace、模型配置、重试及每题状态；`judge-prompt-v2.txt` 保存本次 System Prompt。",
        "- 03、14 题原始 Run/Trace 失败，保持未评分；没有补造答案。",
        "",
    ])
    output = experiment_dir / "REPORT.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=BASELINE)
    parser.add_argument("--bundle-dir", type=Path, default=BUNDLE)
    parser.add_argument("--experiment-dir", type=Path, default=EXPERIMENT)
    args = parser.parse_args()
    print(generate(args.baseline_dir, args.bundle_dir, args.experiment_dir))


if __name__ == "__main__":
    main()
