"""Case GT → 现有 RetrievalQuerySet/Workflow 的薄 adapter。

本模块不重写 invocation、ranking 或 coverage projection：module-level 双策略执行
完全复用 ``TrivaeApplication.generate_retrieval_annotation_packet``（内部就是现有
``RetrievalAnnotationWorkflow``），本文件只负责：
1. 把 benchmark case + per-case retrieval 配置编译成 ``RetrievalQuerySet``；
2. 对 sealed packet 的 ``RetrievalRunRecord`` 做 GT 直接评分（不经盲标标签）。
"""

from __future__ import annotations

from dataclasses import dataclass

from trivae.capabilities.contracts import ExecutionScope
from trivae.evaluation.contracts import EvaluationCaseBundle, EvaluationContractError
from trivae.evaluation.retrieval_evaluation import (
    RetrievalEvaluationQuery,
    RetrievalQuerySet,
    SealedRetrievalPacket,
)
from trivae.evaluation.variant import ControlledVariant

from .gt import CaseGroundTruth
from .metrics import (
    DEFAULT_MRR_K,
    DEFAULT_RECALL_KS,
    MetricOutcome,
    score_expansion,
    score_ranking,
    score_ranking_with_ranges,
)


@dataclass(frozen=True)
class RetrievalCaseConfig:
    """一个 case 的 module-level 检索参数；query-set-controlled，非模型可控。"""

    lexical_query: str
    context_before: int = 2
    context_after: int = 2
    candidate_limit: int = 10
    dense_top_k: int = 40


def build_retrieval_query_set(
    *,
    query_set_id: str,
    version: int,
    snapshot_id: str,
    cases: tuple[EvaluationCaseBundle, ...],
    configs: dict[str, RetrievalCaseConfig],
    description: str = "",
) -> RetrievalQuerySet:
    """把 benchmark case 编译为现有 RetrievalQuerySet；query_id == case_id 保证 GT join。"""

    queries: list[RetrievalEvaluationQuery] = []
    for case in cases:
        config = configs.get(case.case_id)
        if config is None:
            raise EvaluationContractError(f"case {case.case_id} has no benchmark retrieval config")
        if case.case_id != case.case_id.strip():
            raise EvaluationContractError("benchmark case_id must not contain surrounding whitespace")
        scope: ExecutionScope = case.data_access_scope
        if config.candidate_limit > scope.max_results:
            raise EvaluationContractError(
                f"case {case.case_id} candidate_limit exceeds scope.max_results"
            )
        queries.append(
            RetrievalEvaluationQuery(
                query_id=case.case_id,
                query=case.query,
                lexical_query=config.lexical_query,
                query_types=(f"benchmark:{case.case_id}",),
                scope=scope,
                candidate_limit=config.candidate_limit,
                context_before=config.context_before,
                context_after=config.context_after,
                dense_top_k=config.dense_top_k,
                diagnostic=False,
            )
        )
    return RetrievalQuerySet(
        query_set_id=query_set_id,
        version=version,
        snapshot_id=snapshot_id,
        queries=tuple(queries),
        description=description,
    )


def score_sealed_packet(
    sealed: SealedRetrievalPacket,
    gt_index: dict[str, CaseGroundTruth],
    *,
    ks: tuple[int, ...] = DEFAULT_RECALL_KS,
    mrr_k: int = DEFAULT_MRR_K,
) -> dict[str, object]:
    """对 sealed packet 的每个 strategy run 做 GT 评分；不经盲标标签。

    语义检索单元是 canonical range（anchor + 范围恢复），不是单条消息：
    semantic 命中判定为「target ∈ 该 rank anchor 的恢复范围」；lexical 的
    candidate unit 是单条消息，按 anchor 精确匹配。
    """

    if sealed.query_set.snapshot_id != sealed.snapshot.snapshot_id:
        raise EvaluationContractError("sealed packet snapshot does not match query set")
    range_by_anchor: dict[tuple[str, str], frozenset[str]] = {}
    for candidate in sealed.candidates:
        range_by_anchor[(candidate.query_id, candidate.canonical_message_id)] = frozenset(
            candidate.context_message_ids
        )
    runs_by_query: dict[str, list] = {}
    for run in sealed.runs:
        runs_by_query.setdefault(run.query_id, []).append(run)

    query_results: list[dict[str, object]] = []
    for query in sealed.query_set.queries:
        gt = gt_index.get(query.query_id)
        if gt is None:
            raise EvaluationContractError(f"query {query.query_id} has no benchmark GT")
        metrics: list[MetricOutcome] = []
        strategy_flags: dict[str, object] = {}
        for run in runs_by_query.get(query.query_id, ()):
            suffix = run.strategy
            if run.strategy == "semantic":
                metrics.extend(
                    score_ranking_with_ranges(
                        gt,
                        run.ranked_candidate_ids,
                        range_by_anchor,
                        query.query_id,
                        ks=ks,
                        mrr_k=mrr_k,
                        strategy_scope_suffix=suffix,
                    )
                )
            else:
                metrics.extend(
                    score_ranking(gt, run.ranked_candidate_ids, ks=ks, mrr_k=mrr_k, strategy_scope_suffix=suffix)
                )
            metrics.append(score_expansion(gt, run.expanded_message_ids, strategy_scope_suffix=suffix))
            strategy_flags[run.strategy] = {
                "total_hits": run.total_hits,
                "coverage_status": run.coverage_status,
                "partial": run.partial,
                "truncated": run.truncated,
                "latency_ms": run.latency_ms,
                "index_identity": run.index_identity,
            }
        if not strategy_flags:
            raise EvaluationContractError(f"query {query.query_id} has no retrieval runs")
        query_results.append(
            {
                "case_id": query.query_id,
                "category": gt.category,
                "recall_scope": gt.recall_scope,
                "completeness": gt.completeness,
                "strategies": strategy_flags,
                "metrics": [item.to_dict() for item in metrics],
            }
        )
    return {
        "packet_id": sealed.packet_id,
        "snapshot_id": sealed.snapshot.snapshot_id,
        "query_set_id": sealed.query_set.query_set_id,
        "query_set_version": sealed.query_set.version,
        "lexical_variant_id": sealed.lexical_variant.variant_id,
        "semantic_variant_id": sealed.semantic_variant.variant_id,
        "queries": query_results,
    }


def assert_benchmark_variants(
    lexical_variant: ControlledVariant,
    semantic_variant: ControlledVariant,
) -> None:
    """module-level 通道只要求两个 retrieval-only variant 具备对应 tool 暴露。"""

    if "lexical_search" not in lexical_variant.available_tools:
        raise EvaluationContractError("lexical module variant must expose lexical_search")
    if "semantic_search" not in semantic_variant.available_tools:
        raise EvaluationContractError("semantic module variant must expose semantic_search")
