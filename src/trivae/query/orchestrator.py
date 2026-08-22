"""Query Orchestrator：把 route/plan 编译成一次统一 Runtime 执行。"""

from __future__ import annotations

from typing import Iterable

from trivae.query.contracts import QueryDiagnostic, QueryRequest, QueryResult
from trivae.query.planner import Planner, PlannerResult, render_plan_guidance
from trivae.query.router import Router
from trivae.query.runtime.contracts import AgentRuntime


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

    async def run(self, request: QueryRequest) -> QueryResult:
        """路由、可选规划后调用一次同一 Runtime；Planner 失败不阻塞主链路。"""

        if self._capability_names is not None:
            unknown = set(request.available_capabilities) - set(self._capability_names)
            if unknown:
                raise ValueError(f"requested capability is not registered: {sorted(unknown)!r}")
        context = request.to_context()
        decision = await self.router.route(context)
        diagnostics: list[QueryDiagnostic] = []
        if decision.degraded:
            diagnostics.append(
                QueryDiagnostic(
                    stage="router",
                    code=decision.degradation_code or "ROUTER_DEGRADED",
                    message="router optional completion was not used successfully",
                )
            )

        plan = None
        plan_guidance = None
        if decision.route == "planned_execution":
            planner_result = await self.planner.plan(context)
            plan = planner_result.plan
            if plan is not None:
                plan_guidance = render_plan_guidance(plan)
            else:
                diagnostics.append(self._planner_diagnostic(planner_result))

        runtime_request = request.to_runtime_request(plan_guidance)
        runtime_result = await self.runtime.run(runtime_request)
        return QueryResult(
            runtime_result=runtime_result,
            route_decision=decision,
            plan=plan,
            diagnostics=tuple(diagnostics),
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
