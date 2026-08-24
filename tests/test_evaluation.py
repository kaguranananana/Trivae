"""M7 Evaluation contract、生产链路复用与独立 Store 回归。"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.evaluation import (
    CaseProvenance,
    CaseReference,
    ControlledVariant,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationReview,
    EvaluationRunner,
    EvaluationSuite,
    ReferenceEvidence,
    ReferenceFinding,
    ReferenceProvenance,
    ReviewPacket,
    SQLiteEvaluationStore,
    create_failure_diagnosis,
    create_paired_comparison,
    run_deterministic_checks,
    run_judge,
    scope_identity,
)
from trivae.evaluation.checks import operational_measurements, query_result_snapshot
from trivae.observability.contracts import TraceMetrics, TraceProjection, TraceTimelineItem
from trivae.query.contracts import ExecutionOverride, QueryRequest, QueryResult
from trivae.query.evidence import FinalizationErrorInfo, ToolResultRecord
from trivae.query.planner import Plan, PlannerResult, PlanStep
from trivae.query.router import RouteDecision
from trivae.query.runtime.contracts import RuntimeResult, RuntimeToolCall


def _snapshot(snapshot_id: str = "snapshot:test") -> DatasetSnapshot:
    """构造不含聊天正文的确定性测试 Snapshot。"""

    return DatasetSnapshot(
        snapshot_id=snapshot_id,
        canonical_database_identity="sqlite-canonical:test",
        schema_version="canonical-m1-v1",
        source_identity="source:test",
        message_count=3,
        relevant_time_range=(100, 300),
        deterministic_fingerprint="manifest:test",
        created_at="2026-08-23T00:00:00+00:00",
        manifest={"message_count": 3},
    )


def _case(snapshot: DatasetSnapshot | None = None, case_id: str = "case-test") -> EvaluationCaseBundle:
    """建立带多态 Reference Finding 的最小 Case Bundle。"""

    effective_snapshot = snapshot or _snapshot()
    scope = ExecutionScope(allowed_session_ids=("session:test",), max_results=5)
    provenance = ReferenceProvenance(
        source="human:test",
        created_at="2026-08-23T00:00:00+00:00",
        method="manual enumeration",
        snapshot_id=effective_snapshot.snapshot_id,
        scope_identity=scope_identity(scope),
    )
    evidence = ReferenceEvidence(
        evidence_id="evidence-1",
        relation="supports",
        source_type="message",
        locator={"message_id": "message:test"},
        why_relevant="该消息直接支持 finding criterion。",
        provenance=provenance,
    )
    finding = ReferenceFinding(
        finding_id="finding-1",
        criterion="关键词是否在指定 session 出现",
        expected_semantics="应报告出现与否，并保留来源关系。",
        reference_evidence=(evidence,),
        annotation_completeness="partial",
        provenance=provenance,
        known_limitations=("只标记已知代表性消息。",),
        critical=True,
    )
    return EvaluationCaseBundle(
        case_id=case_id,
        version=1,
        suite_tags=("core", "simple_keyword_retrieval"),
        dataset_snapshot=effective_snapshot,
        data_access_scope=scope,
        query="查找关键词并说明证据。",
        reference_findings=(finding,),
        uncertainty_constraints=("证据不完整时必须明确说明。",),
        negative_constraints=("不得引用 scope 外消息。",),
        critical_requirements=("保留 citation provenance。",),
        provenance=CaseProvenance("test", "fixture", "2026-08-23T00:00:00+00:00"),
    )


def _variant(route: str | None = None, variant_id: str = "variant-test") -> ControlledVariant:
    """构造不含 secret 的 Variant；forced route 只作为实验条件。"""

    return ControlledVariant(
        variant_id=variant_id,
        code_version="commit:test",
        provider="test-provider",
        model="test-model",
        role="forced_standard" if route == "standard_execution" else "candidate",
        prompt_identity="prompt:test-v1",
        router_configuration={"implementation": "rule-router"},
        planner_configuration={"implementation": "soft-planner"},
        runtime_configuration={"trace_profile": "normal"},
        retrieval_configuration={"strategy": "lexical"},
        index_identity="index:test",
        evidence_citation_version="m5:test",
        budget={"max_turns": 4},
        execution_override=ExecutionOverride(route),
    )


def _trace(trace_id: str = "trace:test", status: str = "failed") -> TraceProjection:
    """构造最小 Trace projection，明确 terminal 与 QueryResult 对齐。"""

    return TraceProjection(
        trace_id=trace_id,
        request_id="request:test",
        profile="normal",
        started_at="2026-08-23T00:00:00+00:00",
        terminal_at="2026-08-23T00:00:01+00:00",
        terminal_status=status,
        completeness="complete",
        timeline=(),
        failures=(),
        metrics=TraceMetrics(1.0, {}, (), (), {}, 0, 0),
    )


class _FailedExecutor:
    """只返回显式失败，验证 Runner 不会把 Query failure 包装成成功。"""

    def __init__(self) -> None:
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return QueryResult(
            runtime_result=RuntimeResult(
                final_answer=None,
                provider="test-provider",
                model="test-model",
                termination="failed",
                tool_calls=(),
            ),
            route_decision=RouteDecision(
                route="standard_execution",
                confidence=1.0,
                source="evaluation_override",
                reason="forced test route",
            ),
            trace_id="trace:test",
        )


class _RecordingRuntime:
    """Application 集成测试使用的生产 Runtime 替身。"""

    def __init__(self) -> None:
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return RuntimeResult(
            final_answer=None,
            provider="test-provider",
            model="test-model",
            termination="failed",
            tool_calls=(),
        )


class _RejectingRouter:
    """forced route 测试中若 Router 被调用就显式失败。"""

    def __init__(self) -> None:
        self.calls = 0

    async def route(self, context):
        self.calls += 1
        raise AssertionError("forced Evaluation route must bypass Router")


class EvaluationContractTests(unittest.TestCase):
    """验证 Case、Snapshot、Variant 和 Suite 的稳定身份。"""

    def test_case_round_trip_and_version_identity(self) -> None:
        case = _case()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            case.to_json(path)
            restored = EvaluationCaseBundle.from_json(path)
        self.assertEqual(restored, case)
        self.assertEqual(restored.identity, "case-test@v1")
        self.assertEqual(restored.reference_findings[0].annotation_completeness, "partial")

    def test_invalid_case_version_completeness_and_reference_are_rejected(self) -> None:
        payload = _case().to_dict()
        payload["schema_version"] = 2
        with self.assertRaises(EvaluationContractError):
            EvaluationCaseBundle.from_dict(payload)

        finding = payload["reference_findings"][0]
        assert isinstance(finding, dict)
        finding["annotation_completeness"] = "guessed"
        with self.assertRaises(EvaluationContractError):
            EvaluationCaseBundle.from_dict(payload)

        evidence = finding["reference_evidence"][0]
        assert isinstance(evidence, dict)
        evidence["locator"] = {}
        with self.assertRaises(EvaluationContractError):
            EvaluationCaseBundle.from_dict(payload)

        mismatched = _case().to_dict()
        mismatched_finding = mismatched["reference_findings"][0]
        assert isinstance(mismatched_finding, dict)
        mismatched_provenance = mismatched_finding["provenance"]
        assert isinstance(mismatched_provenance, dict)
        mismatched_provenance["snapshot_id"] = "snapshot:other"
        with self.assertRaises(EvaluationContractError):
            EvaluationCaseBundle.from_dict(mismatched)

    def test_snapshot_identity_is_stable_and_changes_with_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_path = Path(directory) / "first.sqlite3"
            second_path = Path(directory) / "second.sqlite3"
            for path in (first_path, second_path):
                connection = sqlite3.connect(path)
                connection.executescript(
                    """
                    CREATE TABLE sources(source_id TEXT PRIMARY KEY, file_name TEXT, adapter TEXT, format_version TEXT,
                        platform TEXT, external_chat_id TEXT, chat_name TEXT, created_at TEXT);
                    CREATE TABLE messages(message_id TEXT PRIMARY KEY, timestamp INTEGER);
                    CREATE TABLE import_batches(batch_id TEXT PRIMARY KEY);
                    """
                )
                connection.commit()
                connection.close()
            first = DatasetSnapshot.from_database(first_path)
            again = DatasetSnapshot.from_database(first_path)
            self.assertEqual(first.snapshot_id, again.snapshot_id)
            connection = sqlite3.connect(second_path)
            connection.execute(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("source-1", "fixture.json", "test", "1", "qq", "chat", "fixture", "now"),
            )
            connection.commit()
            connection.close()
            second = DatasetSnapshot.from_database(second_path)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        for status in ("invalid", "restricted", "unavailable"):
            marked = replace(first, status=status)
            self.assertEqual(marked.status, status)

    def test_variant_fingerprint_is_stable_and_secret_is_rejected(self) -> None:
        first = _variant()
        second = _variant()
        self.assertEqual(first.fingerprint, second.fingerprint)
        with self.assertRaises(EvaluationContractError):
            ControlledVariant(
                variant_id="bad",
                code_version="commit:test",
                provider="test",
                model="model",
                extra_configuration={"api_key": "secret"},
            )

    def test_suite_references_case_version_without_copying_truth(self) -> None:
        suite = EvaluationSuite(
            suite_id="suite-test",
            version=1,
            kind="core",
            case_references=(
                # Suite 只保存 identity，不复制 Finding 或 Answer truth。
                CaseReference("case-test", 1),
            ),
            description="test suite",
            created_at="2026-08-23T00:00:00+00:00",
        )
        self.assertEqual(suite.identity, "suite-test@v1")
        self.assertEqual(suite.to_dict()["cases"], [{"case_id": "case-test", "version": 1}])

    def test_agent_tool_behavior_is_recorded_as_observation_not_quality_judgement(self) -> None:
        """Evaluation 保存 visible/selected sequence，preferred tool 仍留给诊断与 Review。"""

        result = QueryResult(
            runtime_result=RuntimeResult(
                final_answer=None,
                provider="test-provider",
                model="test-model",
                termination="failed",
                tool_calls=(
                    RuntimeToolCall("lexical_search", "ok", round=1),
                    RuntimeToolCall("semantic_search", "error", error_code="CAPABILITY_UNAVAILABLE", round=2),
                ),
                tool_rounds=2,
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
        )

        snapshot = query_result_snapshot(result)
        measurements = operational_measurements(result, None)

        self.assertEqual(
            snapshot["runtime"]["tool_behavior"],
            {
                "first_selected_tool": "lexical_search",
                "tool_sequence": ["lexical_search", "semantic_search"],
                "retrieval_tool_sequence": ["lexical_search", "semantic_search"],
                "tool_call_count": 2,
                "tool_rounds": 2,
                "tool_errors": [
                    {
                        "name": "semantic_search",
                        "status": "error",
                        "error_code": "CAPABILITY_UNAVAILABLE",
                    }
                ],
            },
        )
        self.assertEqual(measurements["agent_tool_behavior"]["tool_rounds"], 2)
        self.assertNotIn("human_verified", measurements["agent_tool_behavior"])


class EvaluationRunnerTests(unittest.TestCase):
    """验证 Runner 只调用生产 callable、保存单次 Run 并保留失败。"""

    def test_runner_repetitions_and_store_reopen(self) -> None:
        executor = _FailedExecutor()
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "evaluation.sqlite3"
            store = SQLiteEvaluationStore(database_path)
            runner = EvaluationRunner(
                query_executor=executor,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot(),
            )
            runs = asyncio.run(runner.run_case(_case(), _variant("standard_execution"), repetitions=2))
            self.assertEqual(len(runs), 2)
            self.assertEqual(len(executor.requests), 2)
            self.assertEqual(executor.requests[0].execution_override.forced_route, "standard_execution")
            self.assertTrue(all(run.terminal_status == "failed" for run in runs))
            first_id = runs[0].run_id
            store.close()
            reopened = SQLiteEvaluationStore(database_path)
            restored = reopened.get_run(first_id)
            reopened.close()
        self.assertEqual(restored.run_id, first_id)
        self.assertEqual(restored.trace_id, "trace:test")

    def test_runner_exception_is_persisted_and_re_raised(self) -> None:
        async def raise_query(request):
            error = RuntimeError("provider failure")
            setattr(error, "trace_id", "trace:exception")
            raise error

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEvaluationStore(Path(directory) / "evaluation.sqlite3")
            runner = EvaluationRunner(
                query_executor=raise_query,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot(),
            )
            with self.assertRaises(RuntimeError):
                asyncio.run(runner.run_case(_case(), _variant(), repetitions=1))
            persisted = store.list_runs()
            store.close()
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].terminal_status, "exception")
        self.assertEqual(persisted[0].exception_type, "RuntimeError")
        self.assertEqual(persisted[0].trace_id, "trace:exception")

    def test_store_persists_result_review_and_diagnosis_across_reopen(self) -> None:
        executor = _FailedExecutor()
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "evaluation.sqlite3"
            store = SQLiteEvaluationStore(database_path)
            runner = EvaluationRunner(
                query_executor=executor,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot(),
            )
            run = asyncio.run(runner.run_case(_case(), _variant()))[0]
            review = EvaluationReview(
                review_id="review:test",
                run_id=run.run_id,
                reviewer_type="human",
                rubric_version="m7-v1",
                quality_axes={"task_finding_correctness": {"label": "needs_review", "confidence": 0.5}},
                confidence=0.5,
                notes="人工 Review contract smoke。",
                disagreement=None,
                needs_adjudication=False,
                created_at="2026-08-23T00:00:00+00:00",
            )
            store.save_review(review)
            diagnosis = create_failure_diagnosis(
                run_id=run.run_id,
                primary_cause="runtime",
                contributing_factors=("scripted failure",),
                evidence_references=("check:query_terminal_state",),
                trace_event_references=("trace:test",),
                confidence=0.9,
                status="confirmed",
            )
            store.save_diagnosis(diagnosis)
            result = store.get_result(f"result:{run.run_id}")
            store.close()
            reopened = SQLiteEvaluationStore(database_path)
            restored_review = reopened.get_review(review.review_id)
            restored_diagnosis = reopened.get_diagnosis(diagnosis.diagnosis_id)
            reopened.close()
        self.assertEqual(result.run_id, run.run_id)
        self.assertEqual(restored_review.reviewer_type, "human")
        self.assertEqual(restored_diagnosis.status, "confirmed")

    def test_limitation_check_maps_trace_payload_facts_without_mutating_trace(self) -> None:
        case = _case()
        request = QueryRequest(case.query, case.data_access_scope)
        tool_record = ToolResultRecord(
            run_id="run:limitation",
            tool_call_id="run:limitation/tool/1",
            tool_result_id="run:limitation/tool/1/result",
            tool_name="search_messages",
            status="partial",
            scope_snapshot={"max_results": 1},
            query_scope_snapshot={},
            limitations=("tool_result_partial", "retrieval_partial", "retrieval_truncated"),
        )
        result = QueryResult(
            runtime_result=RuntimeResult(
                final_answer=None,
                provider="test-provider",
                model="test-model",
                termination="failed",
                tool_calls=(),
                tool_results=(tool_record,),
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
        )
        trace = TraceProjection(
            trace_id="trace:limitation",
            request_id="request:limitation",
            profile="normal",
            started_at="2026-08-23T00:00:00+00:00",
            terminal_at="2026-08-23T00:00:01+00:00",
            terminal_status="failed",
            completeness="complete",
            timeline=(
                TraceTimelineItem(
                    sequence=1,
                    stage="retrieval",
                    operation="retrieval.search.completed",
                    phase="completed",
                    operation_id="retrieval",
                    parent_operation_id=None,
                    outcome="partial",
                    duration_ms=1.0,
                    limitations=(),
                    payload={"partial": True, "truncated": True},
                ),
            ),
            failures=(),
            metrics=TraceMetrics(1.0, {}, (), (), {}, 0, 1),
        )
        checks = run_deterministic_checks(
            case=case,
            snapshot=case.dataset_snapshot,
            variant=_variant(),
            request=request,
            result=result,
            trace=trace,
        )
        limitation_check = next(check for check in checks if check.name == "limitation_preservation")
        self.assertEqual(limitation_check.status, "passed")

    def test_invalid_citation_is_a_hard_deterministic_failure(self) -> None:
        case = _case()
        result = QueryResult(
            runtime_result=RuntimeResult(
                final_answer='{"answer":"candidate"}',
                provider="test-provider",
                model="test-model",
                termination="completed",
                tool_calls=(),
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
            finalization_error=FinalizationErrorInfo("UNRESOLVED_MESSAGE_SOURCE", "invalid source"),
        )
        checks = run_deterministic_checks(
            case=case,
            snapshot=case.dataset_snapshot,
            variant=_variant(),
            request=QueryRequest(case.query, case.data_access_scope),
            result=result,
            trace=_trace("trace:invalid-citation", "failed"),
        )
        citation_check = next(check for check in checks if check.name == "citation_provenance")
        self.assertEqual(citation_check.status, "failed")
        self.assertEqual(citation_check.severity, "hard")


class ApplicationEvaluationTests(unittest.TestCase):
    """验证 Evaluation facade 进入生产 QueryOrchestrator，而非第二套 Runtime。"""

    def test_forced_standard_bypasses_router_and_trace_keeps_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "canonical.sqlite3"
            runtime = _RecordingRuntime()
            router = _RejectingRouter()
            with create_application(
                database_path,
                agent_runtime=runtime,
                router=router,
                evaluation_database_path=Path(directory) / "evaluation.sqlite3",
            ) as application:
                snapshot = DatasetSnapshot.from_database(database_path)
                case = _case(snapshot)
                runs = asyncio.run(application.evaluate_case(case, _variant("standard_execution")))
                trace = application.read_trace(runs[0].trace_id or "")
            self.assertEqual(router.calls, 0)
            self.assertEqual(len(runtime.requests), 1)
            self.assertEqual(runtime.requests[0].query, case.query)
            self.assertEqual(runs[0].execution_override["forced_route"], "standard_execution")
            self.assertTrue(any(item.operation == "router.bypassed" for item in trace.timeline))
            connection = sqlite3.connect(database_path)
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            connection.close()
            self.assertNotIn("evaluation_runs", table_names)

    def test_forced_planned_invokes_existing_planner(self) -> None:
        class RecordingPlanner:
            def __init__(self) -> None:
                self.calls = 0

            async def plan(self, context):
                self.calls += 1
                return PlannerResult(
                    Plan(1, "test", "evidence", (PlanStep("inspect"),), ("answer",)),
                )

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "canonical.sqlite3"
            runtime = _RecordingRuntime()
            router = _RejectingRouter()
            planner = RecordingPlanner()
            with create_application(
                database_path,
                agent_runtime=runtime,
                router=router,
                planner=planner,
                evaluation_database_path=Path(directory) / "evaluation.sqlite3",
            ) as application:
                snapshot = DatasetSnapshot.from_database(database_path)
                runs = asyncio.run(application.evaluate_case(_case(snapshot), _variant("planned_execution")))
            self.assertEqual(router.calls, 0)
            self.assertEqual(planner.calls, 1)
            self.assertEqual(runs[0].execution_override["forced_route"], "planned_execution")


class ComparisonTests(unittest.TestCase):
    """比较只接受同 Case/Snapshot/Scope，并保留单次 Run identity。"""

    def test_different_snapshot_is_rejected(self) -> None:
        case = _case(_snapshot("snapshot:a"))
        baseline = _FailedExecutor()
        candidate = _FailedExecutor()
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEvaluationStore(Path(directory) / "evaluation.sqlite3")
            runner = EvaluationRunner(
                query_executor=baseline,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot("snapshot:a"),
            )
            baseline_runs = asyncio.run(runner.run_case(case, _variant(variant_id="baseline")))
            candidate_case = _case(_snapshot("snapshot:b"))
            candidate_runner = EvaluationRunner(
                query_executor=candidate,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot("snapshot:b"),
            )
            candidate_runs = asyncio.run(candidate_runner.run_case(candidate_case, _variant(variant_id="candidate")))
            with self.assertRaises(EvaluationContractError):
                create_paired_comparison(
                    case=case,
                    baseline_variant=_variant(variant_id="baseline"),
                    candidate_variant=_variant(variant_id="candidate"),
                    baseline_runs=baseline_runs,
                    candidate_runs=candidate_runs,
                    randomization_seed="seed:test",
                )
            store.close()

    def test_same_case_snapshot_scope_comparison_persists_blind_assignment(self) -> None:
        executor = _FailedExecutor()
        case = _case()
        baseline_variant = _variant(variant_id="baseline")
        candidate_variant = replace(
            _variant(variant_id="candidate"),
            model_parameters={"temperature": 0, "top_p": 0.9},
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "evaluation.sqlite3"
            store = SQLiteEvaluationStore(database_path)
            runner = EvaluationRunner(
                query_executor=executor,
                trace_reader=lambda trace_id: _trace(trace_id),
                store=store,
                snapshot_resolver=lambda: _snapshot(),
            )
            baseline_runs = asyncio.run(runner.run_case(case, baseline_variant))
            candidate_runs = asyncio.run(runner.run_case(case, candidate_variant))
            comparison = create_paired_comparison(
                case=case,
                baseline_variant=baseline_variant,
                candidate_variant=candidate_variant,
                baseline_runs=baseline_runs,
                candidate_runs=candidate_runs,
                randomization_seed="seed:comparison",
            )
            store.save_comparison(comparison)
            store.close()
            reopened = SQLiteEvaluationStore(database_path)
            restored = reopened.get_comparison(comparison.comparison_id)
            reopened.close()
        self.assertEqual(restored.blind_order, ("A", "B"))
        self.assertEqual(set(restored.blind_assignment.values()), {"baseline", "candidate"})
        self.assertEqual(restored.baseline_run_ids, (baseline_runs[0].run_id,))


class ReviewTests(unittest.TestCase):
    """验证 Human packet 与可注入 Judge 的边界，不把 Judge 放进在线 Query。"""

    def test_fake_judge_is_injectable_and_packet_has_no_trace_field(self) -> None:
        packet = ReviewPacket(
            packet_id="packet:test",
            run_id="run:test",
            query="q",
            answer_text="answer",
            selected_sources=(),
            rubric_version="m7-v1",
        )

        class FakeJudge:
            async def review(self, received):
                self.received = received
                return EvaluationReview(
                    review_id="review:judge",
                    run_id="run:test",
                    reviewer_type="model_assisted",
                    rubric_version="m7-v1",
                    quality_axes={"answer_relevance": {"label": "not_reviewed"}},
                    confidence=None,
                    notes=None,
                    disagreement=None,
                    needs_adjudication=False,
                    created_at="2026-08-23T00:00:00+00:00",
                )

        review = asyncio.run(run_judge(FakeJudge(), packet))
        self.assertEqual(review.reviewer_type, "model_assisted")
        self.assertNotIn("trace", packet.to_dict())


if __name__ == "__main__":
    unittest.main()
