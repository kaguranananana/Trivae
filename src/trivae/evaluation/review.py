"""Review、blind paired comparison 和显式 Failure Diagnosis。"""

from __future__ import annotations

import random
import uuid
from dataclasses import replace
from typing import Mapping, Protocol

from trivae.query.contracts import QueryResult
from trivae.query.evidence import MessageSource, StructuredSource

from .contracts import (
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationReview,
    EvaluationRun,
    FailureDiagnosis,
    PairedComparison,
    ReferenceRelation,
    ReviewPacket,
)
from .variant import ControlledVariant, variant_diff

QUALITY_AXES = (
    "task_finding_correctness",
    "evidence_completeness",
    "groundedness_entailment",
    "uncertainty_calibration",
    "answer_relevance",
)


def _source_projection(reference: object, relation: ReferenceRelation) -> dict[str, object]:
    """只投影选中的 Source locator 和 bounded trusted snapshot 到 review packet。"""

    if isinstance(reference, MessageSource):
        snapshot = reference.snapshot
        return {
            "type": "message",
            "relation": relation,
            "tool_result_id": reference.tool_result_id,
            "result_item_id": reference.result_item_id,
            "session_id": reference.session_id,
            "internal_message_id": reference.internal_message_id,
            "snapshot": None
            if snapshot is None
            else {
                "session_display": snapshot.session_display,
                "author_display": snapshot.author_display,
                "timestamp_ms": snapshot.timestamp_ms,
                "excerpt": snapshot.excerpt,
                "excerpt_truncated": snapshot.excerpt_truncated,
            },
        }
    if isinstance(reference, StructuredSource):
        return {
            "type": "structured",
            "relation": relation,
            "tool_result_id": reference.tool_result_id,
            "locator_kind": reference.locator_kind,
            "locator": reference.locator,
            "value_snapshot": reference.value_snapshot,
            "query_scope_snapshot": reference.query_scope_snapshot,
            "execution_limitations": list(reference.execution_limitations),
        }
    raise EvaluationContractError("review source is not a supported Evidence source")


def build_review_packet(
    *,
    run: EvaluationRun,
    query: str,
    result: QueryResult | None,
    rubric_version: str,
) -> ReviewPacket:
    """从已完成 Query 生成最小必要人工复核输入，不读取完整 Trace。"""

    selected_sources: list[Mapping[str, object]] = []
    limitations: list[str] = []
    answer_text: str | None = None
    if result is not None and result.answer_artifact is not None:
        artifact = result.answer_artifact
        answer_text = artifact.answer_text
        limitations.extend(artifact.limitations)
        for evidence in artifact.evidence_items:
            for source in evidence.sources:
                selected_sources.append(_source_projection(source.reference, source.relation))
    if result is not None:
        for record in result.runtime_result.tool_results:
            limitations.extend(record.limitations)
    return ReviewPacket(
        packet_id=f"review-packet:{run.run_id}",
        run_id=run.run_id,
        query=query,
        answer_text=answer_text,
        selected_sources=tuple(selected_sources),
        rubric_version=rubric_version,
        visible_limitations=tuple(dict.fromkeys(limitations)),
    )


class JudgeAdapter(Protocol):
    """离线 Judge 端口；实现不能修改在线 QueryResult。"""

    async def review(self, packet: ReviewPacket) -> EvaluationReview:
        """对最小 Review Packet 返回结构化质量轴判断。"""


async def run_judge(
    adapter: JudgeAdapter,
    packet: ReviewPacket,
    *,
    review_id: str | None = None,
) -> EvaluationReview:
    """调用离线 Judge；异常继续向上暴露，不把失败包装成质量通过。"""

    if not callable(getattr(adapter, "review", None)):
        raise EvaluationContractError("JudgeAdapter must provide review(packet)")
    review = await adapter.review(packet)
    if not isinstance(review, EvaluationReview):
        raise EvaluationContractError("JudgeAdapter returned an invalid EvaluationReview")
    if review.run_id != packet.run_id:
        raise EvaluationContractError("Judge review run_id does not match Review Packet")
    if review_id is not None and review.review_id != review_id:
        raise EvaluationContractError("Judge review identity does not match requested review_id")
    return review


def create_paired_comparison(
    *,
    case: EvaluationCaseBundle,
    baseline_variant: ControlledVariant,
    candidate_variant: ControlledVariant,
    baseline_runs: tuple[EvaluationRun, ...],
    candidate_runs: tuple[EvaluationRun, ...],
    randomization_seed: str | None = None,
) -> PairedComparison:
    """验证配对条件后生成 blind A/B identity；质量判断前不暴露 Variant 标签。"""

    if not baseline_runs or not candidate_runs:
        raise EvaluationContractError("paired comparison requires baseline and candidate Runs")
    if len(baseline_runs) != len(candidate_runs):
        raise EvaluationContractError("paired comparison requires equal repetition counts")
    all_runs = (*baseline_runs, *candidate_runs)
    for run in all_runs:
        if run.case_id != case.case_id or run.case_version != case.version:
            raise EvaluationContractError("paired comparison requires the same Case version")
        if run.snapshot_id != case.dataset_snapshot.snapshot_id:
            raise EvaluationContractError("paired comparison requires the same Dataset Snapshot")
        if run.scope_identity != baseline_runs[0].scope_identity:
            raise EvaluationContractError("paired comparison requires the same Data Access Scope")
    if baseline_runs[0].scope_identity != candidate_runs[0].scope_identity:
        raise EvaluationContractError("baseline and candidate Scope identities differ")
    if any(run.variant_id != baseline_variant.variant_id for run in baseline_runs):
        raise EvaluationContractError("baseline Run variant identity does not match Baseline Variant")
    if any(run.variant_id != candidate_variant.variant_id for run in candidate_runs):
        raise EvaluationContractError("candidate Run variant identity does not match Candidate Variant")
    seed = randomization_seed or f"randomization:{uuid.uuid4().hex}"
    rng = random.Random(seed)
    baseline_first = rng.choice((True, False))
    assignment = (
        {"A": baseline_variant.variant_id, "B": candidate_variant.variant_id}
        if baseline_first
        else {"A": candidate_variant.variant_id, "B": baseline_variant.variant_id}
    )
    return PairedComparison(
        comparison_id=f"comparison:{case.case_id}:v{case.version}:{uuid.uuid4().hex}",
        case_id=case.case_id,
        case_version=case.version,
        snapshot_id=case.dataset_snapshot.snapshot_id,
        scope_identity=baseline_runs[0].scope_identity,
        baseline_variant_id=baseline_variant.variant_id,
        candidate_variant_id=candidate_variant.variant_id,
        baseline_run_ids=tuple(run.run_id for run in baseline_runs),
        candidate_run_ids=tuple(run.run_id for run in candidate_runs),
        variant_diff=variant_diff(baseline_variant, candidate_variant),
        randomization_seed=seed,
        blind_order=("A", "B") if baseline_first else ("B", "A"),
        blind_assignment=assignment,
    )


def add_operational_diff(
    comparison: PairedComparison,
    *,
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
) -> PairedComparison:
    """在质量 Review 后追加 operational diff；不改变 blind quality identity。"""

    return replace(
        comparison,
        status="reviewed",
        operational_diff={"baseline": dict(baseline), "candidate": dict(candidate)},
    )


def create_failure_diagnosis(
    *,
    run_id: str,
    primary_cause: str,
    contributing_factors: tuple[str, ...],
    evidence_references: tuple[str, ...],
    trace_event_references: tuple[str, ...],
    confidence: float | None,
    status: str,
    notes: str | None = None,
) -> FailureDiagnosis:
    """只接受显式证据的后验 Diagnosis，不自动猜测 root cause。"""

    if status == "confirmed" and (not evidence_references or not trace_event_references):
        raise EvaluationContractError("confirmed diagnosis requires evidence and Trace references")
    return FailureDiagnosis(
        diagnosis_id=f"diagnosis:{run_id}:{uuid.uuid4().hex}",
        run_id=run_id,
        primary_cause=primary_cause,  # type: ignore[arg-type]
        contributing_factors=contributing_factors,
        evidence_references=evidence_references,
        trace_event_references=trace_event_references,
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        notes=notes,
    )


# 这些是 M6 已记录 Failure 的回归映射，不自动代表每一项都是昂贵 E2E Case。
M6_FAILURE_REGRESSION_MAP: Mapping[str, Mapping[str, object]] = {
    "failure_a_deepseek_trusted_limit": {
        "layer": "contract_regression",
        "owner": "tool_contract",
        "failure": "INVALID_ARGUMENT",
        "requirement": "provider schema exposes trusted maximum; legal input succeeds and illegal input remains rejected",
    },
    "failure_b_mixed_provenance": {
        "layer": "contract_regression",
        "owner": "citation",
        "failure": "UNRESOLVED_MESSAGE_SOURCE",
        "requirement": "self-contained provenance succeeds; mixed locator remains rejected",
    },
    "failure_c_router_degraded": {"layer": "integration_regression", "owner": "router"},
    "failure_c_planner_failed_continue": {"layer": "integration_regression", "owner": "planner"},
    "failure_c_tool_contract_error": {"layer": "contract_regression", "owner": "tool_contract"},
    "failure_c_retrieval_partial_unavailable": {"layer": "integration_regression", "owner": "retrieval"},
    "failure_c_citation_failure": {"layer": "integration_regression", "owner": "citation"},
    "failure_c_conversation_commit_failure": {"layer": "integration_regression", "owner": "conversation_commit"},
    "failure_c_missing_trace_terminal": {"layer": "contract_regression", "owner": "evaluation_infrastructure"},
    "failure_c_trace_store_failure": {"layer": "integration_regression", "owner": "evaluation_infrastructure"},
    "failure_c_privacy_redaction": {"layer": "contract_regression", "owner": "evaluation_infrastructure"},
}
