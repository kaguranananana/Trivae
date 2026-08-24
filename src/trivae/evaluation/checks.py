"""Evaluation 的确定性检查与 operational projection。"""

from __future__ import annotations

from typing import Mapping

from trivae.observability.contracts import TraceProjection
from trivae.query.contracts import QueryRequest, QueryResult
from trivae.query.evidence import AnswerArtifact

from .contracts import (
    DatasetSnapshot,
    DeterministicCheck,
    EvaluationCaseBundle,
    EvaluationContractError,
    EvaluationResult,
    scope_identity,
)
from .variant import ControlledVariant


def query_result_snapshot(result: QueryResult | None) -> dict[str, object] | None:
    """只保存 QueryResult 的 bounded identity/状态，不把完整 Answer/Trace 复制进 Evaluation DB。"""

    if result is None:
        return None
    plan = result.plan
    runtime_error = result.runtime_result.error
    tool_behavior = agent_tool_behavior_projection(result)
    return {
        "termination": result.termination,
        "is_successful": result.is_successful,
        "route": result.route_decision.route,
        "route_source": result.route_decision.source,
        "route_degraded": result.route_decision.degraded,
        "route_degradation_code": result.route_decision.degradation_code,
        "plan": None
        if plan is None
        else {
            "version": plan.version,
            "title": plan.title,
            "intent": plan.intent,
            "step_count": len(plan.steps),
            "criterion_count": len(plan.success_criteria),
        },
        "runtime": {
            "provider": result.runtime_result.provider,
            "model": result.runtime_result.model,
            "termination": result.runtime_result.termination,
            "tool_count": result.runtime_result.tool_count,
            "tool_rounds": result.runtime_result.tool_rounds,
            "tool_behavior": tool_behavior,
            "usage": None if result.runtime_result.usage is None else dict(result.runtime_result.usage),
            "run_id": result.runtime_result.run_id,
            "error": None
            if runtime_error is None
            else {
                "code": runtime_error.code,
                "stage": runtime_error.stage,
                "category": runtime_error.category,
                "diagnostic_type": runtime_error.diagnostic_type,
            },
        },
        "finalization_error": None
        if result.finalization_error is None
        else {
            "code": result.finalization_error.code,
            "path": result.finalization_error.path,
        },
        "answer_artifact_present": isinstance(result.answer_artifact, AnswerArtifact),
        "conversation_id": result.conversation_id,
        "trace_id": result.trace_id,
        "diagnostic_codes": [diagnostic.code for diagnostic in result.diagnostics],
    }


def agent_tool_behavior_projection(result: QueryResult | None) -> dict[str, object]:
    """保存 Agent Tool Selection 的公开行为事实，不替模型行为下质量结论。"""

    if result is None:
        return {
            "first_selected_tool": None,
            "tool_sequence": [],
            "retrieval_tool_sequence": [],
            "context_tool_sequence": [],
            "member_tool_sequence": [],
            "schema_tool_sequence": [],
            "sql_tool_sequence": [],
            "tool_call_count": 0,
            "tool_rounds": 0,
            "tool_errors": [],
        }
    calls = result.runtime_result.tool_calls
    retrieval_names = {"lexical_search", "semantic_search", "search_messages"}
    context_names = {"get_message_context"}
    member_names = {"find_members"}
    schema_names = {"get_schema"}
    sql_names = {"execute_sql"}
    return {
        "first_selected_tool": None if not calls else calls[0].name,
        "tool_sequence": [call.name for call in calls],
        "retrieval_tool_sequence": [call.name for call in calls if call.name in retrieval_names],
        # Stage B 保留 context/member 的公开 action sequence，是否合理仍交给 Case Review。
        "context_tool_sequence": [call.name for call in calls if call.name in context_names],
        "member_tool_sequence": [call.name for call in calls if call.name in member_names],
        # Stage C 将 schema inspection 与 SQL execution 分轴记录，便于判断 schema→SQL 链路。
        "schema_tool_sequence": [call.name for call in calls if call.name in schema_names],
        "sql_tool_sequence": [call.name for call in calls if call.name in sql_names],
        "tool_call_count": len(calls),
        "tool_rounds": result.runtime_result.tool_rounds,
        "tool_errors": [
            {
                "name": call.name,
                "status": call.status,
                "error_code": call.error_code,
            }
            for call in calls
            if call.status in {"error", "failed"} or call.error_code is not None
        ],
    }


def operational_measurements(
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> dict[str, object]:
    """从 Runtime/Trace 派生运行事实，保持与回答质量分轴。"""

    measurements: dict[str, object] = {
        "termination": None if result is None else result.termination,
        "tool_calls": None if result is None else result.runtime_result.tool_count,
        "tool_rounds": None if result is None else result.runtime_result.tool_rounds,
        "provider": None if result is None else result.runtime_result.provider,
        "model": None if result is None else result.runtime_result.model,
        "usage": None
        if result is None or result.runtime_result.usage is None
        else dict(result.runtime_result.usage),
        "trace_completeness": None if trace is None else trace.completeness,
        "retrieval_count": None if trace is None else trace.metrics.retrieval_count,
        "structured_sql": None if trace is None else _structured_sql_measurements(trace),
        # 这是公开 action sequence 的 observation；preferred tool 仍由诊断 Case 和人工/模型 Review 分开判断。
        "agent_tool_behavior": agent_tool_behavior_projection(result),
    }
    if trace is not None:
        measurements["latency_ms"] = trace.metrics.total_duration_ms
        limitations: list[str] = []
        coverage_statuses: list[str] = []
        for item in trace.timeline:
            limitations.extend(item.limitations)
            coverage = item.payload.get("coverage")
            if isinstance(coverage, Mapping):
                status = coverage.get("status")
                if isinstance(status, str):
                    coverage_statuses.append(status)
            if item.payload.get("truncated") is True:
                limitations.append("truncated")
            if item.payload.get("partial") is True:
                limitations.append("partial")
        measurements["trace_limitations"] = tuple(sorted(set(limitations)))
        measurements["coverage_statuses"] = tuple(sorted(set(coverage_statuses)))
    return measurements


def _structured_sql_measurements(trace: TraceProjection) -> dict[str, object]:
    """从 Trace 的公开 structured operation 摘要记录 SQL/schema 行为事实。"""

    schema_events = tuple(
        item
        for item in trace.timeline
        if item.operation == "schema.inspect.completed" and item.phase == "completed"
    )
    sql_events = tuple(
        item
        for item in trace.timeline
        if item.operation == "sql.execute.completed" and item.phase == "completed"
    )
    sql_failures = tuple(
        item
        for item in trace.timeline
        if item.operation == "sql.execute.failed" and item.phase == "failed"
    )
    return {
        "schema_calls": len(schema_events),
        "schema_returned_tables": tuple(
            value
            for item in schema_events
            for value in (item.payload.get("returned_tables"),)
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        "sql_calls": len(sql_events),
        "sql_returned_rows": tuple(
            value
            for item in sql_events
            for value in (item.payload.get("returned_rows"),)
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        "sql_truncated": tuple(item.payload.get("truncated") is True for item in sql_events),
        "sql_scope_enforcement": tuple(
            value
            for item in sql_events
            for value in (item.payload.get("scope_enforcement"),)
            if isinstance(value, str)
        ),
        "sql_errors": tuple(
            value
            for item in sql_failures
            for value in (item.payload.get("error_code"),)
            if isinstance(value, str)
        ),
    }


def _check(
    name: str,
    status: str,
    severity: str,
    message: str,
    *references: str,
) -> DeterministicCheck:
    """集中构造检查，实际 status 仍由 caller 的事实决定。"""

    return DeterministicCheck(
        name=name,
        status=status,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        message=message,
        evidence_references=tuple(references),
    )


def run_deterministic_checks(
    *,
    case: EvaluationCaseBundle,
    snapshot: DatasetSnapshot | None,
    variant: ControlledVariant,
    request: QueryRequest,
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> tuple[DeterministicCheck, ...]:
    """对单次 Run 做 contract checks；不做自然语言质量判断。"""

    checks: list[DeterministicCheck] = []
    checks.append(_check("case_identity", "passed", "hard", f"resolved Case {case.identity}"))
    if snapshot is None:
        checks.append(_check("snapshot_identity", "failed", "hard", "Dataset Snapshot could not be resolved"))
    elif snapshot.status != "available":
        checks.append(_check("snapshot_identity", "failed", "hard", f"Snapshot status is {snapshot.status}"))
    elif snapshot.snapshot_id != case.dataset_snapshot.snapshot_id:
        checks.append(
            _check(
                "snapshot_identity",
                "failed",
                "hard",
                "resolved Snapshot does not match Case Snapshot",
                case.dataset_snapshot.snapshot_id,
                snapshot.snapshot_id,
            )
        )
    else:
        checks.append(_check("snapshot_identity", "passed", "hard", "Case and resolved Snapshot identities match"))

    try:
        variant_identity = variant.identity
    except EvaluationContractError as exc:
        checks.append(_check("variant_identity", "failed", "hard", str(exc)))
    else:
        checks.append(_check("variant_identity", "passed", "hard", f"resolved Variant {variant_identity}"))

    expected_scope = scope_identity(case.data_access_scope)
    request_scope = scope_identity(request.scope)
    if expected_scope != request_scope:
        checks.append(_check("data_access_scope", "failed", "hard", "QueryRequest scope differs from Case scope"))
    else:
        checks.append(_check("data_access_scope", "passed", "hard", "QueryRequest preserves Case Data Access Scope"))

    if result is None:
        checks.append(_check("query_terminal_state", "failed", "hard", "Query raised before a QueryResult was returned"))
    else:
        checks.append(_check("query_terminal_state", "passed", "hard", f"Query returned terminal state {result.termination}"))

    if result is None:
        checks.append(_check("answer_artifact_contract", "not_applicable", "hard", "Query did not produce a successful Answer Artifact"))
        checks.append(_check("finalization_state", "not_applicable", "hard", "Finalization was not successful"))
        checks.append(_check("citation_provenance", "not_applicable", "hard", "No successful citation finalization to validate"))
    elif result.finalization_error is not None:
        # Finalizer/Citation 已明确返回 failure 时必须成为 hard gate，不能被归类为“未适用”。
        checks.append(_check("answer_artifact_contract", "failed", "hard", "Answer Artifact was rejected by production Finalizer"))
        checks.append(
            _check(
                "finalization_state",
                "failed",
                "hard",
                f"Production Finalizer failed with {result.finalization_error.code}",
            )
        )
        checks.append(
            _check(
                "citation_provenance",
                "failed",
                "hard",
                f"Citation/provenance validation failed with {result.finalization_error.code}",
            )
        )
    elif not result.is_successful:
        checks.append(_check("answer_artifact_contract", "not_applicable", "hard", "Query did not produce a successful Answer Artifact"))
        checks.append(_check("finalization_state", "not_applicable", "hard", "Finalization was not successful"))
        checks.append(_check("citation_provenance", "not_applicable", "hard", "No successful citation finalization to validate"))
    else:
        if isinstance(result.answer_artifact, AnswerArtifact):
            checks.append(_check("answer_artifact_contract", "passed", "hard", "Answer Artifact passed the production contract"))
        else:
            checks.append(_check("answer_artifact_contract", "failed", "hard", "Successful QueryResult has no Answer Artifact"))
        if result.finalization_error is None:
            checks.append(_check("finalization_state", "passed", "hard", "Production Finalizer completed"))
            checks.append(_check("citation_provenance", "passed", "hard", "Production citation/provenance validation completed"))
        else:
            checks.append(
                _check(
                    "finalization_state",
                    "failed",
                    "hard",
                    f"Production Finalizer failed with {result.finalization_error.code}",
                )
            )
            checks.append(
                _check(
                    "citation_provenance",
                    "failed",
                    "hard",
                    f"Citation/provenance validation failed with {result.finalization_error.code}",
                )
            )

    if trace is None:
        checks.append(_check("trace_exists", "failed", "hard", "Trace reference could not be read"))
    else:
        checks.append(_check("trace_exists", "passed", "hard", f"Trace {trace.trace_id} is readable"))
        if trace.completeness == "complete":
            checks.append(_check("trace_completeness", "passed", "diagnostic", "Trace projection is complete"))
        else:
            checks.append(
                _check(
                    "trace_completeness",
                    "failed",
                    "diagnostic",
                    f"Trace completeness is {trace.completeness}; quality is not inferred from this fact",
                )
            )

    if trace is None or result is None:
        checks.append(_check("trace_terminal_consistency", "unknown", "hard", "Trace/result terminal consistency cannot be checked"))
    else:
        expected_terminal = "completed" if result.is_successful else "aborted" if result.termination == "aborted" else "failed"
        if trace.terminal_status == expected_terminal:
            checks.append(_check("trace_terminal_consistency", "passed", "hard", f"Trace terminal matches {expected_terminal}"))
        else:
            checks.append(
                _check(
                    "trace_terminal_consistency",
                    "failed",
                    "hard",
                    f"Trace terminal {trace.terminal_status} does not match QueryResult {expected_terminal}",
                )
            )

    if trace is not None:
        forced_route = request.execution_override.forced_route
        operations = {item.operation: item for item in trace.timeline}
        router_decisions = [item for item in trace.timeline if item.operation == "router.decision"]
        if forced_route is None:
            if "router.started" in operations and "router.bypassed" not in operations:
                checks.append(_check("execution_override", "passed", "hard", "Normal execution retained Router decision"))
            else:
                checks.append(_check("execution_override", "failed", "hard", "Normal execution did not retain Router evidence"))
        else:
            override_decision = False
            for item in router_decisions:
                override_payload = item.payload.get("execution_override")
                if (
                    item.payload.get("source") == "evaluation_override"
                    and isinstance(override_payload, Mapping)
                    and override_payload.get("forced_route") == forced_route
                ):
                    override_decision = True
                    break
            bypassed = any(
                item.payload.get("route") == forced_route
                for item in trace.timeline
                if item.operation == "router.bypassed"
            )
            if override_decision and bypassed:
                checks.append(_check("execution_override", "passed", "hard", f"Forced route {forced_route} is explicit in Trace"))
            else:
                checks.append(_check("execution_override", "failed", "hard", f"Forced route {forced_route} is not explicit in Trace"))
    else:
        checks.append(_check("execution_override", "unknown", "hard", "Trace is unavailable for override validation"))

    if result is None:
        checks.append(_check("limitation_preservation", "unknown", "diagnostic", "No RuntimeResult is available"))
    else:
        runtime_limitations = {
            limitation
            for record in result.runtime_result.tool_results
            for limitation in record.limitations
        }
        if not runtime_limitations:
            checks.append(_check("limitation_preservation", "not_applicable", "diagnostic", "Run has no Tool limitations"))
        elif trace is None:
            checks.append(_check("limitation_preservation", "failed", "diagnostic", "Tool limitations exist but Trace is unavailable"))
        else:
            # Trace canonical event 的 payload 记录 partial/truncated 事实，分析层把它映射回
            # Runtime limitation 名称；这里只读事实，不改写 append-only Trace。
            trace_limitations: set[str] = {
                limitation
                for item in trace.timeline
                for limitation in item.limitations
            }
            for item in trace.timeline:
                if item.payload.get("partial") is True:
                    trace_limitations.update(("retrieval_partial", "tool_result_partial"))
                if item.payload.get("truncated") is True:
                    trace_limitations.add("retrieval_truncated")
            missing = sorted(runtime_limitations - trace_limitations)
            if missing:
                checks.append(_check("limitation_preservation", "failed", "diagnostic", f"Trace lost limitations: {missing!r}"))
            else:
                checks.append(_check("limitation_preservation", "passed", "diagnostic", "Tool limitations remain visible in Trace"))

    checks.append(
        _check(
            "replay_identity",
            "passed" if request.request_id and (result is None or result.trace_id) else "failed",
            "hard",
            "Query request and Trace identity are available" if request.request_id and (result is None or result.trace_id) else "Required replay identity is missing",
        )
    )
    return tuple(checks)


def build_evaluation_result(
    *,
    run_id: str,
    checks: tuple[DeterministicCheck, ...],
    result: QueryResult | None,
    trace: TraceProjection | None,
) -> EvaluationResult:
    """把单次 Run 转成不含总分的 Result 投影。"""

    hard_failed = any(item.severity == "hard" and item.status == "failed" for item in checks)
    status = "failed" if result is None or (result is not None and not result.is_successful) or hard_failed else "not_reviewed"
    diagnostics_failed = any(item.name == "trace_completeness" and item.status == "failed" for item in checks)
    quality_axes = {
        "task_finding_correctness": {"label": "not_reviewed"},
        "evidence_completeness": {"label": "not_reviewed"},
        "groundedness_entailment": {"label": "not_reviewed"},
        "uncertainty_calibration": {"label": "not_reviewed"},
        "answer_relevance": {"label": "not_reviewed"},
    }
    diagnosability = {
        "trace_available": trace is not None,
        "trace_completeness": None if trace is None else trace.completeness,
        "trace_completeness_check_failed": diagnostics_failed,
    }
    return EvaluationResult(
        result_id=f"result:{run_id}",
        run_id=run_id,
        status=status,  # type: ignore[arg-type]
        quality_axes=quality_axes,
        diagnosability=diagnosability,
        operational_measurements=operational_measurements(result, trace),
    )
