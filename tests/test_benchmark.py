"""Benchmark Measurement Substrate 回归：GT 解析、Tier 1 指标、failure 判定、gate 与投影。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.evaluation import ControlledVariant
from trivae.evaluation.benchmark.environment import (
    BenchmarkEnvironmentManifest,
    capture_environment,
    verify_environment,
)
from trivae.evaluation.benchmark.failures import evaluate_case_failure
from trivae.evaluation.benchmark.freeze import capture_freeze_record, verify_freeze_record
from trivae.evaluation.benchmark.gt import build_case_ground_truth
from trivae.evaluation.benchmark.metrics import evaluate_end_to_end_case, score_expansion, score_ranking
from trivae.evaluation.benchmark.report import aggregate_metric_records, build_report, render_markdown
from trivae.evaluation.checks import query_result_snapshot, run_deterministic_checks
from trivae.evaluation.contracts import (
    CaseReference,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationSuite,
    ReferenceEvidence,
    ReferenceFinding,
    ReferenceProvenance,
)
from trivae.observability.contracts import TraceMetrics, TraceProjection, TraceTimelineItem
from trivae.query.contracts import ExecutionOverride, QueryRequest, QueryResult
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    SourceHandleReference,
    ToolMessageItem,
    ToolResultRecord,
)
from trivae.query.router import RouteDecision
from trivae.query.runtime.contracts import RuntimeErrorInfo, RuntimeResult, RuntimeToolCall
from trivae.retrieval.structured import MessageProjection

_SNAPSHOT = DatasetSnapshot(
    snapshot_id="snapshot:benchmark-test",
    canonical_database_identity="sqlite-canonical:test",
    schema_version="canonical-m1-v1",
    source_identity="source:test",
    message_count=3,
    relevant_time_range=(100, 300),
    deterministic_fingerprint="manifest:test",
    created_at="2026-08-30T00:00:00+00:00",
    manifest={"message_count": 3, "lexical_index": {"present": True, "message_count": 3}},
)

_SCOPE = ExecutionScope(allowed_session_ids=("session:test",), max_results=20)


def _provenance() -> ReferenceProvenance:
    return ReferenceProvenance(
        source="test",
        created_at="2026-08-30T00:00:00+00:00",
        method="deterministic predicate scan",
        snapshot_id=_SNAPSHOT.snapshot_id,
        scope_identity='{"allowed_session_ids":["session:test"],"end_timestamp":null,"max_results":20,"start_timestamp":null}',
    )


def _message_evidence(message_id: str, *, relation: str = "supports") -> ReferenceEvidence:
    return ReferenceEvidence(
        evidence_id=f"ev:{message_id}",
        relation=relation,  # type: ignore[arg-type]
        source_type="message",
        locator={"internal_message_id": message_id},
        why_relevant="test",
        provenance=_provenance(),
    )


def _finding(
    finding_id: str,
    criterion: str,
    expected_semantics: str,
    evidence=(),
    *,
    completeness: str = "exhaustive",
) -> ReferenceFinding:
    return ReferenceFinding(
        finding_id=finding_id,
        criterion=criterion,
        expected_semantics=expected_semantics,
        reference_evidence=tuple(evidence),
        annotation_completeness=completeness,  # type: ignore[arg-type]
        provenance=_provenance(),
    )


def _case(findings=(), *, case_id: str = "case-benchmark", tags=("category:exact_lexical",)) -> EvaluationCaseBundle:
    return EvaluationCaseBundle(
        case_id=case_id,
        version=1,
        suite_tags=tags,
        dataset_snapshot=_SNAPSHOT,
        data_access_scope=_SCOPE,
        query="test query",
        reference_findings=tuple(findings),
    )


def _gt(findings=(), **kwargs) -> object:
    return build_case_ground_truth(_case(findings, **kwargs))


class GroundTruthTests(unittest.TestCase):
    """GT criterion 约定解析与一致性校验。"""

    def test_full_gt_parse_with_all_axes(self) -> None:
        truth = _gt(
            (
                _finding(
                    "relevant",
                    "gt.relevant",
                    "messages that answer the question",
                    (_message_evidence("m1"), _message_evidence("m2")),
                ),
                _finding("context", "gt.required_context", "prior setup", (_message_evidence("m0", relation="context"),)),
                _finding("coverage", "gt.expected_coverage_status", "partial"),
                _finding("truncated", "gt.expected_truncated", "true"),
                _finding("zero", "gt.expected_zero_result", "false"),
                _finding("fact", "gt.expected_fact", '["LangGraph", "langgraph"]'),
            )
        )
        self.assertEqual(truth.relevant_message_ids, ("m1", "m2"))
        self.assertEqual(truth.required_context_message_ids, ("m0",))
        self.assertEqual(truth.expected_coverage_status, "partial")
        self.assertTrue(truth.expected_truncated)
        self.assertFalse(truth.expected_zero_result)
        self.assertEqual(truth.expected_facts, (("langgraph",),))
        self.assertEqual(truth.completeness, "exhaustive")
        self.assertEqual(truth.recall_scope, "corpus")
        self.assertEqual(truth.evidence_target_ids, ("m1", "m2", "m0"))

    def test_partial_completeness_declares_target_scope(self) -> None:
        truth = _gt(
            (_finding("relevant", "gt.relevant", "subset", (_message_evidence("m1"),), completeness="partial"),)
        )
        self.assertEqual(truth.completeness, "partial")
        self.assertEqual(truth.recall_scope, "target")

    def test_zero_result_true_implies_no_relevant(self) -> None:
        truth = _gt((_finding("zero", "gt.expected_zero_result", "true"),))
        self.assertTrue(truth.expected_zero_result)
        self.assertFalse(truth.has_relevant)
        with self.assertRaises(EvaluationContractError):
            _gt(
                (
                    _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                    _finding("zero", "gt.expected_zero_result", "true"),
                )
            )

    def test_zero_result_false_keeps_relevant(self) -> None:
        truth = _gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("zero", "gt.expected_zero_result", "false"),
            )
        )
        self.assertFalse(truth.expected_zero_result)
        self.assertTrue(truth.has_relevant)

    def test_unknown_criterion_and_bad_locator_are_rejected(self) -> None:
        with self.assertRaises(EvaluationContractError):
            _gt((_finding("bad", "gt.unknown", "x"),))
        with self.assertRaises(EvaluationContractError):
            _gt(
                (
                    _finding(
                        "relevant",
                        "gt.relevant",
                        "x",
                        (
                            ReferenceEvidence(
                                evidence_id="ev:structured",
                                relation="supports",
                                source_type="structured",
                                locator={"locator_kind": "row", "locator": "r1"},
                                why_relevant="test",
                                provenance=_provenance(),
                            ),
                        ),
                    ),
                )
            )


class RankingMetricTests(unittest.TestCase):
    """Recall@K / Hit@K / MRR@K 的 scope 与 cutoff 语义。"""

    def test_perfect_ranking_corpus_scope(self) -> None:
        truth = _gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"), _message_evidence("m2"))),))
        outcomes = {item.name + f"@{item.k}": item for item in score_ranking(truth, ("m1", "m9", "m2"))}
        self.assertEqual(outcomes["recall_at_k@5"].value, 1.0)
        self.assertEqual(outcomes["recall_at_k@5"].scope, "corpus")
        self.assertEqual(outcomes["recall_at_k@10"].value, 1.0)
        self.assertEqual(outcomes["hit_at_k@5"].value, 1.0)
        self.assertEqual(outcomes["mrr_at_k@10"].value, 1.0)

    def test_mrr_cutoff_beyond_k_is_zero_not_unavailable(self) -> None:
        truth = _gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m12"),)),))
        ranked = tuple(f"m{index}" for index in range(1, 13))
        outcomes = {item.name: item for item in score_ranking(truth, ranked)}
        self.assertEqual(outcomes["mrr_at_k"].value, 0.0)
        self.assertEqual(outcomes["mrr_at_k"].k, 10)
        self.assertEqual(outcomes["recall_at_k"].value if "recall_at_k" in outcomes else outcomes["recall_at_k@10"].value, 0.0)

    def test_duplicates_do_not_inflate_recall(self) -> None:
        truth = _gt(
            [
                _finding(
                    "relevant",
                    "gt.relevant",
                    "x",
                    [_message_evidence("m1"), _message_evidence("m2")],
                )
            ]
        )
        outcomes = {item.name + f"@{item.k}": item for item in score_ranking(truth, ("m1", "m1", "m2"))}
        self.assertEqual(outcomes["recall_at_k@5"].value, 1.0)

    def test_partial_gt_reports_target_scope(self) -> None:
        truth = _gt(
            (
                _finding(
                    "relevant",
                    "gt.relevant",
                    "x",
                    (_message_evidence("m1"), _message_evidence("m2")),
                    completeness="partial",
                ),
            )
        )
        outcomes = {item.name + f"@{item.k}": item for item in score_ranking(truth, ("m1", "m9"))}
        self.assertEqual(outcomes["recall_at_k@5"].scope, "target")
        self.assertEqual(outcomes["recall_at_k@5"].value, 0.5)

    def test_unknown_gt_is_unavailable_not_zero(self) -> None:
        truth = _gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),), completeness="unknown"),))
        outcomes = {item.name + f"@{item.k}": item for item in score_ranking(truth, ("m1",))}
        self.assertEqual(outcomes["recall_at_k@5"].availability, "unavailable")


class ExpansionMetricTests(unittest.TestCase):
    """module-level context expansion 的 recovery 语义。"""

    def test_context_recovery_counts_required_ids(self) -> None:
        truth = _gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("context", "gt.required_context", "y", (_message_evidence("m0", relation="context"), _message_evidence("m9", relation="context"))),
            )
        )
        outcome = score_expansion(truth, ("m0",))
        self.assertEqual(outcome.value, 0.5)

    def test_no_required_context_is_not_applicable(self) -> None:
        truth = _gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),))
        self.assertEqual(score_expansion(truth, ("m0",)).availability, "not_applicable")


def _end_to_end_projection(**overrides) -> dict[str, object]:
    """构造与 checks.query_result_snapshot 同形的 run projection。"""

    projection: dict[str, object] = {
        "termination": "completed",
        "is_successful": True,
        "answer_form": "claims",
        "answer_text": "群里有讨论",
        "retrieval_coverage": None,
        "evidence_sources": {"sources": [], "total": 0, "omitted": 0},
        "retrieval_calls": {"calls": [], "total": 0, "omitted": 0},
    }
    projection.update(overrides)
    return projection


def _evidence_projection(*message_ids: str) -> dict[str, object]:
    return {
        "sources": [{"evidence_id": f"e{index}", "message_ids": [message_id], "structured_locator_kinds": []} for index, message_id in enumerate(message_ids)],
        "total": len(message_ids),
        "omitted": 0,
    }


class EndToEndMetricTests(unittest.TestCase):
    """Evidence Recall / Coverage 三轴 / Zero-result / 无条件完成率。"""

    def _base_gt(self, **kwargs):
        findings = kwargs.pop("findings")
        return _gt(findings, **kwargs)

    def test_evidence_recall_and_context_recovery(self) -> None:
        truth = self._base_gt(
            findings=(
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"), _message_evidence("m2"))),
                _finding("context", "gt.required_context", "y", (_message_evidence("m0", relation="context"),)),
            )
        )
        result = evaluate_end_to_end_case(truth, _end_to_end_projection(evidence_sources=_evidence_projection("m1", "m0")))
        metrics = {item["name"]: item for item in result["metrics"]}
        self.assertEqual(metrics["evidence_recall"]["value"], 2 / 3)
        self.assertEqual(metrics["context_recovery"]["value"], 1.0)
        self.assertEqual(metrics["execution_completed"]["value"], 1.0)
        self.assertEqual(metrics["valid_answer"]["value"], 1.0)

    def test_coverage_status_accuracy_reads_artifact_only(self) -> None:
        truth = self._base_gt(
            findings=(
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("coverage", "gt.expected_coverage_status", "complete"),
            )
        )
        mismatched = evaluate_end_to_end_case(
            truth, _end_to_end_projection(retrieval_coverage={"status": "partial", "basis": "b", "unit": "message", "covered_units": 1, "eligible_units": 3, "retrieved_count": 1, "has_more": True})
        )
        self.assertEqual({item["name"]: item for item in mismatched["metrics"]}["coverage_status_accuracy"]["value"], 0.0)
        unavailable = evaluate_end_to_end_case(truth, _end_to_end_projection(retrieval_coverage=None))
        self.assertEqual(
            {item["name"]: item for item in unavailable["metrics"]}["coverage_status_accuracy"]["availability"],
            "unavailable",
        )

    def test_expected_fact_requires_answer_text_hit(self) -> None:
        truth = self._base_gt(
            findings=(
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("fact", "gt.expected_fact", '["langgraph"]'),
            )
        )
        hit = evaluate_end_to_end_case(
            truth,
            _end_to_end_projection(answer_text="大家推荐了 LangGraph", evidence_sources=_evidence_projection("langgraph-in-content")),
        )
        self.assertEqual({item["name"]: item for item in hit["metrics"]}["expected_fact_answer_coverage"]["value"], 1.0)
        miss = evaluate_end_to_end_case(
            truth,
            _end_to_end_projection(answer_text="大家讨论了别的", evidence_sources=_evidence_projection("m1")),
        )
        self.assertEqual({item["name"]: item for item in miss["metrics"]}["expected_fact_answer_coverage"]["value"], 0.0)

    def test_zero_result_axes(self) -> None:
        positive = self._base_gt(
            findings=(
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("zero", "gt.expected_zero_result", "false"),
            )
        )
        violation = evaluate_end_to_end_case(positive, _end_to_end_projection(answer_form="no_result_signature"))
        self.assertEqual({item["name"]: item for item in violation["metrics"]}["false_zero_result"]["value"], 0.0)
        healthy = evaluate_end_to_end_case(positive, _end_to_end_projection())
        self.assertEqual({item["name"]: item for item in healthy["metrics"]}["false_zero_result"]["value"], 1.0)

        negative = self._base_gt(findings=(_finding("zero", "gt.expected_zero_result", "true"),))
        verified = evaluate_end_to_end_case(negative, _end_to_end_projection(answer_form="no_result_signature"))
        self.assertEqual({item["name"]: item for item in verified["metrics"]}["verified_zero_result"]["value"], 1.0)

    def test_exception_run_excludes_conditional_metrics(self) -> None:
        truth = self._base_gt(findings=(_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),))
        result = evaluate_end_to_end_case(truth, _end_to_end_projection(termination="failed", is_successful=False))
        metrics = {item["name"]: item for item in result["metrics"]}
        self.assertEqual(metrics["execution_completed"]["value"], 0.0)
        self.assertEqual(metrics["evidence_recall"]["availability"], "unavailable")
        self.assertEqual(metrics["false_zero_result"]["availability"], "unavailable")


class FailureTests(unittest.TestCase):
    """acceptance condition failure 判定链。"""

    def _gt(self, findings):
        return build_case_ground_truth(_case(findings))

    def test_provider_failure_on_missing_projection(self) -> None:
        truth = self._gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),))
        failure = evaluate_case_failure(truth, variant_id="A", run_id="run-1", run_query_result=None, trace_id=None)
        self.assertIsNotNone(failure)
        self.assertEqual(failure.category, "provider_failure")

    def test_zero_result_error(self) -> None:
        truth = self._gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("zero", "gt.expected_zero_result", "false"),
            )
        )
        failure = evaluate_case_failure(
            truth,
            variant_id="A",
            run_id="run-1",
            run_query_result=_end_to_end_projection(answer_form="no_result_signature"),
            trace_id="trace-1",
        )
        self.assertEqual(failure.category, "zero_result_error")

    def test_answer_generation_failure_precedes_coverage_classification(self) -> None:
        """Finalizer 失败必须归到答案生成，不被 coverage unavailable 遮蔽。"""

        truth = self._gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("coverage", "gt.expected_coverage_status", "complete"),
            )
        )
        failure = evaluate_case_failure(
            truth,
            variant_id="D",
            run_id="run-1",
            run_query_result=_end_to_end_projection(
                answer_form=None,
                is_successful=False,
                finalization_status="failed",
                finalization_error={"code": "INVALID_ANSWER_ARTIFACT", "path": "answer"},
            ),
            trace_id="trace-1",
        )
        self.assertEqual(failure.category, "answer_generation_error")

    def test_context_missing(self) -> None:
        truth = self._gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("context", "gt.required_context", "y", (_message_evidence("m0", relation="context"),)),
            )
        )
        projection = _end_to_end_projection(
            retrieval_calls={
                "calls": [
                    {
                        "tool_call_id": "c1",
                        "tool_name": "lexical_search",
                        "strategy": "lexical",
                        "status": "ok",
                        "direct_hit_count": 1,
                        "direct_hits": [{"rank": 1, "internal_message_id": "m1"}],
                        "omitted_direct_ids": 0,
                        "expanded_count": 0,
                        "expanded_ids": [],
                        "omitted_expanded_ids": 0,
                    }
                ],
                "total": 1,
                "omitted": 0,
            },
            evidence_sources=_evidence_projection("m1"),
        )
        failure = evaluate_case_failure(truth, variant_id="A", run_id="run-1", run_query_result=projection, trace_id=None)
        self.assertEqual(failure.category, "context_missing")

    def test_retrieval_miss_vs_not_observed(self) -> None:
        truth = self._gt((_finding("relevant", "gt.relevant", "x", (_message_evidence("m99"),)),))
        fully_recorded = _end_to_end_projection(
            retrieval_calls={
                "calls": [
                    {
                        "tool_call_id": "c1",
                        "tool_name": "lexical_search",
                        "strategy": "lexical",
                        "status": "ok",
                        "direct_hit_count": 2,
                        "direct_hits": [{"rank": 1, "internal_message_id": "m1"}, {"rank": 2, "internal_message_id": "m2"}],
                        "omitted_direct_ids": 0,
                        "expanded_count": 0,
                        "expanded_ids": [],
                        "omitted_expanded_ids": 0,
                    }
                ],
                "total": 1,
                "omitted": 0,
            }
        )
        self.assertEqual(
            evaluate_case_failure(truth, variant_id="A", run_id="r", run_query_result=fully_recorded, trace_id=None).category,
            "retrieval_miss",
        )
        truncated = _end_to_end_projection(
            retrieval_calls={
                "calls": [
                    {
                        "tool_call_id": "c1",
                        "tool_name": "lexical_search",
                        "strategy": "lexical",
                        "status": "ok",
                        "direct_hit_count": 120,
                        "direct_hits": [{"rank": 1, "internal_message_id": "m1"}],
                        "omitted_direct_ids": 70,
                        "expanded_count": 0,
                        "expanded_ids": [],
                        "omitted_expanded_ids": 0,
                    }
                ],
                "total": 1,
                "omitted": 0,
            }
        )
        self.assertEqual(
            evaluate_case_failure(truth, variant_id="A", run_id="r", run_query_result=truncated, trace_id=None).category,
            "not_observed_within_recorded_depth",
        )

    def test_healthy_run_has_no_failure(self) -> None:
        truth = self._gt(
            (
                _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),
                _finding("zero", "gt.expected_zero_result", "false"),
            )
        )
        projection = _end_to_end_projection(
            retrieval_calls={
                "calls": [
                    {
                        "tool_call_id": "c1",
                        "tool_name": "lexical_search",
                        "strategy": "lexical",
                        "status": "ok",
                        "direct_hit_count": 1,
                        "direct_hits": [{"rank": 1, "internal_message_id": "m1"}],
                        "omitted_direct_ids": 0,
                        "expanded_count": 0,
                        "expanded_ids": [],
                        "omitted_expanded_ids": 0,
                    }
                ],
                "total": 1,
                "omitted": 0,
            },
            evidence_sources=_evidence_projection("m1"),
        )
        self.assertIsNone(
            evaluate_case_failure(truth, variant_id="A", run_id="r", run_query_result=projection, trace_id=None)
        )


class AggregateReportTests(unittest.TestCase):
    """聚合与 Markdown 渲染 smoke。"""

    def test_aggregate_and_render(self) -> None:
        truth = build_case_ground_truth(
            _case((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),))
        )
        records = []
        for variant_id, evidence in (("A", ()), ("B", ("m1",))):
            outcome = evaluate_end_to_end_case(
                truth,
                _end_to_end_projection(evidence_sources=_evidence_projection(*evidence)),
            )
            records.append(
                {
                    "case_id": truth.case_id,
                    "variant_id": variant_id,
                    "category": "exact_lexical",
                    "metrics": outcome["metrics"],
                }
            )
        report = {
            "benchmark": "resume-benchmark-v1",
            "environment": {"canonical_snapshot_id": "s", "git_commit": "c", "semantic_index": "i"},
            "holdout_sealed": False,
            "splits": {"development": {"overall": {record["variant_id"]: aggregate_metric_records(record["metrics"]) for record in records}}},
            "case_stats": {"total": 1},
            "failures": [],
        }
        markdown = render_markdown(report)
        self.assertIn("evidence_recall", markdown)
        self.assertIn("n/a", markdown)

    def test_report_contains_weighted_counts_operational_facts_and_pair_delta(self) -> None:
        """正式报告同时保留 rate 分母、运行事实和真实单变量 paired delta。"""

        truth = build_case_ground_truth(
            _case((_finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),)),))
        )
        variants = [{"variant_id": alias} for alias in ("A", "B", "C", "C2")]
        records = []
        for alias, evidence, latency in (
            ("A", (), 20),
            ("B", ("m1",), 10),
            ("C", ("m1",), 12),
            ("C2", (), 15),
        ):
            outcome = evaluate_end_to_end_case(
                truth,
                _end_to_end_projection(evidence_sources=_evidence_projection(*evidence)),
            )
            records.append(
                {
                    "case_id": truth.case_id,
                    "variant_id": alias,
                    "category": "exact_lexical",
                    "metrics": outcome["metrics"],
                    "operational_measurements": {
                        "latency_ms": latency,
                        "tool_calls": 1,
                        "tool_rounds": 1,
                        "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
                    },
                }
            )
        report = build_report(
            benchmark="resume-benchmark-v1",
            environment={"canonical_snapshot_id": "s", "git_commit": "c", "semantic_index": "i"},
            variants=variants,
            case_stats={"total": 1},
            end_to_end_records={"development": records},
            module_retrieval=None,
            failures=[],
            holdout_sealed=False,
            report_metadata={"stage": "stage3_final_clean", "run_count": 4},
        )
        overall_a = report["splits"]["development"]["overall"]["A"]["metrics"]
        evidence = next(item for item in overall_a if item["name"] == "evidence_recall")
        self.assertEqual(evidence["numerator"], 0.0)
        self.assertEqual(evidence["denominator"], 1.0)
        self.assertEqual(evidence["rate"], 0.0)
        operational = report["splits"]["development"]["operational"]["A"]
        self.assertEqual(operational["run_count"], 1)
        self.assertEqual(operational["latency_ms"]["p50"], 20.0)
        comparisons = report["cross_variant"]["comparisons"]
        semantic = next(item for item in comparisons if item["label"] == "semantic_uplift")
        evidence_delta = next(
            item for item in semantic["splits"][0]["metrics"] if item["name"] == "evidence_recall"
        )
        self.assertEqual(evidence_delta["delta"]["rate"], 1.0)
        self.assertEqual(evidence_delta["paired_n"], 1)
        self.assertIn("1/1", render_markdown(report))


def _tool_record(*direct_ids: str, expanded_ids: tuple[str, ...] = ()) -> ToolResultRecord:
    def _message(message_id: str) -> MessageProjection:
        return MessageProjection(
            internal_message_id=message_id,
            session_id="session:test",
            source_message_id=None,
            sender_user_id=None,
            sender_platform_id=None,
            sender_uin=None,
            sender_name="alice",
            timestamp=100,
            seq=None,
            message_type="text",
            normalized_content="hello",
            reply_to_source_message_id=None,
            recalled=False,
            system=False,
        )

    items = tuple(
        ToolMessageItem(result_item_id=f"item-{message_id}", message=_message(message_id), is_hit=True)
        for message_id in direct_ids
    ) + tuple(
        ToolMessageItem(result_item_id=f"item-{message_id}", message=_message(message_id), is_hit=False)
        for message_id in expanded_ids
    )
    return ToolResultRecord(
        run_id="run-1",
        tool_call_id="call-1",
        tool_result_id="result-1",
        tool_name="lexical_search",
        status="ok",
        scope_snapshot={"session": "session:test"},
        query_scope_snapshot={"session": "session:test"},
        message_items=items,
    )


def _claims_artifact() -> AnswerArtifact:
    return AnswerArtifact(
        content_blocks=(AnswerContentBlock("claim-1", "答案正文"),),
        citation_bindings=(CitationBinding("claim-1", ("e1",)),),
        evidence_items=(
            EvidenceItem(
                evidence_id="e1",
                finding="f",
                criterion="c",
                sufficiency="sufficient",
                sources=(EvidenceSource("supports", SourceHandleReference("m1-1")),),
            ),
        ),
    )


class ChecksProjectionTests(unittest.TestCase):
    """query_result_snapshot 的分层 retrieval/evidence 投影与 override check。"""

    def _result(self, records=(), artifact=None) -> QueryResult:
        return QueryResult(
            runtime_result=RuntimeResult(
                final_answer="答案" if artifact else None,
                provider="p",
                model="m",
                termination="completed",
                tool_calls=(RuntimeToolCall("lexical_search", "ok", tool_call_id="call-1", round=1),),
                tool_results=records,
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
            answer_artifact=artifact,
        )

    def test_retrieval_calls_layer_direct_and_expanded(self) -> None:
        result = self._result(records=(_tool_record("m1", "m2", expanded_ids=("m0",)),), artifact=_claims_artifact())
        snapshot = query_result_snapshot(result)
        calls = snapshot["retrieval_calls"]["calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([hit["internal_message_id"] for hit in calls[0]["direct_hits"]], ["m1", "m2"])
        self.assertEqual(calls[0]["direct_hits"][0]["rank"], 1)
        self.assertEqual(calls[0]["expanded_ids"], ["m0"])
        self.assertEqual(snapshot["answer_form"], "claims")

    def test_no_result_form_signature(self) -> None:
        artifact = AnswerArtifact(content_blocks=(AnswerContentBlock("answer", "没有找到相关内容"),))
        result = self._result(artifact=artifact)
        self.assertEqual(query_result_snapshot(result)["answer_form"], "no_result_signature")

    def test_failed_runtime_projection_does_not_claim_valid_finalization(self) -> None:
        """Runtime 未完成时，projection 必须保留 skipped 与真实 exception type。"""

        failed_runtime = replace(
            self._result().runtime_result,
            final_answer=None,
            termination="failed",
            error=RuntimeErrorInfo(
                code="RUNTIME_ERROR",
                message="runtime failed",
                category="terminal",
                exception_type="ProviderError",
            ),
        )
        snapshot = query_result_snapshot(replace(self._result(), runtime_result=failed_runtime))
        self.assertEqual(snapshot["finalization_status"], "skipped")
        self.assertEqual(snapshot["runtime"]["error"]["exception_type"], "ProviderError")

    def test_context_expansion_override_check(self) -> None:
        case = _case()
        variant = ControlledVariant(
            variant_id="bench-lexical-only-v1",
            code_version="commit:test",
            provider="test",
            model="test-model",
            execution_override=ExecutionOverride(forced_route=None, context_window_limit=0),
        )
        request = QueryRequest(query="q", scope=_SCOPE, execution_override=variant.execution_override)
        trace_with_violation = TraceProjection(
            trace_id="trace:t",
            request_id="request:test",
            profile="normal",
            started_at="2026-08-30T00:00:00+00:00",
            terminal_at="2026-08-30T00:00:01+00:00",
            terminal_status="completed",
            completeness="complete",
            timeline=(
                TraceTimelineItem(
                    sequence=1,
                    stage="retrieval",
                    operation="retrieval.search.completed",
                    phase="completed",
                    operation_id="op:retrieval",
                    parent_operation_id="op",
                    outcome="ok",
                    duration_ms=1.0,
                    limitations=(),
                    payload={"query": {"context_before": 2, "context_after": 2}},
                ),
            ),
            failures=(),
            metrics=TraceMetrics(1.0, {}, (), (), {}, 0, 0),
        )
        checks = run_deterministic_checks(
            case=case,
            snapshot=_SNAPSHOT,
            variant=variant,
            request=request,
            result=self._result(),
            trace=trace_with_violation,
        )
        override_checks = [item for item in checks if item.name == "context_expansion_override"]
        self.assertEqual(len(override_checks), 1)
        self.assertEqual(override_checks[0].status, "failed")

        compliant_trace = TraceProjection(
            trace_id="trace:t",
            request_id="request:test",
            profile="normal",
            started_at="2026-08-30T00:00:00+00:00",
            terminal_at="2026-08-30T00:00:01+00:00",
            terminal_status="completed",
            completeness="complete",
            timeline=(
                TraceTimelineItem(
                    sequence=1,
                    stage="retrieval",
                    operation="retrieval.search.completed",
                    phase="completed",
                    operation_id="op:retrieval",
                    parent_operation_id="op",
                    outcome="ok",
                    duration_ms=1.0,
                    limitations=(),
                    payload={"query": {"context_before": 0, "context_after": 0}},
                ),
            ),
            failures=(),
            metrics=TraceMetrics(1.0, {}, (), (), {}, 0, 0),
        )
        checks = run_deterministic_checks(
            case=case,
            snapshot=_SNAPSHOT,
            variant=variant,
            request=request,
            result=self._result(),
            trace=compliant_trace,
        )
        override_checks = [item for item in checks if item.name == "context_expansion_override"]
        self.assertEqual(override_checks[0].status, "passed")


class _ContextRecordingRuntime:
    """记录 AgentRunRequest 的 context_window_limit，返回显式失败结果。"""

    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return RuntimeResult(final_answer=None, provider="p", model="m", termination="failed", tool_calls=())


class EnvironmentAndIntegrationTests(unittest.TestCase):
    """environment manifest round-trip、gate 与 Runner 集成（override 贯通）。"""

    def test_manifest_round_trip_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "canonical.sqlite3"
            with create_application(database_path):
                # fixture DB 默认没有 messages_fts；benchmark gate 要求 lexical index 存在。
                connection = sqlite3.connect(database_path)
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE messages_fts USING fts5(
                        internal_message_id UNINDEXED,
                        session_id UNINDEXED,
                        source_message_id UNINDEXED,
                        content_text,
                        tokenize = 'unicode61'
                    )
                    """
                )
                connection.commit()
                connection.close()
                snapshot = DatasetSnapshot.from_database(database_path)
            manifest = capture_environment(
                benchmark="resume-benchmark-test",
                database_path=database_path,
                snapshot=snapshot,
                semantic_index_identity="semantic-index:test",
                git_commit="0" * 40,
            )
            path = Path(directory) / "environment.json"
            manifest.to_json(path)
            loaded = BenchmarkEnvironmentManifest.from_json(path)
            self.assertEqual(loaded.semantic_index, "semantic-index:test")
            passed = verify_environment(
                loaded,
                database_path=database_path,
                snapshot=DatasetSnapshot.from_database(database_path),
                semantic_index_identity="semantic-index:test",
                git_commit=loaded.git_commit,
            )
            self.assertTrue(passed.passed)
            failed = verify_environment(
                loaded,
                database_path=database_path,
                snapshot=DatasetSnapshot.from_database(database_path),
                semantic_index_identity="semantic-index:other",
                git_commit=loaded.git_commit,
            )
            self.assertFalse(failed.passed)

    def test_override_flows_to_runtime_request(self) -> None:
        runtime = _ContextRecordingRuntime()
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "canonical.sqlite3"
            with create_application(
                database_path,
                agent_runtime=runtime,
                evaluation_database_path=Path(directory) / "evaluation.sqlite3",
            ) as application:
                snapshot = DatasetSnapshot.from_database(database_path)
                case = _case()
                case = EvaluationCaseBundle(
                    case_id=case.case_id,
                    version=case.version,
                    suite_tags=case.suite_tags,
                    dataset_snapshot=snapshot,
                    data_access_scope=case.data_access_scope,
                    query=case.query,
                    reference_findings=case.reference_findings,
                )
                variant = ControlledVariant(
                    variant_id="bench-lexical-only-v1",
                    code_version="commit:test",
                    provider="test",
                    model="test-model",
                    execution_override=ExecutionOverride(forced_route=None, context_window_limit=0),
                )
                asyncio.run(application.evaluate_case(case, variant))
            self.assertEqual(runtime.requests[0].context_window_limit, 0)
            self.assertEqual(runtime.requests[0].available_capabilities, ("search_messages",))

    def test_gate_two_freeze_records_case_and_variant_identity(self) -> None:
        """冻结记录必须能发现 Case GT 或 Variant 配置的漂移。"""

        finding = _finding("relevant", "gt.relevant", "x", (_message_evidence("m1"),))
        adjudicated_provenance = replace(_provenance(), adjudicated=True)
        adjudicated_evidence = replace(finding.reference_evidence[0], provenance=adjudicated_provenance)
        adjudicated_finding = replace(
            finding,
            provenance=adjudicated_provenance,
            reference_evidence=(adjudicated_evidence,),
        )
        case = _case((adjudicated_finding,))
        case = replace(case, provenance=replace(case.provenance, notes="human adjudication: Accept"))
        suite = EvaluationSuite(
            suite_id="resume-benchmark-test",
            version=1,
            kind="core",
            case_references=(CaseReference(case.case_id, case.version),),
            description="test suite",
            created_at="2026-08-31T00:00:00+00:00",
        )
        variant = ControlledVariant(
            variant_id="bench-test",
            code_version="commit:test",
            provider="test",
            model="test-model",
        )
        variants = tuple(replace(variant, variant_id=f"bench-test-{index}") for index in range(5))
        environment = BenchmarkEnvironmentManifest(
            benchmark="resume-benchmark-test",
            canonical_snapshot_id=_SNAPSHOT.snapshot_id,
            lexical_index={"present": True, "message_count": 3},
            semantic_index="semantic-index:test",
            git_commit="commit:test",
            created_at="2026-08-31T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            holdout_dir = Path(directory) / "holdout"
            record = capture_freeze_record(
                benchmark="resume-benchmark-test",
                execution_commit="commit:test",
                frozen_at="2026-08-31T00:00:00+00:00",
                suite=suite,
                dev_cases={case.case_id: case},
                calibration_cases={},
                variants=variants,
                environment=environment,
                holdout_dir=holdout_dir,
            )
            self.assertEqual(record.ordered_dev_case_identities, (case.identity,))
            self.assertEqual(record.gt_adjudication["accept"], 1)
            passed = verify_freeze_record(
                record,
                suite=suite,
                dev_cases={case.case_id: case},
                calibration_cases={},
                variants=variants,
                environment=environment,
                holdout_dir=holdout_dir,
            )
            self.assertTrue(passed.passed)
            drifted_case = replace(case, query="drifted query")
            drifted = verify_freeze_record(
                record,
                suite=suite,
                dev_cases={drifted_case.case_id: drifted_case},
                calibration_cases={},
                variants=variants,
                environment=environment,
                holdout_dir=holdout_dir,
            )
            self.assertFalse(drifted.passed)


if __name__ == "__main__":
    unittest.main()


class TraceLimitationBoundTests(unittest.TestCase):
    """大命中数下 trace_limitations 归一化且有界（pilot 发现的回归）。"""

    def test_projection_path_limitations_are_normalized_and_bounded(self) -> None:
        from trivae.evaluation.checks import operational_measurements

        timeline = tuple(
            TraceTimelineItem(
                sequence=index,
                stage="runtime",
                operation="model.turn",
                phase="completed",
                operation_id=f"turn-{index}",
                parent_operation_id=None,
                outcome="ok",
                duration_ms=1.0,
                limitations=tuple(f"payload.model_visible_context[4].output_projection.data.hits[{i}].truncated" for i in range(300)),
                payload={},
            )
            for index in range(1, 3)
        )
        trace = TraceProjection(
            trace_id="trace:t",
            request_id="request:test",
            profile="normal",
            started_at="2026-08-30T00:00:00+00:00",
            terminal_at="2026-08-30T00:00:01+00:00",
            terminal_status="completed",
            completeness="complete",
            timeline=timeline,
            failures=(),
            metrics=TraceMetrics(1.0, {}, (), (), {}, 0, 0),
        )
        measurements = operational_measurements(None, trace)
        self.assertLessEqual(len(measurements["trace_limitations"]), 200)
        self.assertEqual(
            measurements["trace_limitations"],
            ("payload.model_visible_context[].output_projection.data.hits[].truncated",),
        )


class CaseAuditTests(unittest.TestCase):
    """GT 机器审计回归：存在性、zero-result 蕴含、category 形态、正文泄露、holdout 隔离。"""

    def _fixture_db(self, directory: Path) -> Path:
        database_path = directory / "canonical.sqlite3"
        with create_application(database_path):
            connection = sqlite3.connect(database_path)
            connection.execute(
                "INSERT INTO messages(internal_message_id, session_id, platform, source_message_id, seq, timestamp,"
                " message_type, content_text, content_json, raw_payload_json, canonical_projection_json,"
                " canonical_source_id, canonical_source_record_index, reply_to_source_message_id, recalled, system)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "m-1", "session:t", "qq", "s-1", 1, 1750000000000, "text",
                    "https://github.com/example/repo 是个好项目",
                    "{}", "{}", "{}", "source:test", 0, None, 0, 0,
                ),
            )
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                "internal_message_id UNINDEXED, session_id UNINDEXED, source_message_id UNINDEXED,"
                " content_text, tokenize = 'unicode61')"
            )
            connection.commit()
            connection.close()
        return database_path

    def _case_file(self, directory: Path, name: str, findings, *, query: str = "test?", tags=("category:exact_lexical",)) -> Path:
        from trivae.evaluation.contracts import DatasetSnapshot

        snapshot = DatasetSnapshot(
            snapshot_id="snapshot:audit-test",
            canonical_database_identity="sqlite-canonical:test",
            schema_version="canonical-m1-v1",
            source_identity="source:test",
            message_count=1,
            relevant_time_range=(1750000000000, 1750000000000),
            deterministic_fingerprint="manifest:audit-test",
            created_at="2026-08-31T00:00:00+00:00",
            manifest={"message_count": 1},
        )
        payload = {
            "schema_version": 1,
            "case_id": name,
            "version": 1,
            "suite_tags": list(tags),
            "dataset_snapshot": snapshot.to_dict(),
            "data_access_scope": {"allowed_session_ids": None, "start_timestamp": None, "end_timestamp": None, "max_results": 20},
            "query": query,
            "locale": "zh-CN",
            "reference_findings": [finding.to_dict() for finding in findings],
            "uncertainty_constraints": [],
            "negative_constraints": [],
            "critical_requirements": [],
            "diagnostic_expectations": None,
            "review_policy": {"rubric_version": "m7-v1", "reviewer_types": ["human"], "blind_pairwise": True, "human_adjudication_on_disagreement": True},
            "provenance": {"source": "test", "method": "test", "created_at": "2026-08-31T00:00:00+00:00"},
        }
        path = directory / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _finding(self, finding_id: str, criterion: str, semantics: str, evidence_ids=(), completeness="exhaustive", adjudicated=False, method="deterministic LIKE scan; hit_count=1"):
        from trivae.evaluation.benchmark.gt import build_case_ground_truth  # noqa: F401
        from trivae.evaluation.contracts import ReferenceEvidence, ReferenceFinding, ReferenceProvenance

        provenance = ReferenceProvenance(
            source="t", created_at="2026-08-31T00:00:00+00:00", method=method,
            snapshot_id="snapshot:audit-test",
            scope_identity='{"allowed_session_ids":null,"end_timestamp":null,"max_results":20,"start_timestamp":null}',
            adjudicated=adjudicated,
        )
        evidence = tuple(
            ReferenceEvidence(
                evidence_id=f"ev:{mid}", relation="supports" if criterion == "gt.relevant" else "context",
                source_type="message", locator={"internal_message_id": mid}, why_relevant="t", provenance=provenance,
            )
            for mid in evidence_ids
        )
        return ReferenceFinding(
            finding_id=finding_id, criterion=criterion, expected_semantics=semantics,
            reference_evidence=evidence, annotation_completeness=completeness, provenance=provenance,
        )

    def test_valid_case_passes_and_leak_detected(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "ok-case",
                (
                    self._finding("relevant", "gt.relevant", "messages with repo", ["m-1"]),
                    self._finding("zero", "gt.expected_zero_result", "false"),
                    self._finding("fact", "gt.expected_fact", '["github.com/example/repo"]'),
                ),
                query="谁分享过 example/repo？",
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertTrue(result["passed"], result["findings"])

            # 正文泄露：把消息原文塞进 why_relevant 必须被抓到
            leaking = self._case_file(
                cases_dir, "leak-case",
                (
                    self._finding(
                        "relevant", "gt.relevant", "x", ["m-1"],
                    ),
                ),
            )
            payload = json.loads(leaking.read_text())
            # 直接把消息原文整段粘进 why_relevant——即真实泄露形态。
            payload["reference_findings"][0]["reference_evidence"][0]["why_relevant"] = (
                "https://github.com/example/repo 是个好项目"
            )
            leaking.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertFalse(result["passed"])
            self.assertTrue(any(f["detail"].startswith("content_leak") for f in result["findings"]))

    def test_missing_message_and_holdout_isolation(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "missing-msg",
                (
                    self._finding("relevant", "gt.relevant", "x", ["m-404"]),
                    self._finding("zero", "gt.expected_zero_result", "false"),
                ),
            )
            holdout = root / "holdout"
            holdout.mkdir()
            (holdout / "case.json").write_text("{}", encoding="utf-8")
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=holdout)
            result = audit.audit()
            audit.close()
            details = {item["detail"].split(":")[0] for item in result["findings"]}
            self.assertIn("missing_message", details)
            self.assertIn("holdout_dir_exists_before_freeze", details)
            self.assertFalse(result["passed"])

    def test_category_shape_enforced(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "bad-paraphrase",
                (
                    self._finding("relevant", "gt.relevant", "x", ["m-1"]),
                    self._finding("zero", "gt.expected_zero_result", "false"),
                ),
                tags=("category:semantic_paraphrase",),
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertTrue(any("paraphrase must not claim exhaustive" in item["detail"] for item in result["findings"]))

    def test_partial_target_predicate_case_passes(self) -> None:
        """语义类 query + target repo 出现集合：partial 合法且 occurrence set 必须重扫一致。"""
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "partial-target",
                (
                    self._finding("relevant", "gt.relevant", "target repo occurrence set", ["m-1"], completeness="partial", adjudicated=True),
                    self._finding("zero", "gt.expected_zero_result", "false", adjudicated=True),
                    self._finding("fact", "gt.expected_fact", '["example/repo"]', adjudicated=True),
                ),
                query="有没有人分享过 example/repo 这类好项目？",
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertEqual(result["findings"], [])
            self.assertEqual(result["adjudicated_case_count"], 1)
            self.assertTrue(result["passed"])

    def test_partial_target_occurrence_mismatch_detected(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "partial-mismatch",
                (
                    self._finding("relevant", "gt.relevant", "target set drift", ["m-1"], completeness="partial", adjudicated=True),
                    self._finding("zero", "gt.expected_zero_result", "false", adjudicated=True),
                    self._finding("fact", "gt.expected_fact", '["zzz-unknown-token"]', adjudicated=True),
                ),
                query="有没有人分享过 zzz-unknown-token？",
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertTrue(any(item["detail"].startswith("occurrence_set_mismatch") for item in result["findings"]))
            self.assertFalse(result["passed"])

    def test_zero_result_iso_date_requires_explicit_utc(self) -> None:
        """ISO 日期 zero-result：窗口重扫 + 裸日期（未声明 UTC）出 warning。"""
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            # fixture 消息在 2025-06-15 UTC；2024-01-01 UTC 是真实空窗。
            self._case_file(
                cases_dir, "zero-utc",
                (self._finding("zero", "gt.expected_zero_result", "true", adjudicated=True),),
                query="按 UTC 时间算，2024-01-01 这天有没有消息？",
                tags=("category:zero_result",),
            )
            self._case_file(
                cases_dir, "zero-bare",
                (self._finding("zero", "gt.expected_zero_result", "true", adjudicated=True),),
                query="2024年1月1日当天有没有消息？",
                tags=("category:zero_result",),
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            warnings = {item["case_id"]: item["detail"] for item in result["findings"] if item["severity"] == "warning"}
            self.assertNotIn("zero-utc", warnings)
            self.assertEqual(warnings.get("zero-bare"), "zero_result_bare_date_without_utc")
            self.assertTrue(result["passed"])

    def test_zero_result_token_rescan(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            finding = self._finding(
                "zero", "gt.expected_zero_result", "true", adjudicated=True,
                method="LIKE scan for token 'example' = 0 (deterministic)",
            )
            self._case_file(
                cases_dir, "zero-token-hit",
                (finding,),
                query="有没有人提到过 example？",
                tags=("category:zero_result",),
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertTrue(any(item["detail"].startswith("zero_result_token_hit_present") for item in result["findings"]))
            self.assertFalse(result["passed"])

    def test_unadjudicated_case_warns(self) -> None:
        from trivae.evaluation.benchmark.audit import CaseAudit

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = self._fixture_db(root)
            cases_dir = root / "cases"
            cases_dir.mkdir()
            self._case_file(
                cases_dir, "not-adjudicated",
                (
                    self._finding("relevant", "gt.relevant", "x", ["m-1"]),
                    self._finding("zero", "gt.expected_zero_result", "false"),
                    self._finding("fact", "gt.expected_fact", '["example/repo"]'),
                ),
                query="谁分享过 example/repo？",
            )
            audit = CaseAudit(database_path=database_path, case_dirs=(cases_dir,), holdout_dir=root / "holdout")
            result = audit.audit()
            audit.close()
            self.assertEqual(result["adjudicated_case_count"], 0)
            self.assertTrue(any(item["detail"] == "case_not_adjudicated" for item in result["findings"]))
            # 裁决前审计允许 provisional：warning 不使 audit 失败。
            self.assertTrue(result["passed"])
