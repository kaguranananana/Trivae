"""Benchmark Tier 1 deterministic 指标引擎。

输入是现有 contract 的产出物：``CaseGroundTruth``（gt.py 解析的 ReferenceFinding 视图）、
module-level ``RetrievalRunRecord``（现有 RetrievalAnnotationWorkflow 执行路径）、以及
``EvaluationRun.query_result`` 的 bounded projection（checks.py 落盘）。

硬规则（design §4.2 / prd R4）：
- Provider/runtime failure 不进入条件指标分母；报告必须同时给出无条件 completion rates。
- GT completeness 决定 scope：exhaustive→corpus；其余→target；unknown→unavailable。
- Coverage actual 只读 Host-owned ``AnswerArtifact.retrieval_coverage``；unavailable 即
  指标 unavailable，禁止在本模块从 retrieval_calls 重算 production coverage。
- 不把 incomplete coverage 算成正确；citation 存在不等于 citation 正确（后者属 Tier 2）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from trivae.evaluation.contracts import EvaluationContractError
from trivae.evaluation.retrieval_evaluation import RetrievalRunRecord

from .gt import CaseGroundTruth

MetricAvailability = Literal["available", "not_applicable", "unavailable"]

DEFAULT_RECALL_KS = (5, 10)
DEFAULT_MRR_K = 10

# Answer Artifact 的 no_result 确定性形态标签（checks.py 落盘的 answer_form）。
NO_RESULT_FORM = "no_result_signature"
CLAIMS_FORM = "claims"


@dataclass(frozen=True)
class MetricOutcome:
    """单 case × 单指标的可复现事实；value 只在 available 时有数值。"""

    name: str
    k: int | None
    scope: str
    denominator: int
    hits: float | None
    value: float | None
    availability: MetricAvailability
    reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "k": self.k,
            "scope": self.scope,
            "denominator": self.denominator,
            "hits": self.hits,
            "value": self.value,
            "availability": self.availability,
            "reason": self.reason,
        }


def _available(name: str, *, k: int | None, scope: str, denominator: int, hits: float) -> MetricOutcome:
    value = hits / denominator if denominator else None
    if value is None or not math.isfinite(value):
        raise EvaluationContractError(f"metric {name} produced a non-finite value")
    return MetricOutcome(name, k, scope, denominator, hits, value, "available", None)


def _unavailable(
    name: str, *, k: int | None, scope: str, reason: str
) -> MetricOutcome:
    return MetricOutcome(name, k, scope, 0, None, None, "unavailable", reason)


def _not_applicable(name: str, *, k: int | None, scope: str, reason: str) -> MetricOutcome:
    return MetricOutcome(name, k, scope, 0, None, None, "not_applicable", reason)


def _normalize_text(value: str) -> str:
    """expected-fact 匹配的规范化：去空白、小写；不做更激进的归一化。"""

    return "".join(value.split()).lower()


def score_ranking(
    gt: CaseGroundTruth,
    ranked_ids: Sequence[str],
    *,
    ks: Sequence[int] = DEFAULT_RECALL_KS,
    mrr_k: int = DEFAULT_MRR_K,
    strategy_scope_suffix: str = "",
) -> list[MetricOutcome]:
    """module-level 完整 tool-returned ranking 的 Recall@K / Hit@K / MRR@K。

    scope 由 GT completeness 决定：exhaustive→corpus；partial→target；
    unknown / 无 relevant→unavailable。cutoff 显式携带在 k 上，不宣称全库排序。
    """

    prefix = f"{strategy_scope_suffix}:" if strategy_scope_suffix else ""
    if gt.completeness == "unknown" or not gt.has_relevant:
        unavailable_outcomes = [
            _unavailable(f"{prefix}recall_at_k", k=k, scope=gt.recall_scope, reason="gt_not_exhaustive_or_no_relevant")
            for k in ks
        ]
        unavailable_outcomes.append(
            _unavailable(f"{prefix}hit_at_k", k=ks[0] if ks else None, scope=gt.recall_scope, reason="gt_not_exhaustive_or_no_relevant")
        )
        unavailable_outcomes.append(
            _unavailable(f"{prefix}mrr_at_k", k=mrr_k, scope=gt.recall_scope, reason="gt_not_exhaustive_or_no_relevant")
        )
        return unavailable_outcomes

    relevant = set(gt.relevant_message_ids)
    seen: set[str] = set()
    deduped: list[str] = []
    for message_id in ranked_ids:
        if message_id not in seen:
            seen.add(message_id)
            deduped.append(message_id)

    outcomes: list[MetricOutcome] = []
    for k in ks:
        top = deduped[:k]
        hits = sum(1 for message_id in top if message_id in relevant)
        outcomes.append(_available(f"{prefix}recall_at_k", k=k, scope=gt.recall_scope, denominator=len(relevant), hits=hits))
        outcomes.append(
            _available(
                f"{prefix}hit_at_k",
                k=k,
                scope=gt.recall_scope,
                denominator=1,
                hits=1.0 if hits > 0 else 0.0,
            )
        )
    first_rank = next(
        (rank for rank, message_id in enumerate(deduped[:mrr_k], start=1) if message_id in relevant),
        None,
    )
    outcomes.append(
        _available(
            f"{prefix}mrr_at_k",
            k=mrr_k,
            scope=gt.recall_scope,
            denominator=1,
            hits=0.0 if first_rank is None else 1.0 / first_rank,
        )
    )
    return outcomes


def score_expansion(
    gt: CaseGroundTruth,
    expanded_ids: Sequence[str],
    *,
    strategy_scope_suffix: str = "",
) -> MetricOutcome:
    """module-level context expansion 的 retrieval 侧 context recovery（case 级布尔）。"""

    prefix = f"{strategy_scope_suffix}:" if strategy_scope_suffix else ""
    if not gt.required_context_message_ids:
        return _not_applicable(
            f"{prefix}context_recovery", k=None, scope="retrieval_expansion", reason="no_required_context_declared"
        )
    covered = set(expanded_ids)
    hits = sum(1 for message_id in gt.required_context_message_ids if message_id in covered)
    return _available(
        f"{prefix}context_recovery",
        k=None,
        scope="retrieval_expansion",
        denominator=len(gt.required_context_message_ids),
        hits=float(hits),
    )


def _evidence_message_ids(run_query_result: Mapping[str, object]) -> tuple[str, ...]:
    """从 run projection 的 evidence_sources 抽取去重 evidence message IDs。"""

    projection = run_query_result.get("evidence_sources")
    if not isinstance(projection, Mapping):
        return ()
    sources = projection.get("sources")
    if not isinstance(sources, Sequence) or isinstance(sources, str):
        return ()
    ids: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for message_id in source.get("message_ids", ()):
            if isinstance(message_id, str) and message_id not in ids:
                ids.append(message_id)
    return tuple(ids)


def _answer_fact_hits(gt: CaseGroundTruth, answer_text: str | None) -> tuple[int, int] | None:
    """Expected Fact Answer Coverage 的确定性匹配：alias 必须命中 answer_text。"""

    if not gt.expected_facts:
        return None
    if answer_text is None:
        return None
    normalized = _normalize_text(answer_text)
    hits = sum(1 for aliases in gt.expected_facts if any(alias in normalized for alias in aliases))
    return hits, len(gt.expected_facts)


def evaluate_end_to_end_case(
    gt: CaseGroundTruth,
    run_query_result: Mapping[str, object] | None,
    *,
    operational_measurements: Mapping[str, object] | None = None,
    ks: Sequence[int] = DEFAULT_RECALL_KS,
) -> dict[str, object]:
    """从单次 end-to-end Run projection 计算 case 级 Tier 1 指标。

    ``run_query_result`` 是 ``EvaluationRun.query_result``（checks.py 的 bounded
    projection）；terminal 异常的 run 只产出无条件事实，条件指标显式 unavailable。
    """

    if run_query_result is None:
        return {
            "case_id": gt.case_id,
            "run_status": "exception",
            "metrics": [],
            "flags": {},
        }
    terminal = run_query_result.get("termination")
    is_successful = run_query_result.get("is_successful") is True
    answer_form = run_query_result.get("answer_form")
    answer_text = run_query_result.get("answer_text")
    retrieval_coverage = run_query_result.get("retrieval_coverage")
    completed = terminal == "completed"

    metrics: list[MetricOutcome] = []

    # 无条件指标：不分 provider failure 与否，全部 run 都计入。
    metrics.append(
        MetricOutcome(
            "execution_completed",
            None,
            "unconditional",
            1,
            1.0 if completed else 0.0,
            1.0 if completed else 0.0,
            "available",
            None,
        )
    )
    metrics.append(
        MetricOutcome(
            "valid_answer",
            None,
            "unconditional",
            1,
            1.0 if is_successful else 0.0,
            1.0 if is_successful else 0.0,
            "available",
            None,
        )
    )

    flags: dict[str, object] = {"answer_form": answer_form}

    if not completed:
        # 条件指标分母剔除 provider/runtime failure；原因显式保留。
        reason = f"run_not_completed:{terminal}"
        metrics.extend(
            [
                _unavailable("evidence_recall", k=None, scope="evidence", reason=reason),
                _unavailable("context_recovery", k=None, scope="evidence", reason=reason),
                _unavailable("expected_fact_answer_coverage", k=None, scope="answer", reason=reason),
                _unavailable("false_zero_result", k=None, scope="failure", reason=reason),
                _unavailable("verified_zero_result", k=None, scope="failure", reason=reason),
            ]
        )
        return {
            "case_id": gt.case_id,
            "run_status": str(terminal),
            "metrics": [item.to_dict() for item in metrics],
            "flags": flags,
        }

    # Evidence Recall / Context Recovery：evidence 层 vs GT 目标集合。
    target_ids = gt.evidence_target_ids
    if target_ids:
        evidence_ids = _evidence_message_ids(run_query_result)
        hits = sum(1 for message_id in target_ids if message_id in evidence_ids)
        metrics.append(
            _available("evidence_recall", k=None, scope="evidence", denominator=len(target_ids), hits=float(hits))
        )
        if gt.required_context_message_ids:
            context_hits = sum(
                1 for message_id in gt.required_context_message_ids if message_id in evidence_ids
            )
            metrics.append(
                _available(
                    "context_recovery",
                    k=None,
                    scope="evidence",
                    denominator=len(gt.required_context_message_ids),
                    hits=float(context_hits),
                )
            )
        else:
            metrics.append(
                _not_applicable("context_recovery", k=None, scope="evidence", reason="no_required_context_declared")
            )
    else:
        metrics.append(_unavailable("evidence_recall", k=None, scope="evidence", reason="no_gt_targets"))
        metrics.append(_not_applicable("context_recovery", k=None, scope="evidence", reason="no_required_context_declared"))

    # Coverage Status Accuracy：actual 只读 Host-owned artifact.retrieval_coverage。
    if gt.expected_coverage_status is None:
        metrics.append(_not_applicable("coverage_status_accuracy", k=None, scope="coverage", reason="no_expected_declared"))
    else:
        actual_status: str | None = None
        if answer_form == NO_RESULT_FORM:
            # no_result 形态没有 recent coverage 事实；该 case 的 coverage 轴交给 zero-result 轴。
            actual_status = None
        elif isinstance(retrieval_coverage, Mapping):
            status = retrieval_coverage.get("status")
            if isinstance(status, str):
                actual_status = status
        if actual_status is None:
            metrics.append(
                _unavailable(
                    "coverage_status_accuracy",
                    k=None,
                    scope="coverage",
                    reason="artifact_coverage_unavailable",
                )
            )
        else:
            metrics.append(
                MetricOutcome(
                    "coverage_status_accuracy",
                    None,
                    "coverage",
                    1,
                    1.0 if actual_status == gt.expected_coverage_status else 0.0,
                    1.0 if actual_status == gt.expected_coverage_status else 0.0,
                    "available",
                    None,
                )
            )
        flags["actual_coverage_status"] = actual_status

    # Truncation Accuracy：actual 来自 run 级 Host 派生 limitation 事实。
    if gt.expected_truncated is None:
        metrics.append(_not_applicable("truncation_accuracy", k=None, scope="coverage", reason="no_expected_declared"))
    else:
        limitations: Sequence[str] = ()
        if operational_measurements is not None:
            raw = operational_measurements.get("trace_limitations")
            if isinstance(raw, Sequence) and not isinstance(raw, str):
                limitations = tuple(item for item in raw if isinstance(item, str))
        actual_truncated = any(item in ("truncated", "retrieval_truncated") for item in limitations)
        metrics.append(
            MetricOutcome(
                "truncation_accuracy",
                None,
                "coverage",
                1,
                1.0 if actual_truncated == gt.expected_truncated else 0.0,
                1.0 if actual_truncated == gt.expected_truncated else 0.0,
                "available",
                None,
            )
        )
        flags["actual_truncated"] = actual_truncated

    # Expected Fact Answer Coverage：alias 必须命中 answer_text；evidence 含有不算。
    fact_hits = _answer_fact_hits(gt, answer_text if isinstance(answer_text, str) else None)
    if fact_hits is None:
        metrics.append(
            _not_applicable(
                "expected_fact_answer_coverage",
                k=None,
                scope="answer",
                reason="no_answer_text" if answer_text is None else "no_expected_facts",
            )
        )
    else:
        hits, denominator = fact_hits
        metrics.append(_available("expected_fact_answer_coverage", k=None, scope="answer", denominator=denominator, hits=float(hits)))

    # Zero-result 轴：expected_zero_result=false 的正例看 False；=true 的负例看 Verified。
    if gt.expected_zero_result is False:
        metrics.append(
            MetricOutcome(
                "false_zero_result",
                None,
                "failure",
                1,
                0.0 if answer_form == NO_RESULT_FORM else 1.0,
                0.0 if answer_form == NO_RESULT_FORM else 1.0,
                "available",
                None,
            )
        )
    elif gt.expected_zero_result is True:
        metrics.append(
            MetricOutcome(
                "verified_zero_result",
                None,
                "failure",
                1,
                1.0 if answer_form == NO_RESULT_FORM else 0.0,
                1.0 if answer_form == NO_RESULT_FORM else 0.0,
                "available",
                None,
            )
        )
    else:
        metrics.append(_not_applicable("false_zero_result", k=None, scope="failure", reason="expected_zero_result_undeclared"))
        metrics.append(_not_applicable("verified_zero_result", k=None, scope="failure", reason="expected_zero_result_undeclared"))

    return {
        "case_id": gt.case_id,
        "run_status": str(terminal),
        "metrics": [item.to_dict() for item in metrics],
        "flags": flags,
    }


def aggregate_metric_outcomes(
    outcomes: Sequence[MetricOutcome],
) -> dict[str, object]:
    """同名同 scope 同 k 的 metric 做 macro 聚合；not_applicable 不进分母。"""

    grouped: dict[tuple[str, int | None, str], list[MetricOutcome]] = {}
    for outcome in outcomes:
        grouped.setdefault((outcome.name, outcome.k, outcome.scope), []).append(outcome)
    aggregates: list[dict[str, object]] = []
    for (name, k, scope), items in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])):
        scored = [item for item in items if item.availability == "available"]
        unavailable_reasons = sorted(
            {item.reason for item in items if item.availability == "unavailable" and item.reason}
        )
        not_applicable = sum(1 for item in items if item.availability == "not_applicable")
        hits = sum(float(item.hits) for item in scored if item.hits is not None)
        denominator = len(scored)
        aggregates.append(
            {
                "name": name,
                "k": k,
                "scope": scope,
                "n": denominator,
                "hits": hits,
                "value": hits / denominator if denominator else None,
                "not_applicable_count": not_applicable,
                "unavailable_count": len(items) - denominator - not_applicable,
                "unavailable_reasons": unavailable_reasons,
            }
        )
    return {"metrics": aggregates}


def retrieval_run_record_rankings(
    record: RetrievalRunRecord,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """从 sealed packet 的 RetrievalRunRecord 读取 (strategy, ranked, expanded)。"""

    if not isinstance(record, RetrievalRunRecord):
        raise EvaluationContractError("retrieval ranking scoring requires RetrievalRunRecord")
    return record.strategy, record.ranked_candidate_ids, record.expanded_message_ids
