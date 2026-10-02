"""两路 Query Router：先结构化判断，再按需使用受约束的决策 Provider。"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal, Mapping, Protocol

from trivae.query.completion import CompletionCallback, invoke_completion
from trivae.query.contracts import QueryContext

RouteName = Literal["standard_execution", "planned_execution"]
RouteSource = Literal["rule", "llm", "jev", "evaluation_override"]
RouterMode = Literal["existing_llm", "jev", "shadow"]
RouterInput = QueryContext


@dataclass(frozen=True)
class RouterProviderResult:
    """Provider boundary 的 Trivae-owned 投影，不携带 SDK response 类型。"""

    route: RouteName
    confidence: float
    probabilities: Mapping[str, float]
    usage: Mapping[str, int | float] | None = None
    provider: str | None = None
    model: str | None = None


class RouterDecisionProviderError(RuntimeError):
    """Router optional decision provider 失败时保留的稳定 degradation code。"""

    def __init__(self, code: str, *, diagnostic_type: str | None = None) -> None:
        """只保存稳定错误码和异常类型，不让原始 Provider body 越过边界。"""

        super().__init__(code)
        self.code = code
        self.diagnostic_type = diagnostic_type


class RouterDecisionProvider(Protocol):
    """给 ambiguous Router case 使用的 typed decision provider 边界。"""

    async def decide(self, context: RouterInput) -> RouterProviderResult:
        """返回 Trivae-owned route projection。"""


@dataclass(frozen=True)
class RouterShadowObservation:
    """shadow Jev 的独立 bounded 结果，不参与 primary RouteDecision。"""

    route: RouteName | None
    latency_ms: float
    confidence: float | None = None
    probabilities: Mapping[str, float] | None = None
    usage: Mapping[str, int | float] | None = None
    provider: str | None = None
    model: str | None = None
    degraded: bool = False
    degradation_code: str | None = None
    provider_error_type: str | None = None

    def __post_init__(self) -> None:
        """拒绝未界定的 shadow 概率与错误状态，保证可安全写入 Trace。"""

        if self.route not in (None, "standard_execution", "planned_execution"):
            raise ValueError("shadow route must be a Router route or null")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("shadow latency must be a finite non-negative number")
        if self.degraded and not self.degradation_code:
            raise ValueError("degraded shadow observation must have a degradation code")
        if self.provider_error_type is not None and not self.provider_error_type.strip():
            raise ValueError("provider error type must be non-empty when present")
        _validate_probabilities(self.probabilities)


@dataclass(frozen=True)
class RouteDecision:
    """Router 的安全决定；不会携带工具参数、数据库结果或 trusted scope。"""

    route: RouteName
    confidence: float
    source: RouteSource
    reason: str
    degraded: bool = False
    degradation_code: str | None = None
    usage: Mapping[str, int | float] | None = None
    probabilities: Mapping[str, float] | None = None
    provider: str | None = None
    model: str | None = None
    primary_latency_ms: float | None = None
    shadow: RouterShadowObservation | None = None
    provider_error_type: str | None = None

    def __post_init__(self) -> None:
        """把 Router output 限制为两个 route 与有界的普通 metadata。"""

        if self.route not in ("standard_execution", "planned_execution"):
            raise ValueError("route must be standard_execution or planned_execution")
        if self.source not in ("rule", "llm", "jev", "evaluation_override"):
            raise ValueError("route source must be rule, llm, jev, or evaluation_override")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("route confidence must be numeric")
        if not math.isfinite(float(self.confidence)) or not 0 <= self.confidence <= 1:
            raise ValueError("route confidence must be between 0 and 1")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("route reason must be non-empty")
        if self.degraded and not self.degradation_code:
            raise ValueError("degraded route must have a degradation code")
        if self.primary_latency_ms is not None and (
            not math.isfinite(self.primary_latency_ms) or self.primary_latency_ms < 0
        ):
            raise ValueError("primary router latency must be finite and non-negative")
        if self.provider_error_type is not None and not self.provider_error_type.strip():
            raise ValueError("provider error type must be non-empty when present")
        _validate_probabilities(self.probabilities)
        if self.shadow is not None and not isinstance(self.shadow, RouterShadowObservation):
            raise ValueError("shadow must be a RouterShadowObservation")


class Router(Protocol):
    """Provider-neutral Router boundary。"""

    async def route(self, context: RouterInput) -> RouteDecision:
        """选择 standard 或 planned execution。"""


def router_context_projection(context: RouterInput) -> dict[str, object]:
    """生成既有 Router 可见状态；不包含 ExecutionScope 或 Capability inventory。"""

    # 对外只投影当前 LLM Router 原本使用的四类普通值。
    projected: dict[str, object] = {
        "query": context.query,
        "locale": context.locale,
        "prior_model_context": [
            {"role": message.role, "content": message.content}
            for message in context.prior_context
        ],
        "data_snapshot": dict(context.data_snapshot),
    }
    # 规范成 JSON 普通值，延续既有 data_snapshot 的 default=str 序列化语义。
    return json.loads(json.dumps(projected, ensure_ascii=False, default=str))


class RuleRouter:
    """以任务结构判断 route，避免单关键词业务特判。"""

    _STRUCTURED_QUERY = re.compile(
        r"(多少|数量|计数|统计|发言最多|发言量|排名|排名|总数|最近\s*\d+\s*(条|条消息)|每天的?发言)"
    )
    _RECOVERY = re.compile(r"(恢复|补充|完整上下文|前后文|继续调查|重新检索|追踪讨论|找回遗漏)")
    _MULTI_GOAL = re.compile(r"(并且|同时|以及|不仅.+还|先.+再|分别.+(?:并|以及)|并分析)")
    _TEMPORAL_CHANGE = re.compile(r"(从.+到.+(?:变化|演变|转变)|前后.+变化|期间.+后来|趋势(?:变化|演变))")
    _EVIDENCE_CHAIN = re.compile(r"(证据链|完整证据|依据.+判断|找出.+(?:并|然后).+(?:解释|判断|比较)|定位.+(?:然后|再))")
    _DEPENDENT_SEMANTIC = re.compile(r"(哪些.+为什么|比较.+并(?:说明|解释|判断)|关联.+原因|围绕.+追踪)")

    def __init__(
        self,
        completion: CompletionCallback | None = None,
        *,
        decision_provider: RouterDecisionProvider | None = None,
        jev_enabled: bool = False,
        provider_mode: RouterMode = "existing_llm",
        completion_timeout_seconds: float = 10.0,
        decision_timeout_seconds: float = 10.0,
    ) -> None:
        """注入可选 provider；无 Jev 设置时维持既有 Rule + LLM 行为。"""

        if completion_timeout_seconds <= 0 or decision_timeout_seconds <= 0:
            raise ValueError("router provider timeouts must be positive")
        if provider_mode not in ("existing_llm", "jev", "shadow"):
            raise ValueError("provider_mode must be existing_llm, jev, or shadow")
        self._completion = completion
        self._decision_provider = decision_provider
        self._jev_enabled = jev_enabled
        self._provider_mode = provider_mode
        self._completion_timeout_seconds = completion_timeout_seconds
        self._decision_timeout_seconds = decision_timeout_seconds

    async def aclose(self) -> None:
        """Application 关闭时释放可选 decision provider 持有的 transport。"""

        close = getattr(self._decision_provider, "aclose", None)
        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result

    async def route(self, context: RouterInput) -> RouteDecision:
        """先保留 deterministic Rule，再按配置执行 LLM、Jev 或 shadow。"""

        route_started = perf_counter()
        # 规则先于任意 provider；高置信 Rule 不会额外触发 Jev 或 LLM。
        static_decision = self._rule_decision(context.query)
        if static_decision.confidence >= 0.8:
            return replace(static_decision, primary_latency_ms=_elapsed_ms(route_started))
        # Jev primary 只替换 ambiguous provider；失败时由 `_route_jev` 保留 static route。
        if self._jev_enabled and self._provider_mode == "jev":
            return await self._route_jev(context, static_decision, route_started)
        # Shadow 同时发出两路请求，但只有 LLM/static primary 决定真实 execution route。
        if self._jev_enabled and self._provider_mode == "shadow":
            primary_task = asyncio.create_task(self._route_llm(context, static_decision, route_started))
            shadow_task = asyncio.create_task(self._route_jev(context, static_decision, perf_counter()))
            primary_decision, shadow_decision = await asyncio.gather(primary_task, shadow_task)
            return replace(primary_decision, shadow=_shadow_projection(shadow_decision))
        # Jev disabled 或 existing_llm mode 时保持当前基线行为。
        return await self._route_llm(context, static_decision, route_started)

    async def _route_llm(
        self,
        context: RouterInput,
        static_decision: RouteDecision,
        route_started: float,
    ) -> RouteDecision:
        """运行现有 strict-JSON fallback，并把调用错误与输出错误分别标记。"""

        if self._completion is None:
            return replace(static_decision, primary_latency_ms=_elapsed_ms(route_started))
        # LLM baseline 使用共享 context projection，reasoning/context 语义与 Jev 对齐。
        try:
            result = await asyncio.wait_for(
                invoke_completion(self._completion, self._build_prompt(context)),
                timeout=self._completion_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return replace(
                static_decision,
                degraded=True,
                degradation_code="ROUTER_COMPLETION_TIMEOUT",
                primary_latency_ms=_elapsed_ms(route_started),
            )
        except Exception as exc:
            # Provider call failure 与下面的 JSON contract failure 分开统计。
            return replace(
                static_decision,
                degraded=True,
                degradation_code="ROUTER_COMPLETION_PROVIDER_ERROR",
                primary_latency_ms=_elapsed_ms(route_started),
                provider_error_type=type(exc).__name__,
            )
        # 空 response、strict JSON 错误或未知 route 属于 provider output contract failure。
        try:
            if not isinstance(result.content, str) or not result.content.strip():
                raise ValueError("router completion returned no text")
            decision = self._parse_completion(result.content)
        except Exception:
            return replace(
                static_decision,
                degraded=True,
                degradation_code="ROUTER_COMPLETION_INVALID",
                primary_latency_ms=_elapsed_ms(route_started),
            )
        # Runtime completion observation 只投影实际 usage/provider/model，不保存 response text。
        observation = result.observation
        return replace(
            decision,
            usage=None if observation is None else observation.usage,
            provider=None if observation is None else observation.provider,
            model=None if observation is None else observation.model,
            primary_latency_ms=_elapsed_ms(route_started),
        )

    async def _route_jev(
        self,
        context: RouterInput,
        static_decision: RouteDecision,
        route_started: float,
    ) -> RouteDecision:
        """调用 Jev provider；所有失败都显式退回原静态 Rule route。"""

        if self._decision_provider is None:
            return replace(
                static_decision,
                degraded=True,
                degradation_code="JEV_ROUTER_PROVIDER_UNAVAILABLE",
                primary_latency_ms=_elapsed_ms(route_started),
            )
        # 对单次 Decision 设置本地上限，即使 mock/provider transport 不实现 timeout 也有界。
        try:
            result = await asyncio.wait_for(
                self._decision_provider.decide(context),
                timeout=self._decision_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return replace(
                static_decision,
                degraded=True,
                degradation_code="JEV_ROUTER_TIMEOUT",
                primary_latency_ms=_elapsed_ms(route_started),
            )
        except RouterDecisionProviderError as exc:
            return replace(
                static_decision,
                degraded=True,
                degradation_code=exc.code,
                primary_latency_ms=_elapsed_ms(route_started),
                provider_error_type=exc.diagnostic_type,
            )
        except Exception as exc:
            # 未分类适配器错误统一映射为稳定码，并只记录异常类型供 Trace 排查。
            return replace(
                static_decision,
                degraded=True,
                degradation_code="JEV_ROUTER_PROVIDER_ERROR",
                primary_latency_ms=_elapsed_ms(route_started),
                provider_error_type=type(exc).__name__,
            )
        # 重新通过 RouteDecision contract 验证注入 provider 的 plain projection。
        try:
            decision = RouteDecision(
                route=result.route,
                confidence=result.confidence,
                source="jev",
                reason="OpenRouter Jev Choice classified Planner value.",
                usage=result.usage,
                probabilities=result.probabilities,
                provider=result.provider,
                model=result.model,
                primary_latency_ms=_elapsed_ms(route_started),
            )
        except (AttributeError, TypeError, ValueError):
            return replace(
                static_decision,
                degraded=True,
                degradation_code="JEV_ROUTER_INVALID_RESPONSE",
                primary_latency_ms=_elapsed_ms(route_started),
            )
        return decision

    @classmethod
    def _rule_decision(cls, query: str) -> RouteDecision:
        """按多个任务结构信号判断，单一“分析/总结”词不改变标准路径。"""

        if cls._STRUCTURED_QUERY.search(query) and not cls._has_planning_signal(query):
            return RouteDecision(
                route="standard_execution",
                confidence=0.95,
                source="rule",
                reason="structured lookup or aggregation can use the standard execution path",
            )

        signals = sum(
            bool(pattern.search(query))
            for pattern in (
                cls._MULTI_GOAL,
                cls._TEMPORAL_CHANGE,
                cls._EVIDENCE_CHAIN,
                cls._DEPENDENT_SEMANTIC,
            )
        )
        if cls._RECOVERY.search(query) or signals >= 2:
            return RouteDecision(
                route="planned_execution",
                confidence=0.92,
                source="rule",
                reason="the request contains dependent investigation or recovery structure",
            )

        return RouteDecision(
            route="standard_execution",
            confidence=0.45,
            source="rule",
            reason="no decisive multi-stage structure was detected; standard path is conservative",
        )

    @classmethod
    def _has_planning_signal(cls, query: str) -> bool:
        """识别统计问题中的真正多阶段要求，避免结构化查询被误路由。"""

        return bool(
            cls._RECOVERY.search(query)
            or cls._MULTI_GOAL.search(query)
            or cls._TEMPORAL_CHANGE.search(query)
            or cls._EVIDENCE_CHAIN.search(query)
            or cls._DEPENDENT_SEMANTIC.search(query)
        )

    @staticmethod
    def _build_prompt(context: RouterInput) -> str:
        """把已有 context projection 编译为当前 baseline 使用的 strict-JSON prompt。"""

        # 与 Jev 共用四个状态字段；history 保留原有 role/content 投影和顺序。
        state = router_context_projection(context)
        prior_context = state["prior_model_context"]
        history = "\n".join(
            f"{message['role']}: {message['content']}"
            for message in prior_context
            if isinstance(message, Mapping)
        ) if isinstance(prior_context, list) else ""
        snapshot = json.dumps(state["data_snapshot"], ensure_ascii=False)
        return (
            "Classify the Trivae query into exactly one route. Return JSON only with keys "
            '`route` (standard_execution or planned_execution), `confidence` (0..1), and `reason`.\n'
            "Use planned_execution only when the query has dependent multi-stage investigation, "
            "temporal change plus evidence, or explicit context recovery. Simple lookup, count, "
            "ranking, or aggregation remains standard_execution.\n"
            f"locale: {state['locale']}\nquery: {state['query']}\n"
            f"prior model context:\n{history or '<none>'}\ndata snapshot: {snapshot}"
        )

    @staticmethod
    def _parse_completion(raw: str) -> RouteDecision:
        """严格解析 JSON；未知 route 或非法 confidence 进入 static degraded path。"""

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("router completion must be a JSON object")
        route = payload.get("route")
        confidence = payload.get("confidence")
        reason = payload.get("reason")
        if route not in ("standard_execution", "planned_execution"):
            raise ValueError("router completion returned an unknown route")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("router completion confidence must be numeric")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("router completion reason must be non-empty")
        return RouteDecision(
            route=route,
            confidence=max(0.0, min(1.0, float(confidence))),
            source="llm",
            reason=reason.strip()[:240],
        )


def _shadow_projection(decision: RouteDecision) -> RouterShadowObservation:
    """从 Jev-only primary-shaped result 提取 shadow branch 的 Trivae metadata。"""

    return RouterShadowObservation(
        route=None if decision.degraded else decision.route,
        latency_ms=decision.primary_latency_ms or 0.0,
        confidence=None if decision.degraded else decision.confidence,
        probabilities=None if decision.degraded else decision.probabilities,
        usage=decision.usage,
        provider=decision.provider,
        model=decision.model,
        degraded=decision.degraded,
        degradation_code=decision.degradation_code,
        provider_error_type=decision.provider_error_type,
    )


def _validate_probabilities(probabilities: Mapping[str, float] | None) -> None:
    """只接受 Router 两个既定 route 的 bounded probability projection。"""

    if probabilities is None:
        return
    if set(probabilities) != {"standard_execution", "planned_execution"}:
        raise ValueError("route probabilities must contain exactly the two Router routes")
    values = []
    for value in probabilities.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("route probabilities must be numeric")
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 1:
            raise ValueError("route probabilities must be between 0 and 1")
        values.append(number)
    if not math.isclose(math.fsum(values), 1.0, abs_tol=0.02):
        raise ValueError("route probabilities must sum to 1")


def _elapsed_ms(started_at: float) -> float:
    """统一将本地 monotonic elapsed 转换成 Trace 可接受的毫秒数。"""

    return max(0.0, (perf_counter() - started_at) * 1000)
