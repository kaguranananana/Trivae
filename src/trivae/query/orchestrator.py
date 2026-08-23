"""Query Orchestrator：把 route/plan 编译成一次统一 Runtime 执行。"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Iterable

from trivae.observability.contracts import FailureInfo
from trivae.query.contracts import QueryDiagnostic, QueryRequest, QueryResult
from trivae.query.evidence import AnswerFinalizationError, FinalizationErrorInfo, finalize_answer
from trivae.query.planner import Planner, PlannerResult, render_plan_guidance
from trivae.query.router import RouteDecision, Router
from trivae.query.runtime.contracts import AgentRuntime

if TYPE_CHECKING:
    from trivae.observability.collector import TraceCollector


class QueryOrchestrator:
    """拥有 application-level query flow，但不实现 SDK/tool loop。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        router: Router,
        planner: Planner,
        *,
        capability_names: Iterable[str] | None = None,
    ) -> None:
        """保存同一 runtime/router/planner 实例，保证两路不会各自创建执行器。"""

        self.runtime = runtime
        self.router = router
        self.planner = planner
        self._capability_names = None if capability_names is None else tuple(capability_names)

    async def run(self, request: QueryRequest, *, trace: TraceCollector | None = None) -> QueryResult:
        """路由、可选规划后调用一次同一 Runtime；Planner 失败不阻塞主链路。"""

        if self._capability_names is not None:
            unknown = set(request.available_capabilities) - set(self._capability_names)
            if unknown:
                raise ValueError(f"requested capability is not registered: {sorted(unknown)!r}")
        context = request.to_context()
        query_operation_id = "query"
        router_operation_id = "router"
        forced_route = request.execution_override.forced_route
        if forced_route is not None:
            # Forced path 只绕过 Router 的选择，不复制或替换后续 Planner/Runtime。
            decision = RouteDecision(
                route=forced_route,
                confidence=1.0,
                source="evaluation_override",
                reason=f"explicit evaluation override: {forced_route}",
            )
            if trace is not None:
                trace.emit(
                    stage="router",
                    operation="router.bypassed",
                    phase="skipped",
                    operation_id=router_operation_id,
                    parent_operation_id=query_operation_id,
                    outcome="ok",
                    payload={
                        "execution_override": request.execution_override.to_dict(),
                        "route": forced_route,
                    },
                )
        else:
            router_started = perf_counter()
            if trace is not None:
                trace.emit(
                    stage="router",
                    operation="router.started",
                    phase="started",
                    operation_id=router_operation_id,
                    parent_operation_id=query_operation_id,
                    payload={"available_capabilities": request.available_capabilities},
                )
            try:
                decision = await self.router.route(context)
            except Exception as exc:
                if trace is not None:
                    trace.emit(
                        stage="router",
                        operation="router.failed",
                        phase="failed",
                        operation_id=router_operation_id,
                        parent_operation_id=query_operation_id,
                        outcome="error",
                        duration_ms=(perf_counter() - router_started) * 1000,
                        payload={"exception_type": type(exc).__name__},
                        failure=FailureInfo(
                            error_code="ROUTER_EXCEPTION",
                            origin_stage="router",
                            observed_stage="router",
                            category="exception",
                            handling="propagated",
                            cause_operation_id=router_operation_id,
                            diagnostic_reference=type(exc).__name__,
                        ),
                    )
                raise
        if trace is not None:
            decision_payload = {
                "route": decision.route,
                "confidence": decision.confidence,
                "source": decision.source,
                "reason": decision.reason,
                "degraded": decision.degraded,
                "degradation_code": decision.degradation_code,
                "usage": None if decision.usage is None else dict(decision.usage),
                "execution_override": request.execution_override.to_dict(),
            }
            trace.emit(
                stage="router",
                operation="router.decision",
                phase="completed",
                operation_id=router_operation_id,
                parent_operation_id=query_operation_id,
                outcome="partial" if decision.degraded else "ok",
                duration_ms=None if forced_route is not None else (perf_counter() - router_started) * 1000,
                payload=decision_payload,
            )
        diagnostics: list[QueryDiagnostic] = []
        if decision.degraded:
            diagnostics.append(
                QueryDiagnostic(
                    stage="router",
                    code=decision.degradation_code or "ROUTER_DEGRADED",
                    message="router optional completion was not used successfully",
                )
            )
            if trace is not None:
                trace.emit(
                    stage="router",
                    operation="router.degraded",
                    phase="degraded",
                    operation_id=router_operation_id,
                    parent_operation_id=query_operation_id,
                    outcome="partial",
                    payload={"degradation_code": decision.degradation_code},
                    limitations=("static_route_retained",),
                    failure=FailureInfo(
                        error_code=decision.degradation_code or "ROUTER_DEGRADED",
                        origin_stage="router",
                        observed_stage="router",
                        category="degradation",
                        handling="static_route_retained",
                        cause_operation_id=router_operation_id,
                    ),
                )

        plan = None
        plan_guidance = None
        if decision.route == "planned_execution":
            planner_operation_id = "planner"
            planner_started = perf_counter()
            if trace is not None:
                trace.emit(
                    stage="planner",
                    operation="planner.started",
                    phase="started",
                    operation_id=planner_operation_id,
                    parent_operation_id=query_operation_id,
                    payload={"route": decision.route},
                )
            try:
                planner_result = await self.planner.plan(context)
            except Exception as exc:
                if trace is not None:
                    trace.emit(
                        stage="planner",
                        operation="planner.failed",
                        phase="failed",
                        operation_id=planner_operation_id,
                        parent_operation_id=query_operation_id,
                        outcome="error",
                        duration_ms=(perf_counter() - planner_started) * 1000,
                        payload={"exception_type": type(exc).__name__},
                        failure=FailureInfo(
                            error_code="PLANNER_EXCEPTION",
                            origin_stage="planner",
                            observed_stage="planner",
                            category="exception",
                            handling="propagated",
                            cause_operation_id=planner_operation_id,
                            diagnostic_reference=type(exc).__name__,
                        ),
                    )
                raise
            plan = planner_result.plan
            if plan is not None:
                plan_guidance = render_plan_guidance(plan)
                if trace is not None:
                    trace.emit(
                        stage="planner",
                        operation="planner.completed",
                        phase="completed",
                        operation_id=planner_operation_id,
                        parent_operation_id=query_operation_id,
                        outcome="ok",
                        duration_ms=(perf_counter() - planner_started) * 1000,
                        payload={
                            "version": plan.version,
                            "title": plan.title,
                            "intent": plan.intent,
                            "step_count": len(plan.steps),
                            "criterion_count": len(plan.success_criteria),
                            # Planner 的成功标准是显式 execution fact，供 Transcript 直接阅读。
                            "success_criteria": plan.success_criteria,
                            "steps": [
                                {
                                    "goal": step.goal,
                                    "suggested_tools": step.suggested_tools,
                                    "evidence_needed": step.evidence_needed,
                                }
                                for step in plan.steps
                            ],
                        },
                    )
            else:
                diagnostics.append(self._planner_diagnostic(planner_result))
                if trace is not None:
                    planner_failure = planner_result.failure
                    error_code = (
                        "PLANNER_EMPTY"
                        if planner_failure is None
                        else f"PLANNER_{planner_failure.code.upper()}"
                    )
                    trace.emit(
                        stage="planner",
                        operation="planner.failed",
                        phase="failed",
                        operation_id=planner_operation_id,
                        parent_operation_id=query_operation_id,
                        outcome="partial",
                        duration_ms=(perf_counter() - planner_started) * 1000,
                        payload={
                            "error_code": error_code,
                            "failure_category": None if planner_failure is None else planner_failure.code,
                        },
                        limitations=("executed_without_plan",),
                        failure=FailureInfo(
                            error_code=error_code,
                            origin_stage="planner",
                            observed_stage="planner",
                            category="planner_failure",
                            handling="executed_without_plan",
                            cause_operation_id=planner_operation_id,
                        ),
                    )
                    trace.emit(
                        stage="planner",
                        operation="planner.skipped",
                        phase="skipped",
                        operation_id=planner_operation_id,
                        parent_operation_id=query_operation_id,
                        outcome="partial",
                        payload={"reason": "planner_failure"},
                        limitations=("executed_without_plan",),
                    )

        runtime_request = request.to_runtime_request(
            plan_guidance,
            trace_context=None if trace is None else trace.operation_context(query_operation_id),
        )
        if trace is None:
            runtime = self.runtime
        else:
            # 延迟导入避免 query package 与 observability collector 的初始化环相互依赖。
            from trivae.observability.collector import TraceableAgentRuntime

            runtime = TraceableAgentRuntime(self.runtime, trace)
        runtime_result = await runtime.run(runtime_request)
        if runtime_result.termination != "completed":
            # Runtime failure/abort/max-turn 不能被包装成 Evidence partial 或成功回答。
            if trace is not None:
                trace.emit(
                    stage="answer",
                    operation="answer.finalization.skipped",
                    phase="skipped",
                    operation_id="answer.finalization",
                    parent_operation_id=query_operation_id,
                    outcome="aborted" if runtime_result.termination == "aborted" else "error",
                    payload={"termination": runtime_result.termination},
                    limitations=("runtime_not_completed",),
                )
            return QueryResult(
                runtime_result=runtime_result,
                route_decision=decision,
                plan=plan,
                diagnostics=tuple(diagnostics),
            )

        finalization_operation_id = "answer.finalization"
        if trace is not None:
            trace.emit(
                stage="evidence",
                operation="evidence.prepare.started",
                phase="started",
                operation_id="evidence.prepare",
                parent_operation_id=query_operation_id,
                payload={
                    "tool_result_count": len(runtime_result.tool_results),
                    "tool_call_count": len(runtime_result.tool_calls),
                },
            )
            trace.emit(
                stage="citation",
                operation="citation.validation.started",
                phase="started",
                operation_id="citation.validation",
                parent_operation_id="evidence.prepare",
                payload={"run_id": runtime_result.run_id},
            )
            trace.emit(
                stage="answer",
                operation="answer.finalization.started",
                phase="started",
                operation_id="answer.finalization",
                parent_operation_id=query_operation_id,
                payload={"run_id": runtime_result.run_id},
            )
        try:
            # Finalizer 只读取同一个 RuntimeResult 携带的 current-run provenance。
            answer_artifact = finalize_answer(
                runtime_result.final_answer or "",
                run_id=runtime_result.run_id,
                tool_results=runtime_result.tool_results,
                scope=request.scope,
                # M5 旧输出把 request_id 嵌入 tool locator；M6 保持 fresh run_id，
                # 仅在调用者明确提供同一 request_id 时映射旧 locator 前缀。
                accepted_run_ids=() if request.request_id is None else (request.request_id,),
            )
        except AnswerFinalizationError as exc:
            # citation 错误显式暴露；不删除 binding、不自动替换 source、不重试模型。
            if trace is not None:
                failure = FailureInfo(
                    error_code=exc.code,
                    origin_stage="citation",
                    observed_stage="answer",
                    category="validation",
                    handling="returned_to_caller",
                    cause_operation_id="citation.validation",
                    diagnostic_reference=exc.path,
                )
                trace.emit(
                    stage="citation",
                    operation="citation.validation.failed",
                    phase="failed",
                    operation_id="citation.validation",
                    parent_operation_id="evidence.prepare",
                    outcome="error",
                    payload={"error_code": exc.code, "path": exc.path},
                    failure=failure,
                )
                trace.emit(
                    stage="answer",
                    operation="answer.finalization.failed",
                    phase="failed",
                    operation_id=finalization_operation_id,
                    parent_operation_id=query_operation_id,
                    outcome="error",
                    payload={"error_code": exc.code, "path": exc.path},
                    failure=FailureInfo(
                        error_code=exc.code,
                        origin_stage="citation",
                        observed_stage="answer",
                        category="validation",
                        handling="returned_to_caller",
                        cause_operation_id="citation.validation",
                        diagnostic_reference=exc.path,
                    ),
                )
            return QueryResult(
                runtime_result=runtime_result,
                route_decision=decision,
                plan=plan,
                diagnostics=tuple(diagnostics),
                finalization_error=FinalizationErrorInfo(exc.code, exc.message, exc.path),
            )
        if trace is not None:
            selected_sources: list[str] = []
            for evidence_item in answer_artifact.evidence_items:
                for evidence_source in evidence_item.sources:
                    reference = evidence_source.reference
                    locator = getattr(reference, "internal_message_id", None) or getattr(
                        reference, "locator", None
                    )
                    if isinstance(locator, str):
                        selected_sources.append(locator)
            trace.emit(
                stage="evidence",
                operation="evidence.prepare.completed",
                phase="completed",
                operation_id="evidence.prepare",
                parent_operation_id=query_operation_id,
                outcome="ok",
                payload={
                    "evidence_count": len(answer_artifact.evidence_items),
                    "selected_source_count": len(selected_sources),
                    "selected_source_ids": selected_sources,
                    "limitations": answer_artifact.limitations,
                },
            )
            trace.emit(
                stage="citation",
                operation="citation.validation.completed",
                phase="completed",
                operation_id="citation.validation",
                parent_operation_id="evidence.prepare",
                outcome="ok",
                payload={
                    "binding_count": len(answer_artifact.citation_bindings),
                    "unresolved_count": 0,
                },
            )
            trace.emit(
                stage="answer",
                operation="answer.finalization.completed",
                phase="completed",
                operation_id=finalization_operation_id,
                parent_operation_id=query_operation_id,
                outcome="ok",
                payload={
                    "answer_length": len(answer_artifact.answer_text),
                    "limitation_count": len(answer_artifact.limitations),
                    # 这是通过 finalization 校验后的 Debug execution snapshot；业务事实仍由 AnswerArtifact/Conversation Store 持有。
                    "answer_text": answer_artifact.answer_text,
                },
            )
        return QueryResult(
            runtime_result=runtime_result,
            route_decision=decision,
            plan=plan,
            diagnostics=tuple(diagnostics),
            answer_artifact=answer_artifact,
        )

    def _planner_diagnostic(self, result: PlannerResult) -> QueryDiagnostic:
        """将 Planner failure 映射为稳定信息，不把 provider 异常正文传给调用者。"""

        failure = result.failure
        if failure is None:
            return QueryDiagnostic(
                stage="planner",
                code="PLANNER_EMPTY",
                message="planner returned no plan",
            )
        return QueryDiagnostic(stage="planner", code=f"PLANNER_{failure.code.upper()}", message=failure.message)
