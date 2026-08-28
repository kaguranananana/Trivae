"""Query Orchestrator：把 route/plan 编译成一次统一 Runtime 执行。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from time import perf_counter
from typing import TYPE_CHECKING, Iterable, Literal

from trivae.observability.contracts import FailureInfo
from trivae.query.contracts import QueryDiagnostic, QueryRequest, QueryResult
from trivae.query.evidence import MAX_CONTENT_BLOCKS, FinalizationErrorInfo, finalize_answer_gracefully
from trivae.query.planner import Planner, PlannerResult, render_plan_guidance
from trivae.query.router import RouteDecision, Router
from trivae.query.runtime.contracts import AgentRunRequest, AgentRuntime, RuntimeEvent, RuntimeResult

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

    @staticmethod
    def _answer_candidate_observation(output: str | None) -> dict[str, object]:
        """提取不含正文的 candidate 形状指标，供 Trace 定位答案深度层级。"""

        if not isinstance(output, str) or not output.strip():
            return {}
        try:
            decoded = json.loads(output)
        except (TypeError, ValueError):
            # 非 JSON 会由 finalizer 按既有 contract 处理；这里仅缺少 candidate 诊断，不改变结果。
            return {}
        if not isinstance(decoded, Mapping) or not isinstance(decoded.get("claims"), list):
            return {}
        claims = decoded["claims"]
        # finalizer 对 claims 的业务上限是 MAX_CONTENT_BLOCKS；诊断只读取同一有界前缀。
        bounded_claims = claims[:MAX_CONTENT_BLOCKS]
        text_lengths = tuple(
            len(item["text"])
            if isinstance(item, Mapping) and isinstance(item.get("text"), str)
            else None
            for item in bounded_claims
        )
        return {
            "candidate_claim_count": len(claims),
            "candidate_claim_text_lengths": text_lengths,
        }

    @staticmethod
    async def _run_with_abort(
        runtime: AgentRuntime,
        runtime_request: AgentRunRequest,
        abort_event: object,
    ) -> RuntimeResult:
        """无 Trace 时仍以 stream + abort_event 消费 Runtime，保持取消语义一致。"""

        stream = getattr(runtime, "stream", None)
        if not callable(stream):
            raise ValueError("graceful abort requires a streaming runtime")
        terminal = None
        stream_iterator = stream(runtime_request, abort_event)
        try:
            async for event in stream_iterator:
                if not isinstance(event, RuntimeEvent):
                    raise TypeError("runtime stream must yield RuntimeEvent values")
                if event.type in {"completed", "failed", "aborted"} and event.result is not None:
                    terminal = event.result
        finally:
            close = getattr(stream_iterator, "aclose", None)
            if callable(close):
                await close()
        if terminal is None:
            raise RuntimeError("runtime stream ended without a terminal result")
        return terminal

    async def run(
        self,
        request: QueryRequest,
        *,
        trace: TraceCollector | None = None,
        runtime_event_observer: Callable[[RuntimeEvent], None] | None = None,
        abort_event: object | None = None,
    ) -> QueryResult:
        """路由、可选规划后调用一次同一 Runtime；Planner 失败不阻塞主链路。

        ``abort_event`` 是可选的优雅取消信号（提供 is_set()/wait() 的对象）；
        传入后由 Runtime adapter 解释为 cooperative abort，终态为 aborted，
        区别于 asyncio task cancellation。
        """

        if runtime_event_observer is not None and trace is None:
            # live RuntimeEvent 与 normalized facts 必须经同一 Traceable wrapper 排序，禁止另建执行链。
            raise ValueError("runtime_event_observer requires the query TraceCollector")
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
                    payload={
                        "route": decision.route,
                        **self._planner_request_payload(),
                    },
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
                            **self._planner_observation_payload(planner_result, trace),
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
                            **self._planner_observation_payload(planner_result, trace),
                            **self._planner_failure_payload(planner_failure),
                        },
                        limitations=("executed_without_plan",),
                        failure=FailureInfo(
                            error_code=error_code,
                            origin_stage="planner",
                            observed_stage="planner",
                            category="planner_failure",
                            handling="executed_without_plan",
                            cause_operation_id=planner_operation_id,
                            diagnostic_reference=(
                                None if planner_failure is None else planner_failure.detail_code
                            ),
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
        if trace is None and abort_event is None:
            runtime_result = await self.runtime.run(runtime_request)
        elif trace is None:
            # 无 Trace 的 caller 也必须获得一致的优雅取消语义，不静默丢弃 abort。
            runtime_result = await self._run_with_abort(self.runtime, runtime_request, abort_event)
        else:
            # 延迟导入避免 query package 与 observability collector 的初始化环相互依赖。
            from trivae.observability.collector import TraceableAgentRuntime

            runtime = TraceableAgentRuntime(
                self.runtime,
                trace,
                runtime_event_observer=runtime_event_observer,
                abort_event=abort_event,
            )
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
        # Finalizer 只读取同一个 RuntimeResult 携带的 current-run provenance。
        finalization = finalize_answer_gracefully(
            runtime_result.final_answer or "",
            run_id=runtime_result.run_id,
            tool_results=runtime_result.tool_results,
            scope=request.scope,
            # M5 旧输出把 request_id 嵌入 tool locator；M6 保持 fresh run_id，
            # 仅在调用者明确提供同一 request_id 时映射旧 locator 前缀。
            accepted_run_ids=() if request.request_id is None else (request.request_id,),
        )
        if finalization.error is not None:
            # graceful wrapper 已经把可恢复问题与 fatal 问题区分；fatal 仍显式返回 caller。
            error = finalization.error
            if trace is not None:
                failure = FailureInfo(
                    error_code=error.code,
                    origin_stage="citation",
                    observed_stage="answer",
                    category="validation",
                    handling="returned_to_caller",
                    cause_operation_id="citation.validation",
                    diagnostic_reference=error.path,
                )
                trace.emit(
                    stage="citation",
                    operation="citation.validation.failed",
                    phase="failed",
                    operation_id="citation.validation",
                    parent_operation_id="evidence.prepare",
                    outcome="error",
                    payload={
                        "finalization_status": "failed",
                        "error_code": error.code,
                        "path": error.path,
                        **finalization.diagnostics.to_dict(),
                    },
                    failure=failure,
                )
                trace.emit(
                    stage="answer",
                    operation="answer.finalization.failed",
                    phase="failed",
                    operation_id=finalization_operation_id,
                    parent_operation_id=query_operation_id,
                    outcome="error",
                    payload={
                        "finalization_status": "failed",
                        "error_code": error.code,
                        "path": error.path,
                        **finalization.diagnostics.to_dict(),
                    },
                    failure=FailureInfo(
                        error_code=error.code,
                        origin_stage="citation",
                        observed_stage="answer",
                        category="validation",
                        handling="returned_to_caller",
                        cause_operation_id="citation.validation",
                        diagnostic_reference=error.path,
                    ),
                )
            return QueryResult(
                runtime_result=runtime_result,
                route_decision=decision,
                plan=plan,
                diagnostics=tuple(diagnostics),
                finalization_error=FinalizationErrorInfo(error.code, error.message, error.path),
                finalization_status="failed",
                finalization_diagnostics=finalization.diagnostics,
            )
        answer_artifact = finalization.artifact
        if answer_artifact is None:
            # FinalizationResult 的 invariant 已保证不会发生；若发生必须暴露实现错误。
            raise RuntimeError("successful finalization is missing its answer artifact")
        finalization_diagnostics = finalization.diagnostics
        finalization_outcome: Literal["ok", "partial"] = (
            "partial" if finalization_diagnostics.status == "degraded" else "ok"
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
                outcome=finalization_outcome,
                payload={
                    "evidence_count": len(answer_artifact.evidence_items),
                    "selected_source_count": len(selected_sources),
                    "selected_source_ids": selected_sources,
                    "limitations": answer_artifact.limitations,
                    "resolved_time_range": answer_artifact.resolved_time_range,
                    "retrieval_coverage": answer_artifact.retrieval_coverage,
                    "finalization_status": finalization_diagnostics.status,
                    "user_answer_preserved": finalization_diagnostics.user_answer_preserved,
                    "dropped_field_count": finalization_diagnostics.dropped_field_count,
                    "dropped_citation_count": finalization_diagnostics.dropped_citation_count,
                    "normalization_count": finalization_diagnostics.normalization_count,
                },
            )
            trace.emit(
                stage="citation",
                operation="citation.validation.completed",
                phase="completed",
                operation_id="citation.validation",
                parent_operation_id="evidence.prepare",
                outcome=finalization_outcome,
                payload={
                    "binding_count": len(answer_artifact.citation_bindings),
                    "unresolved_count": finalization_diagnostics.dropped_citation_count,
                    "validated_citation_count": finalization_diagnostics.validated_citation_count,
                    "finalization_status": finalization_diagnostics.status,
                },
            )
            trace.emit(
                stage="answer",
                operation="answer.finalization.completed",
                phase="completed",
                operation_id=finalization_operation_id,
                parent_operation_id=query_operation_id,
                outcome=finalization_outcome,
                payload={
                    "answer_length": len(answer_artifact.answer_text),
                    # 保持既有 Trace 正文快照位于 normal CapturePolicy 的有界字段前缀内。
                    "answer_text": answer_artifact.answer_text,
                    # candidate 指标只记录 claim 数和正文长度，不把模型原文复制到 Trace。
                    # 将新诊断收进一个有界 mapping，避免新增顶层字段挤掉既有 Trace 字段。
                    "answer_shape": {
                        **self._answer_candidate_observation(runtime_result.final_answer),
                        "content_block_count": len(answer_artifact.content_blocks),
                        "content_block_text_lengths": tuple(
                            len(block.text) for block in answer_artifact.content_blocks
                        ),
                    },
                    "limitation_count": len(answer_artifact.limitations),
                    "finalization_status": finalization_diagnostics.status,
                    "user_answer_preserved": finalization_diagnostics.user_answer_preserved,
                    "error_code": finalization_diagnostics.error_code,
                    "error_path": finalization_diagnostics.error_path,
                    "degradation_codes": finalization_diagnostics.degradation_codes,
                    "dropped_field_count": finalization_diagnostics.dropped_field_count,
                    "dropped_field_paths": finalization_diagnostics.dropped_field_paths,
                    "dropped_citation_count": finalization_diagnostics.dropped_citation_count,
                    "normalization_count": finalization_diagnostics.normalization_count,
                    "validated_citation_count": finalization_diagnostics.validated_citation_count,
                    "resolved_time_range": answer_artifact.resolved_time_range,
                    "retrieval_coverage": answer_artifact.retrieval_coverage,
                },
            )
        return QueryResult(
            runtime_result=runtime_result,
            route_decision=decision,
            plan=plan,
            diagnostics=tuple(diagnostics),
            answer_artifact=answer_artifact,
            finalization_status=finalization_diagnostics.status,
            finalization_diagnostics=finalization_diagnostics,
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

    def _planner_request_payload(self) -> dict[str, object]:
        """从 SoftPlanner 读取 timeout/request projection，timeout 时也保留调用边界事实。"""

        payload: dict[str, object] = {}
        timeout = getattr(self.planner, "completion_timeout_seconds", None)
        if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            payload["completion_timeout_seconds"] = timeout
        request = getattr(self.planner, "completion_request", None)
        if isinstance(request, dict) and request:
            # request 已由 Runtime adapter 约束为普通非敏感值，不在这里复制 SDK 对象。
            payload["completion_request"] = dict(request)
        return payload

    @staticmethod
    def _planner_observation_payload(
        result: PlannerResult,
        trace: TraceCollector | None,
    ) -> dict[str, object]:
        """把 Planner observation 映射为 normal/debug 共享的安全运行事实。"""

        observation = result.observation
        if observation is None:
            return {}
        payload: dict[str, object] = {
            "provider": observation.provider,
            "model": observation.model,
            "completion_request": dict(observation.request),
            "planner_latency_ms": observation.latency_ms,
            "provider_latency_ms": observation.provider_latency_ms,
            "finish_reason": observation.finish_reason,
            "usage": None if observation.usage is None else dict(observation.usage),
            "response_length": (
                None if observation.response_content is None else len(observation.response_content)
            ),
            "parse_stage": observation.parse_stage,
        }
        usage = observation.usage
        if usage is not None:
            # Provider 可能使用 output_tokens 或 completion_tokens，Trace 统一提供一个易读别名。
            for key in ("output_tokens", "completion_tokens"):
                value = usage.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    payload["output_tokens"] = value
                    break
        # Prompt/response 正文只在 debug profile 落盘，normal Trace 保留长度和结构化元数据。
        if trace is not None and trace.profile == "debug":
            payload["prompt"] = observation.prompt
            if observation.response_content is not None:
                payload["response_content"] = observation.response_content
        return payload

    @staticmethod
    def _planner_failure_payload(failure: object) -> dict[str, object]:
        """附加 Planner-owned 的细分类，不把 Provider exception 正文暴露给调用者。"""

        if failure is None:
            return {}
        detail_code = getattr(failure, "detail_code", None)
        parse_stage = getattr(failure, "parse_stage", None)
        diagnostic = getattr(failure, "diagnostic", None)
        exception_type = getattr(failure, "exception_type", None)
        payload: dict[str, object] = {
            "failure_detail_code": detail_code,
            "parse_stage": parse_stage,
        }
        if isinstance(diagnostic, str) and diagnostic:
            payload["diagnostic"] = diagnostic
        if isinstance(exception_type, str) and exception_type:
            payload["exception_type"] = exception_type
        return payload
