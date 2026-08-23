"""两路 Query Router：先结构化判断，再按需使用受约束的文本 completion。"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from typing import Literal, Mapping, Protocol

from trivae.query.completion import CompletionCallback, complete_text
from trivae.query.contracts import QueryContext

RouteName = Literal["standard_execution", "planned_execution"]
RouteSource = Literal["rule", "llm", "evaluation_override"]
RouterInput = QueryContext


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

    def __post_init__(self) -> None:
        """把 provider 输出限制在两路 route 和稳定的 confidence 范围内。"""

        if self.route not in ("standard_execution", "planned_execution"):
            raise ValueError("route must be standard_execution or planned_execution")
        if self.source not in ("rule", "llm", "evaluation_override"):
            raise ValueError("route source must be rule, llm, or evaluation_override")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("route confidence must be numeric")
        if not 0 <= self.confidence <= 1:
            raise ValueError("route confidence must be between 0 and 1")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("route reason must be non-empty")
        if self.degraded and not self.degradation_code:
            raise ValueError("degraded route must have a degradation code")


class Router(Protocol):
    """Provider-neutral Router boundary。"""

    async def route(self, context: RouterInput) -> RouteDecision:
        """选择 standard 或 planned execution。"""


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
        completion_timeout_seconds: float = 10.0,
    ) -> None:
        """completion 是可选依赖；未注入时只使用本地规则，不隐式创建 provider。"""

        if completion_timeout_seconds <= 0:
            raise ValueError("completion_timeout_seconds must be positive")
        self._completion = completion
        self._completion_timeout_seconds = completion_timeout_seconds

    async def route(self, context: RouterInput) -> RouteDecision:
        """先得到 deterministic decision，只有低置信度时才请求可选 LLM。"""

        static_decision = self._rule_decision(context.query)
        if self._completion is None or static_decision.confidence >= 0.8:
            return static_decision

        try:
            raw = await asyncio.wait_for(
                complete_text(self._completion, self._build_prompt(context)),
                timeout=self._completion_timeout_seconds,
            )
            return self._parse_completion(raw)
        except asyncio.TimeoutError:
            return replace(
                static_decision,
                degraded=True,
                degradation_code="ROUTER_COMPLETION_TIMEOUT",
            )
        except Exception:
            # 解析/调用失败只影响可选分类来源；静态 route 仍保留并显式标记 degraded。
            return replace(
                static_decision,
                degraded=True,
                degradation_code="ROUTER_COMPLETION_INVALID",
            )

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
        """只发送 query 与显式 model context，不发送 ExecutionScope。"""

        snapshot = json.dumps(dict(context.data_snapshot), ensure_ascii=False, default=str)
        history = "\n".join(f"{message.role}: {message.content}" for message in context.prior_context)
        return (
            "Classify the Trivae query into exactly one route. Return JSON only with keys "
            '`route` (standard_execution or planned_execution), `confidence` (0..1), and `reason`.\n'
            "Use planned_execution only when the query has dependent multi-stage investigation, "
            "temporal change plus evidence, or explicit context recovery. Simple lookup, count, "
            "ranking, or aggregation remains standard_execution.\n"
            f"locale: {context.locale}\nquery: {context.query}\n"
            f"prior model context:\n{history or '<none>'}\ndata snapshot: {snapshot}"
        )

    @staticmethod
    def _parse_completion(raw: str) -> RouteDecision:
        """严格解析 JSON；未知 route 或字段不合法直接进入 degraded static path。"""

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
