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
    "ranking_failure",
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


@dataclass(frozen=True)
class _DirectHitObservation:
    """单个检索 call 中保留下来的 direct hit 观测。"""

    tool_call_id: str
    strategy: str
    rank: int
    message_id: str


@dataclass(frozen=True)
class _DirectHitAudit:
    """供 failure 分类消费的 bounded direct-hit 观测摘要。"""

    observations: tuple[_DirectHitObservation, ...]
    hit_at_k_observable: bool
    ignored_context_calls: int


def _recorded_direct_hits(run_query_result: Mapping[str, object]) -> _DirectHitAudit:
    """保留每个检索 call 的 rank，并判断 Hit@K 是否仍可由投影确定。"""

    projection = run_query_result.get("retrieval_calls")
    if not isinstance(projection, Mapping):
        return _DirectHitAudit((), True, 0)
    calls = projection.get("calls")
    if not isinstance(calls, list):
        return _DirectHitAudit((), True, 0)

    observations: list[_DirectHitObservation] = []
    hit_at_k_observable = not (
        isinstance(projection.get("omitted"), int) and projection.get("omitted", 0) > 0
    )
    ignored_context_calls = 0
    for call in calls:
        if not isinstance(call, Mapping):
            continue

        # Context Expansion 是检索后的第二个动作，不是独立的 ranking surface；
        # 把它排除，避免“显式恢复到的消息”伪装成搜索结果排名。
        strategy = call.get("strategy")
        if strategy == "context":
            ignored_context_calls += 1
            continue
        if not isinstance(strategy, str):
            continue

        direct_hits = call.get("direct_hits", ())
        if not isinstance(direct_hits, list):
            direct_hits = []
        omitted_direct_ids = call.get("omitted_direct_ids", 0)
        # 只有 top-K 本身被截断时才会影响 Hit@K；K 之后的 bounded omission
        # 不会让已经记录的 top-K 变成未知。
        if (
            isinstance(omitted_direct_ids, int)
            and omitted_direct_ids > 0
            and len(direct_hits) < ACCEPTANCE_HIT_K
        ):
            hit_at_k_observable = False

        tool_call_id = call.get("tool_call_id")
        bounded_tool_call_id = tool_call_id if isinstance(tool_call_id, str) else ""
        for hit in direct_hits:
            if isinstance(hit, Mapping):
                rank = hit.get("rank")
                message_id = hit.get("internal_message_id")
                if isinstance(rank, int) and isinstance(message_id, str):
                    observations.append(
                        _DirectHitObservation(
                            tool_call_id=bounded_tool_call_id,
                            strategy=strategy,
                            rank=rank,
                            message_id=message_id,
                        )
                    )
    return _DirectHitAudit(tuple(observations), hit_at_k_observable, ignored_context_calls)


def _observed_relevant_hits(
    audit: _DirectHitAudit,
    relevant_message_ids: tuple[str, ...],
) -> list[dict[str, object]]:
    """返回 GT relevant 的 bounded rank 观测，保留 tool 与 strategy 归因。"""

    relevant = set(relevant_message_ids)
    return [
        {
            "internal_message_id": observation.message_id,
            "rank": observation.rank,
            "strategy": observation.strategy,
            "tool_call_id": observation.tool_call_id,
        }
        for observation in audit.observations
        if observation.message_id in relevant
    ]


def _has_relevant_hit_at_k(
    audit: _DirectHitAudit,
    relevant_message_ids: tuple[str, ...],
) -> bool:
    """按单个 direct-search call 的局部 rank 判断是否命中 Hit@K。"""

    relevant = set(relevant_message_ids)
    return any(
        observation.message_id in relevant and observation.rank <= ACCEPTANCE_HIT_K
        for observation in audit.observations
    )


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
            expected={"termination": "completed"},
            actual={"termination": "exception"},
            trace_id=trace_id,
            detail="query executor raised before returning a QueryResult",
        )

    terminal = run_query_result.get("termination")
    actual: dict[str, object] = {"termination": terminal, "answer_form": run_query_result.get("answer_form")}

    # 1. terminal failure：provider/runtime/aborted。
    if terminal != "completed":
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="provider_failure",
            expected={"termination": "completed"},
            actual=actual,
            trace_id=trace_id,
            detail=f"run terminated with {terminal}",
        )

    # Runtime completed 仍可能在 Answer/Citation Finalizer 失败；这属于答案生成边界，
    # 必须先于 coverage 检查归类，避免把“没有 artifact”误报为 coverage mismatch。
    finalization_error = run_query_result.get("finalization_error")
    if isinstance(finalization_error, Mapping) or run_query_result.get("finalization_status") == "failed":
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="answer_generation_error",
            expected={"answer_artifact": "present"},
            actual={
                **actual,
                "finalization_status": run_query_result.get("finalization_status"),
                "finalization_error": dict(finalization_error)
                if isinstance(finalization_error, Mapping)
                else None,
            },
            trace_id=trace_id,
            detail="answer finalization did not produce a valid AnswerArtifact",
        )

    # 2. false zero-result：GT 存在相关消息却输出 no_result 形态。
    if gt.expected_zero_result is False and run_query_result.get("answer_form") == NO_RESULT_FORM:
        return BenchmarkFailure(
            case_id=gt.case_id,
            variant_id=variant_id,
            run_id=run_id,
            category="zero_result_error",
            expected={
                "zero_result": False,
                "expected_non_empty": True,
                "relevant_count": len(gt.relevant_message_ids),
            },
            actual=actual,
            trace_id=trace_id,
            detail="answer claimed no results while GT requires a non-empty result",
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

    # 5. target Hit@K miss：按每个 direct-search call 的局部 rank 做观测分类。
    if gt.has_relevant:
        audit = _recorded_direct_hits(run_query_result)
        observed_relevant = _observed_relevant_hits(audit, gt.relevant_message_ids)
        top_k_hit = _has_relevant_hit_at_k(audit, gt.relevant_message_ids)
        if not top_k_hit:
            actual_with_observation = {
                **actual,
                "recorded_direct_hits": len(audit.observations),
                "observed_relevant_direct_hits": observed_relevant,
                "hit_at_k_observable": audit.hit_at_k_observable,
                "ignored_context_calls": audit.ignored_context_calls,
            }
            if not audit.hit_at_k_observable:
                return BenchmarkFailure(
                    case_id=gt.case_id,
                    variant_id=variant_id,
                    run_id=run_id,
                    category="not_observed_within_recorded_depth",
                    expected={"hit_at_k": ACCEPTANCE_HIT_K},
                    actual=actual_with_observation,
                    trace_id=trace_id,
                    detail="relevant messages were not observable within the recorded top-K depth",
                )
            if observed_relevant:
                return BenchmarkFailure(
                    case_id=gt.case_id,
                    variant_id=variant_id,
                    run_id=run_id,
                    category="ranking_failure",
                    expected={"hit_at_k": ACCEPTANCE_HIT_K},
                    actual=actual_with_observation,
                    trace_id=trace_id,
                    detail="relevant messages were observed in direct search but all recorded ranks exceeded K",
                )
            return BenchmarkFailure(
                case_id=gt.case_id,
                variant_id=variant_id,
                run_id=run_id,
                category="retrieval_miss",
                expected={"hit_at_k": ACCEPTANCE_HIT_K, "relevant_count": len(gt.relevant_message_ids)},
                actual=actual_with_observation,
                trace_id=trace_id,
                detail="no GT relevant message appears in the recorded direct hits",
            )

    # 6. 其余：answer generation 层违反（如 claims 无 citation 的明文答案）目前不自动判失败，
    # 交给 Tier 2 judge 与人工 review；这里保持 acceptance 列表最小化。
    return None
