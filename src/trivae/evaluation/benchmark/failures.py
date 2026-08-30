"""Benchmark acceptance-condition failure artifact。

Failure 只来自 case 的显式 acceptance condition 违反（design §8）：
required context miss、false zero-result、coverage/truncation mismatch、
target Hit@K miss、terminal failure。低 MRR / Recall<1 是质量结果，进 diagnosis
不自动成 failure。跨 Variant 归因（semantic uplift/miss）不在本模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trivae.evaluation.contracts import EvaluationContractError

from .gt import CaseGroundTruth
from .metrics import NO_RESULT_FORM, _evidence_message_ids

FAILURE_CATEGORIES = (
    "provider_failure",
    "zero_result_error",
    "coverage_error",
    "context_missing",
    "retrieval_miss",
    "not_observed_within_recorded_depth",
    "answer_generation_error",
)

# target Hit@K miss 的 acceptance K；与报告 Recall 口径一致。
ACCEPTANCE_HIT_K = 10


@dataclass(frozen=True)
class BenchmarkFailure:
    """单 case × 单 variant 的 failure artifact；expected/actual 均为 bounded 摘要。"""

    case_id: str
    variant_id: str
    run_id: str
    category: str
    expected: Mapping[str, object]
    actual: Mapping[str, object]
    trace_id: str | None
    detail: str

    def __post_init__(self) -> None:
        if self.category not in FAILURE_CATEGORIES:
            raise EvaluationContractError(f"unknown benchmark failure category: {self.category}")
        for name, value in (
            ("case_id", self.case_id),
            ("variant_id", self.variant_id),
            ("run_id", self.run_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise EvaluationContractError(f"benchmark failure {name} must be a non-empty string")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise EvaluationContractError("benchmark failure detail must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "variant_id": self.variant_id,
            "run_id": self.run_id,
            "category": self.category,
            "expected": dict(self.expected),
            "actual": dict(self.actual),
            "trace_id": self.trace_id,
            "detail": self.detail,
        }


def _recorded_direct_hits(run_query_result: Mapping[str, object]) -> tuple[list[str], bool]:
    """返回 (按 rank 排序的全部 recorded direct hit IDs, 是否所有 call 完整落盘)。"""

    projection = run_query_result.get("retrieval_calls")
    if not isinstance(projection, Mapping):
        return [], True
    calls = projection.get("calls")
    if not isinstance(calls, list):
        return [], True
    ranked: list[tuple[int, str]] = []
    complete = True
    for call in calls:
        if not isinstance(call, Mapping):
            continue
        if call.get("omitted_direct_ids", 0) or call.get("omitted_expanded_ids", 0) or (
            isinstance(projection.get("omitted"), int) and projection.get("omitted", 0) > 0
        ):
            complete = False
        for hit in call.get("direct_hits", ()):
            if isinstance(hit, Mapping):
                rank = hit.get("rank")
                message_id = hit.get("internal_message_id")
                if isinstance(rank, int) and isinstance(message_id, str):
                    ranked.append((rank, message_id))
    ranked.sort()
    return [message_id for _, message_id in ranked], complete


def evaluate_case_failure(
    gt: CaseGroundTruth,
    *,
    variant_id: str,
    run_id: str,
    run_query_result: Mapping[str, object] | None,
    trace_id: str | None,
) -> BenchmarkFailure | None:
    """按 acceptance condition 链返回第一个命中的 failure；无违反返回 None。"""

    if run_query_result is None:
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="provider_failure",
            expected={"terminal": "completed"},
            actual={"terminal": "exception"},
            trace_id=trace_id,
            detail="query executor raised before returning a QueryResult",
        )

    terminal = run_query_result.get("terminal")
    actual: dict[str, object] = {"terminal": terminal, "answer_form": run_query_result.get("answer_form")}

    # 1. terminal failure：provider/runtime/aborted。
    if terminal != "completed":
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="provider_failure",
            expected={"terminal": "completed"},
            actual=actual,
            trace_id=trace_id,
            detail=f"run terminated with {terminal}",
        )

    # 2. false zero-result：GT 存在相关消息却输出 no_result 形态。
    if gt.expected_zero_result is False and run_query_result.get("answer_form") == NO_RESULT_FORM:
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="zero_result_error",
            expected={"zero_result": False, "relevant_count": len(gt.relevant_message_ids)},
            actual=actual,
            trace_id=trace_id,
            detail="answer claimed no results while GT declares relevant messages",
        )

    # 3. coverage / truncation mismatch（GT 有声明时）。
    if gt.expected_coverage_status is not None:
        retrieval_coverage = run_query_result.get("retrieval_coverage")
        if run_query_result.get("answer_form") == NO_RESULT_FORM:
            pass  # coverage 轴对 no_result 不适用，由 zero-result 轴承载。
        elif isinstance(retrieval_coverage, Mapping):
            status = retrieval_coverage.get("status")
            if status != gt.expected_coverage_status:
                return BenchmarkFailure(
                    case_id=gt.case_id,
                    variant_id=variant_id,
                    run_id=run_id,
                    category="coverage_error",
                    expected={"coverage_status": gt.expected_coverage_status},
                    actual={**actual, "coverage_status": status},
                    trace_id=trace_id,
                    detail="artifact coverage status does not match GT expectation",
                )
        else:
            return BenchmarkFailure(
                case_id=gt.case_id,
                variant_id=variant_id,
                run_id=run_id,
                category="coverage_error",
                expected={"coverage_status": gt.expected_coverage_status},
                actual={**actual, "coverage_status": None},
                trace_id=trace_id,
                detail="artifact coverage unavailable while GT declares an expectation",
            )

    # 4. required context miss。
    if gt.required_context_message_ids:
        evidence_ids = set(_evidence_message_ids(run_query_result))
        missing = [message_id for message_id in gt.required_context_message_ids if message_id not in evidence_ids]
        if missing:
            return BenchmarkFailure(
                case_id=gt.case_id,
                variant_id=variant_id,
                run_id=run_id,
                category="context_missing",
                expected={"required_context": list(gt.required_context_message_ids)},
                actual={**actual, "missing_context": missing},
                trace_id=trace_id,
                detail=f"{len(missing)} required context message(s) missing from final evidence",
            )

    # 5. target Hit@K miss：recorded direct hits 内前 K 全 miss。
    if gt.has_relevant:
        ranked_hits, complete = _recorded_direct_hits(run_query_result)
        top = ranked_hits[:ACCEPTANCE_HIT_K]
        if not any(message_id in set(gt.relevant_message_ids) for message_id in top):
            if not complete:
                return BenchmarkFailure(
                    case_id=gt.case_id,
                    variant_id=variant_id,
                    run_id=run_id,
                    category="not_observed_within_recorded_depth",
                    expected={"hit_at_k": ACCEPTANCE_HIT_K},
                    actual={**actual, "recorded_direct_hits": len(ranked_hits)},
                    trace_id=trace_id,
                    detail="relevant messages not observed within recorded depth; ranking beyond depth was omitted",
                )
            return BenchmarkFailure(
                case_id=gt.case_id,
                variant_id=variant_id,
                run_id=run_id,
                category="retrieval_miss",
                expected={"hit_at_k": ACCEPTANCE_HIT_K, "relevant_count": len(gt.relevant_message_ids)},
                actual={**actual, "recorded_direct_hits": len(ranked_hits)},
                trace_id=trace_id,
                detail="no GT relevant message appears in the recorded direct hits",
            )

    # 6. 其余：answer generation 层违反（如 claims 无 citation 的明文答案）目前不自动判失败，
    # 交给 Tier 2 judge 与人工 review；这里保持 acceptance 列表最小化。
    return None
