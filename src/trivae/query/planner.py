"""轻量、bounded、不可执行的 Query Planner。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from trivae.query.completion import CompletionCallback, complete_text
from trivae.query.contracts import QueryContext

PlanIntent = Literal["summary", "trend", "relationship", "search", "comparison", "evidence", "mixed"]
_INTENTS = {"summary", "trend", "relationship", "search", "comparison", "evidence", "mixed"}
_MAX_STEPS = 5
_MAX_CRITERIA = 5
_MAX_FIELD_LENGTH = 240


@dataclass(frozen=True)
class PlanStep:
    """一条给 runtime 的软 guidance，不描述可执行状态或 tool arguments。"""

    goal: str
    suggested_tools: tuple[str, ...] = ()
    evidence_needed: tuple[str, ...] = ()

    @property
    def suggested_capabilities(self) -> tuple[str, ...]:
        """提供 domain-neutral 读取别名，但公开 plan 字段以 suggested_tools 为准。"""

        return self.suggested_tools


@dataclass(frozen=True)
class Plan:
    """Planner 结构化输出；大小和文本长度都在边界内。"""

    version: int
    title: str
    intent: PlanIntent
    steps: tuple[PlanStep, ...]
    success_criteria: tuple[str, ...]


@dataclass(frozen=True)
class PlannerFailure:
    """Planner 失败的安全分类，不携带 provider 原始异常。"""

    code: Literal["generation_error", "timeout", "invalid_output", "unavailable", "aborted"]
    message: str


@dataclass(frozen=True)
class PlannerResult:
    """有 plan 或 failure 的显式结果；None plan 由 Orchestrator 继续 standard runtime。"""

    plan: Plan | None
    failure: PlannerFailure | None = None


class Planner(Protocol):
    """Provider-neutral Planner boundary。"""

    async def plan(self, context: QueryContext) -> PlannerResult:
        """生成一次 bounded soft plan。"""


PlannerInput = QueryContext


class SoftPlanner:
    """使用注入 completion 生成一次计划，失败时不阻塞主查询。"""

    def __init__(
        self,
        completion: CompletionCallback | None = None,
        *,
        completion_timeout_seconds: float = 10.0,
    ) -> None:
        """不注入 completion 时明确返回 unavailable，不创建隐藏 provider。"""

        if completion_timeout_seconds <= 0:
            raise ValueError("completion_timeout_seconds must be positive")
        self._completion = completion
        self._completion_timeout_seconds = completion_timeout_seconds

    async def plan(self, context: QueryContext) -> PlannerResult:
        """完成一次调用并严格解析；不会执行 plan steps。"""

        if self._completion is None:
            return PlannerResult(None, PlannerFailure("unavailable", "planner completion is not configured"))
        try:
            raw = await asyncio.wait_for(
                complete_text(self._completion, self._build_prompt(context)),
                timeout=self._completion_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return PlannerResult(None, PlannerFailure("timeout", "planner completion timed out"))
        except Exception:
            return PlannerResult(None, PlannerFailure("generation_error", "planner completion failed"))

        try:
            plan = self._parse(raw, context.available_capabilities)
        except Exception:
            return PlannerResult(None, PlannerFailure("invalid_output", "planner completion was invalid"))
        return PlannerResult(plan)

    @staticmethod
    def _build_prompt(context: QueryContext) -> str:
        """把 bounded query context 编译为 provider-neutral JSON 规划请求。"""

        snapshot = json.dumps(dict(context.data_snapshot), ensure_ascii=False, default=str)
        history = "\n".join(f"{message.role}: {message.content}" for message in context.prior_context)
        return (
            "Create a concise soft plan for this Trivae query. Return JSON only with keys: "
            "version (1), title, intent, steps, success_criteria. Each step has goal, "
            "suggested_tools, evidence_needed. Use only the supplied capabilities. "
            "The plan is guidance only, not an executable workflow.\n"
            f"locale: {context.locale}\nquery: {context.query}\n"
            f"prior model context:\n{history or '<none>'}\n"
            f"available capabilities: {list(context.available_capabilities)!r}\n"
            f"data snapshot: {snapshot}"
        )

    @classmethod
    def _parse(cls, raw: str, available_capabilities: tuple[str, ...]) -> Plan:
        """严格解析、过滤未知 capability、去重并应用 5/5 bounded contract。"""

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("planner output must be a JSON object")
        if payload.get("version") != 1:
            raise ValueError("planner version must be 1")

        title = cls._text(payload.get("title"), "title")
        raw_intent = payload.get("intent")
        if raw_intent not in _INTENTS:
            raise ValueError("planner intent is invalid")
        raw_steps = payload.get("steps")
        raw_criteria = payload.get("success_criteria")
        if not isinstance(raw_steps, list) or not isinstance(raw_criteria, list):
            raise ValueError("planner steps and success_criteria must be lists")

        allowed = set(available_capabilities)
        steps: list[PlanStep] = []
        for raw_step in raw_steps[:_MAX_STEPS]:
            if not isinstance(raw_step, dict):
                raise ValueError("planner step must be an object")
            goal = cls._text(raw_step.get("goal"), "step goal")
            capabilities = cls._names(raw_step.get("suggested_tools", ()), allowed)
            evidence = cls._texts(raw_step.get("evidence_needed", ()), "evidence_needed")
            steps.append(PlanStep(goal, capabilities, evidence))

        criteria = cls._texts(raw_criteria[:_MAX_CRITERIA], "success_criteria")
        if not steps or not criteria:
            raise ValueError("planner output must contain usable steps and criteria")
        return Plan(
            version=1,
            title=title,
            intent=raw_intent,
            steps=tuple(steps),
            success_criteria=tuple(criteria),
        )

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        """规范化单个文本字段，限制大小并拒绝空值。"""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"planner {field_name} must be non-empty text")
        return value.strip()[:_MAX_FIELD_LENGTH]

    @classmethod
    def _texts(cls, values: object, field_name: str) -> tuple[str, ...]:
        """规范化文本数组；空数组可作为 step 的可选 evidence。"""

        if not isinstance(values, (list, tuple)):
            raise ValueError(f"planner {field_name} must be a list")
        result: list[str] = []
        for value in values:
            text = cls._text(value, field_name)
            if text not in result:
                result.append(text)
        return tuple(result)

    @classmethod
    def _names(cls, values: object, allowed: set[str]) -> tuple[str, ...]:
        """只保留 registry 白名单内的 capability，并按首次出现顺序去重。"""

        if not isinstance(values, (list, tuple)):
            raise ValueError("planner suggested_tools must be a list")
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("planner capability name must be text")
            if value in allowed and value not in result:
                result.append(value)
        return tuple(result)


def render_plan_guidance(plan: Plan) -> str:
    """把 plan 变成短软提示；明确禁止将其解释为 executable workflow。"""

    lines = [
        "Soft plan guidance only; do not execute steps mechanically or invent missing evidence.",
        f"Intent: {plan.intent}. Goal: {plan.title}.",
    ]
    for index, step in enumerate(plan.steps, start=1):
        capabilities = ", ".join(step.suggested_tools) or "no specific capability suggestion"
        evidence = "; ".join(step.evidence_needed) or "state evidence limits explicitly"
        lines.append(f"{index}. {step.goal} (capabilities: {capabilities}; evidence: {evidence})")
    lines.append("Success criteria: " + "; ".join(plan.success_criteria))
    return "\n".join(lines)
