from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from tests.test_semantic_retrieval import _DeterministicProvider, _write_semantic_fixture
from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.settings import ModelSettings
from trivae.evaluation import (
    BlindAnnotationPacket,
    BlindCandidate,
    ControlledVariant,
    DatasetSnapshot,
    EvaluationContractError,
    LLMRetrievalAnnotator,
    RelevanceAnnotation,
    RelevanceAnnotationSet,
    RetrievalAppearance,
    RetrievalEvaluationQuery,
    RetrievalQuerySet,
    RetrievalRunRecord,
    SealedCandidate,
    SealedRetrievalPacket,
    build_retrieval_audit_queue,
    build_retrieval_metrics,
)


def _snapshot(snapshot_id: str = "snapshot-test") -> DatasetSnapshot:
    """构造不含正文的固定 Snapshot。"""

    return DatasetSnapshot(
        snapshot_id=snapshot_id,
        canonical_database_identity="sqlite-canonical:test",
        schema_version="canonical-m1-v1",
        source_identity="source-test",
        message_count=3,
        relevant_time_range=(1, 3),
        deterministic_fingerprint="snapshot-test-fingerprint",
        created_at="2026-08-24T00:00:00+00:00",
        manifest={"message_count": 3},
    )


def _variant(strategy: str) -> ControlledVariant:
    """建立只改变检索方法的测试 Variant。"""

    return ControlledVariant(
        variant_id=f"{strategy}-variant",
        code_version="test-code",
        provider="local",
        model="none",
        role="minimal_control" if strategy == "lexical" else "candidate",
        available_tools=(f"{strategy}_search",),
        retrieval_configuration={"strategy": strategy},
        index_identity=f"{strategy}-index",
    )


def _appearance(strategy: str, rank: int) -> RetrievalAppearance:
    return RetrievalAppearance(
        strategy=strategy,  # type: ignore[arg-type]
        rank=rank,
        source_rank=rank,
        score=1.0 / rank,
        score_type="fixture_score",
        hit_identity=f"{strategy}-hit-{rank}",
    )


def _sealed(
    *,
    lexical_ids: tuple[str, ...] = ("m1", "m2"),
    semantic_ids: tuple[str, ...] = ("m2", "m3"),
    snapshot_id: str = "snapshot-test",
) -> SealedRetrievalPacket:
    """生成三候选、两策略的固定 sealed packet。"""

    query = RetrievalEvaluationQuery(
        query_id="q1",
        query="find relevant evidence",
        lexical_query="evidence",
        query_types=("fixture",),
        scope=ExecutionScope(max_results=8),
    )
    query_set = RetrievalQuerySet("retrieval-fixture", 1, snapshot_id, (query,))
    candidates: list[SealedCandidate] = []
    for index, message_id in enumerate(("m1", "m2", "m3"), start=1):
        appearances: list[RetrievalAppearance] = []
        if message_id in lexical_ids:
            appearances.append(_appearance("lexical", lexical_ids.index(message_id) + 1))
        if message_id in semantic_ids:
            appearances.append(_appearance("semantic", semantic_ids.index(message_id) + 1))
        candidates.append(
            SealedCandidate(
                blind_id=f"b{index}",
                query_id="q1",
                canonical_message_id=message_id,
                session_id="session-1",
                source_message_id=message_id,
                timestamp=index,
                appearances=tuple(appearances),
                context_message_ids=(message_id,),
            )
        )
    return SealedRetrievalPacket(
        packet_id="packet-1",
        query_set=query_set,
        snapshot=_snapshot(snapshot_id),
        lexical_variant=_variant("lexical"),
        semantic_variant=_variant("semantic"),
        created_at="2026-08-24T00:00:00+00:00",
        runs=(
            RetrievalRunRecord(
                query_id="q1",
                strategy="lexical",
                variant_id="lexical-variant",
                variant_identity=_variant("lexical").identity,
                ranked_candidate_ids=lexical_ids,
                expanded_message_ids=lexical_ids,
                total_hits=len(lexical_ids),
                latency_ms=1.0,
                coverage_status="complete",
                coverage_basis="fixture",
                partial=False,
                truncated=False,
                parameters={"limit": 8},
                index_identity="lexical-index",
            ),
            RetrievalRunRecord(
                query_id="q1",
                strategy="semantic",
                variant_id="semantic-variant",
                variant_identity=_variant("semantic").identity,
                ranked_candidate_ids=semantic_ids,
                expanded_message_ids=semantic_ids,
                total_hits=len(semantic_ids),
                latency_ms=2.0,
                coverage_status="complete",
                coverage_basis="fixture",
                partial=False,
                truncated=False,
                parameters={"limit": 8, "dense_top_k": 40},
                index_identity="semantic-index",
            ),
        ),
        candidates=tuple(candidates),
        diagnostics=(),
    )


def _annotations(
    labels: tuple[str, ...],
    *,
    snapshot_id: str = "snapshot-test",
    include: int = 3,
) -> RelevanceAnnotationSet:
    """构造 provisional 标签；include 可模拟 partial annotation。"""

    return RelevanceAnnotationSet(
        packet_id="packet-1",
        snapshot_id=snapshot_id,
        rubric_version="retrieval-relevance-v1",
        annotator_type="llm_assisted",
        annotator_identity="fixture-model",
        created_at="2026-08-24T00:00:00+00:00",
        annotations=tuple(
            RelevanceAnnotation(
                blind_id=f"b{index}",
                label=label,  # type: ignore[arg-type]
                confidence=0.9,
                notes="fixture",
                verification_status="llm_assisted_provisional",
            )
            for index, label in enumerate(labels[:include], start=1)
        ),
    )


def _metric(
    report: dict[str, object],
    strategy: str,
    name: str,
    k: int | None = None,
) -> dict[str, Any]:
    query = report["queries"][0]  # type: ignore[index]
    metrics = query["strategies"][strategy]["metrics"]
    return next(item for item in metrics if item["name"] == name and item["k"] == k)


class RetrievalMetricTests(unittest.TestCase):
    """覆盖 retrieval relevance 指标的保守 availability 语义。"""

    def test_perfect_retrieval_and_rank_ordering(self) -> None:
        sealed = _sealed(lexical_ids=("m1", "m2"), semantic_ids=("m2", "m1", "m3"))
        report = build_retrieval_metrics(
            sealed,
            _annotations(("relevant", "relevant", "not_relevant")),
            ks=(1, 2),
        )

        self.assertEqual(report["metric_status"], "llm_assisted_provisional")
        self.assertFalse(report["ground_truth_claim"])
        provenance = report["annotation_provenance"]
        self.assertEqual(provenance["annotator_identity"], "fixture-model")  # type: ignore[index]
        self.assertEqual(provenance["label_counts"]["relevant"], 2)  # type: ignore[index]
        self.assertEqual(provenance["verification_counts"]["human_verified"], 0)  # type: ignore[index]
        self.assertEqual(provenance["confidence"]["mean"], 0.9)  # type: ignore[index]
        self.assertEqual(_metric(report, "lexical", "recall_at_k", 2)["value"], 1.0)
        self.assertEqual(_metric(report, "lexical", "mrr")["value"], 1.0)
        self.assertEqual(_metric(report, "semantic", "mrr")["value"], 1.0)

    def test_complete_miss_and_paired_comparison(self) -> None:
        sealed = _sealed(lexical_ids=("m1", "m2"), semantic_ids=("m3", "m2"))
        report = build_retrieval_metrics(
            sealed,
            _annotations(("not_relevant", "not_relevant", "relevant")),
            ks=(1, 2),
        )

        self.assertEqual(_metric(report, "lexical", "recall_at_k", 2)["value"], 0.0)
        self.assertEqual(_metric(report, "lexical", "mrr")["value"], 0.0)
        self.assertEqual(_metric(report, "semantic", "recall_at_k", 1)["value"], 1.0)
        self.assertEqual(_metric(report, "semantic", "mrr")["value"], 1.0)

    def test_partial_relevance_is_not_counted_as_full_relevant(self) -> None:
        sealed = _sealed()
        report = build_retrieval_metrics(
            sealed,
            _annotations(("partially_relevant", "not_relevant", "relevant")),
            ks=(1, 2),
        )

        self.assertEqual(_metric(report, "lexical", "precision_at_k", 1)["value"], 0.0)
        self.assertEqual(
            _metric(report, "lexical", "partial_relevant_coverage")["value"],
            1.0,
        )
        self.assertEqual(
            _metric(report, "semantic", "partial_relevant_coverage")["value"],
            0.0,
        )

    def test_duplicate_result_does_not_inflate_metrics(self) -> None:
        sealed = _sealed(lexical_ids=("m1", "m1", "m2"))
        report = build_retrieval_metrics(
            sealed,
            _annotations(("relevant", "not_relevant", "not_relevant")),
            ks=(2,),
        )

        lexical = report["queries"][0]["strategies"]["lexical"]  # type: ignore[index]
        self.assertEqual(lexical["diagnostics"]["duplicate_candidate_count"], 1)
        self.assertEqual(_metric(report, "lexical", "precision_at_k", 2)["value"], 0.5)

    def test_no_relevant_finding_keeps_recall_and_mrr_unavailable(self) -> None:
        report = build_retrieval_metrics(
            _sealed(),
            _annotations(("not_relevant", "not_relevant", "not_relevant")),
            ks=(1,),
        )

        self.assertEqual(_metric(report, "lexical", "precision_at_k", 1)["value"], 0.0)
        self.assertEqual(_metric(report, "lexical", "recall_at_k", 1)["availability"], "unavailable")
        self.assertEqual(_metric(report, "lexical", "mrr")["availability"], "unavailable")

    def test_unknown_and_partial_annotation_are_never_negative_labels(self) -> None:
        unknown = build_retrieval_metrics(
            _sealed(),
            _annotations(("uncertain", "not_relevant", "relevant")),
            ks=(1,),
        )
        partial = build_retrieval_metrics(
            _sealed(),
            _annotations(("not_relevant", "not_relevant", "relevant"), include=2),
            ks=(1,),
        )

        self.assertEqual(_metric(unknown, "lexical", "precision_at_k", 1)["availability"], "unavailable")
        self.assertEqual(_metric(unknown, "semantic", "recall_at_k", 1)["availability"], "unavailable")
        self.assertEqual(_metric(partial, "lexical", "recall_at_k", 1)["availability"], "unavailable")

    def test_invalid_snapshot_is_rejected(self) -> None:
        with self.assertRaises(EvaluationContractError):
            build_retrieval_metrics(
                _sealed(),
                _annotations(("relevant", "not_relevant", "not_relevant"), snapshot_id="other"),
            )

    def test_audit_queue_prioritizes_uncertain_and_high_impact_labels(self) -> None:
        queue = build_retrieval_audit_queue(
            _sealed(),
            _annotations(("uncertain", "not_relevant", "relevant")),
        )

        self.assertGreater(queue["queue_count"], 0)
        self.assertGreater(queue["priority_counts"]["high"], 0)  # type: ignore[index]
        self.assertEqual(queue["annotator_identity"], "fixture-model")
        self.assertEqual(queue["rubric_version"], "retrieval-relevance-v1")


class RetrievalPacketWorkflowTests(unittest.TestCase):
    """验证 packet 复用真实 Tool facade，blind 部分不泄漏方法和排名。"""

    def test_application_generates_deduplicated_blind_and_sealed_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            with create_application(
                root / "app.sqlite3",
                semantic_provider=_DeterministicProvider(),
            ) as application:
                application.import_directory(raw)
                application.rebuild_lexical_index()
                application.rebuild_semantic_index()
                snapshot = application.materialize_evaluation_snapshot()
                query_set = RetrievalQuerySet(
                    "workflow-fixture",
                    1,
                    snapshot.snapshot_id,
                    (
                        RetrievalEvaluationQuery(
                            query_id="budget",
                            query="how was the budget planned",
                            lexical_query="budget",
                            query_types=("literal", "semantic"),
                            scope=ExecutionScope(max_results=2),
                            candidate_limit=2,
                            context_before=1,
                            context_after=1,
                        ),
                    ),
                )
                blind, sealed = application.generate_retrieval_annotation_packet(
                    query_set,
                    _variant("lexical"),
                    _variant("semantic"),
                )

            self.assertEqual(blind.packet_id, sealed.packet_id)
            self.assertEqual(len(sealed.runs), 2)
            self.assertEqual(
                len({(item.query_id, item.canonical_message_id) for item in sealed.candidates}),
                len(sealed.candidates),
            )
            for candidate in blind.to_dict()["candidates"]:  # type: ignore[index]
                serialized = json.dumps(candidate, ensure_ascii=False)
                self.assertNotIn('"strategy"', serialized)
                self.assertNotIn('"rank"', serialized)
                self.assertNotIn('"score"', serialized)
            self.assertTrue(
                any(len(item.appearances) == 2 for item in sealed.candidates),
                "同一 canonical hit 应合并 lexical/semantic provenance",
            )


class RetrievalLLMAnnotationTests(unittest.TestCase):
    """验证 LLM 路径只看 blind payload，且永远不能自称 human verified。"""

    def test_llm_annotation_is_complete_blind_and_provisional(self) -> None:
        packet = BlindAnnotationPacket(
            packet_id="packet-llm",
            query_set_id="query-set",
            query_set_version=1,
            snapshot_id="snapshot-llm",
            rubric_version="retrieval-relevance-v1",
            created_at="2026-08-24T00:00:00+00:00",
            candidates=(
                BlindCandidate(
                    blind_id="q1:candidate-001",
                    query_id="q1",
                    query="find evidence",
                    candidate={"canonical_message_id": "m1", "content": "useful evidence"},
                    context=({"canonical_message_id": "m1", "content": "useful evidence"},),
                ),
                BlindCandidate(
                    blind_id="q1:candidate-002",
                    query_id="q1",
                    query="find evidence",
                    candidate={"canonical_message_id": "m2", "content": "unrelated"},
                    context=({"canonical_message_id": "m2", "content": "unrelated"},),
                ),
            ),
        )
        observed_payloads: list[dict[str, object]] = []

        class FakeCompletions:
            async def create(self, **kwargs: object) -> object:
                messages = kwargs["messages"]
                payload = json.loads(messages[1]["content"])  # type: ignore[index]
                observed_payloads.append(payload)
                labels = [
                    {
                        "blind_id": item["blind_id"],
                        "label": "relevant" if "useful" in item["candidate"]["content"] else "not_relevant",
                        "confidence": 0.9,
                        "notes": "fixture",
                    }
                    for item in payload["candidates"]
                ]
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=json.dumps({"labels": labels}))
                        )
                    ]
                )

        class FakeClient:
            def __init__(self, **_: object) -> None:
                self.chat = SimpleNamespace(completions=FakeCompletions())

            async def __aenter__(self) -> FakeClient:
                return self

            async def __aexit__(self, *_: object) -> None:
                return None

        settings = ModelSettings(
            api_key="fixture-key",
            base_url="https://provider.test/v1",
            provider="deepseek",
            model_name="fixture-model",
            max_turns=1,
        )
        with patch(
            "trivae.evaluation.retrieval_annotation.AsyncOpenAI",
            FakeClient,
        ):
            annotations = asyncio.run(LLMRetrievalAnnotator(settings).annotate(packet))

        self.assertEqual(len(annotations.annotations), 2)
        self.assertEqual(annotations.reference_status, "llm_assisted_provisional")
        self.assertTrue(all(not item.verification_status == "human_verified" for item in annotations.annotations))
        serialized_payload = json.dumps(observed_payloads, ensure_ascii=False)
        self.assertNotIn('"strategy"', serialized_payload)
        self.assertNotIn('"rank"', serialized_payload)
        self.assertNotIn('"score"', serialized_payload)


if __name__ == "__main__":
    unittest.main()
