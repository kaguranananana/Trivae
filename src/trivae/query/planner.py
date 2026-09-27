"""轻量、bounded、不可执行的 Query Planner。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal, Protocol

from trivae.capabilities.contracts import CapabilityMetadata
from trivae.query.completion import (
    CompletionCallback,
    CompletionResult,
    invoke_completion,
)
from trivae.query.contracts import QueryContext

PlanIntent = Literal["summary", "trend", "relationship", "search", "comparison", "evidence", "mixed"]
_INTENTS = {"summary", "trend", "relationship", "search", "comparison", "evidence", "mixed"}
_MAX_STEPS = 5
_MAX_CRITERIA = 5
_MAX_FIELD_LENGTH = 240
_DEFAULT_COMPLETION_TIMEOUT_SECONDS = 20.0

# 这里只记录 Planner 选用关系，Tool 的用途正文继续来自 CapabilityMetadata。
# 新注册 Tool 必须显式补齐规划约束，避免 purpose 与选用规则悄悄漂移。
_PLANNING_GUIDANCE = {
    # purpose 已来自 Registry；这里只保留选用边界，避免重复完整 Tool 文档。
    "lexical_search": "Prefer for named entities, URLs and exact terms.",
    "search_messages": "Legacy exact-word retrieval; preserve named-entity anchors.",
    "semantic_search": "For conceptual recall; do not pair with lexical_search automatically.",
    "get_message_context": "For replies or feedback, deepen the most relevant direct share, recommendation, invitation or usage hit; ignore unrelated popularity updates.",
    "get_recent_messages": "For time windows or topic discovery; 'later' alone does not justify broad browsing.",
    "find_members": "For identity ambiguity, not who used a tool or expressed an opinion in message content.",
    "get_schema": "For structured SQL preparation, not result verification.",
    "execute_sql": "For scoped counts, ranks or filters; stop after a complete answer.",
}


@dataclass(frozen=True)
class PlannerCapabilitySummary:
    """Planner 独立读取的用途与选用约束；可用性仍由 QueryContext allowlist 决定。"""

    name: str
    purpose: str
    planning_guidance: str


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
class PlannerObservation:
    """一次 Planner 调用的安全事实，供 Trace 进行阶段化投影。"""

    # prompt 是 Planner 实际构造的 model-visible 文本，仅在 debug Trace 中保存正文。
    prompt: str
    # 该耗时包含 wait_for，能直接判断是否撞到 Planner 独立 timeout。
    latency_ms: float
    # completion request 是 provider-facing 的非敏感参数投影。
    request: Mapping[str, object]
    # 下列字段来自 Provider response，缺失时保留 None，不猜测。
    provider: str | None = None
    model: str | None = None
    provider_latency_ms: float | None = None
    finish_reason: str | None = None
    usage: Mapping[str, int | float] | None = None
    response_content: str | None = None
    # parse_stage/detail 由 Planner-owned parser 填写，明确拒绝发生在哪个 contract。
    parse_stage: str | None = None
    failure_detail_code: str | None = None


class PlannerParseError(ValueError):
    """把 JSON decode 与 Plan contract 失败转换成稳定、可测试的内部分类。"""

    def __init__(self, detail_code: str, parse_stage: str, diagnostic: str) -> None:
        # detail_code 是 Trace/debug 诊断键，不直接替换业务层 coarse error code。
        self.detail_code = detail_code
        # parse_stage 表达首次拒绝的 contract 边界。
        self.parse_stage = parse_stage
        # diagnostic 只描述本地 parser contract，不复制 Provider exception 正文。
        self.diagnostic = diagnostic
        super().__init__(diagnostic)


@dataclass(frozen=True)
class PlannerFailure:
    """Planner 失败的安全分类，不携带 provider 原始异常。"""

    code: Literal["generation_error", "timeout", "invalid_output", "unavailable", "aborted"]
    message: str
    # 业务层继续使用 code；以下字段只增加 debug attribution，不改变 degradation 语义。
    detail_code: str | None = None
    parse_stage: str | None = None
    diagnostic: str | None = None
    exception_type: str | None = None


@dataclass(frozen=True)
class PlannerResult:
    """有 plan 或 failure 的显式结果；None plan 由 Orchestrator 继续 standard runtime。"""

    plan: Plan | None
    failure: PlannerFailure | None = None
    # 成功和失败都携带同一次 completion 的安全事实，Orchestrator 决定是否写入 Trace。
    observation: PlannerObservation | None = None


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
        completion_timeout_seconds: float = _DEFAULT_COMPLETION_TIMEOUT_SECONDS,
        completion_request: Mapping[str, object] | None = None,
        capability_metadata: tuple[CapabilityMetadata, ...] = (),
    ) -> None:
        """不注入 completion 时明确返回 unavailable，不创建隐藏 provider。"""

        if completion_timeout_seconds <= 0:
            raise ValueError("completion_timeout_seconds must be positive")
        self._completion = completion
        self._completion_timeout_seconds = completion_timeout_seconds
        # timeout 时 Provider 可能没有 response，因此预先保存非敏感 request projection。
        self._completion_request = {} if completion_request is None else dict(completion_request)
        # purpose 直接取注册 Capability 的描述，避免 Planner 复制 Tool 文档。
        self._capability_summaries = tuple(
            PlannerCapabilitySummary(
                name=metadata.name,
                purpose=metadata.description,
                planning_guidance=_PLANNING_GUIDANCE[metadata.name],
            )
            for metadata in capability_metadata
        )

    @property
    def completion_timeout_seconds(self) -> float:
        """返回本次 Planner 使用的独立 completion timeout。"""

        return self._completion_timeout_seconds

    @property
    def completion_request(self) -> dict[str, object]:
        """返回可进入 Trace 的 provider request projection，不暴露 callback/SDK 对象。"""

        return dict(self._completion_request)

    async def plan(self, context: QueryContext) -> PlannerResult:
        """完成一次调用并严格解析；不会执行 plan steps。"""

        if self._completion is None:
            return PlannerResult(None, PlannerFailure("unavailable", "planner completion is not configured"))
        prompt = self._build_prompt(context, self._capability_summaries)
        started = perf_counter()
        try:
            completion_result = await asyncio.wait_for(
                invoke_completion(self._completion, prompt),
                timeout=self._completion_timeout_seconds,
            )
        except asyncio.TimeoutError:
            observation = self._observation(prompt, started, None, parse_stage="provider_request")
            return PlannerResult(
                None,
                PlannerFailure(
                    "timeout",
                    "planner completion timed out",
                    detail_code="completion_timeout",
                    parse_stage="provider_request",
                ),
                observation,
            )
        except Exception as exc:
            observation = self._observation(
                prompt,
                started,
                None,
                parse_stage="provider_request",
                failure_detail_code="provider_exception",
            )
            return PlannerResult(
                None,
                PlannerFailure(
                    "generation_error",
                    "planner completion failed",
                    detail_code="provider_exception",
                    parse_stage="provider_request",
                    exception_type=type(exc).__name__,
                ),
                observation,
            )

        observation = self._observation(prompt, started, completion_result)
        raw = completion_result.content
        # Provider length 先于 JSON parser 归因，避免把截断事实误报成普通 syntax error。
        if observation.finish_reason == "length":
            return PlannerResult(
                None,
                PlannerFailure(
                    "invalid_output",
                    "planner completion was truncated by the provider",
                    detail_code="provider_length",
                    parse_stage="provider_response",
                ),
                replace(observation, parse_stage="provider_response", failure_detail_code="provider_length"),
            )
        # 空 content 是 Provider response contract 失败，不进入 json.loads 猜测阶段。
        if not isinstance(raw, str) or not raw.strip():
            return PlannerResult(
                None,
                PlannerFailure(
                    "generation_error",
                    "planner completion returned empty output",
                    detail_code="empty_response",
                    parse_stage="provider_response",
                ),
                replace(observation, parse_stage="provider_response", failure_detail_code="empty_response"),
            )
        try:
            plan = self._parse(raw, context.available_capabilities)
        except PlannerParseError as exc:
            failed_observation = replace(
                observation,
                parse_stage=exc.parse_stage,
                failure_detail_code=exc.detail_code,
            )
            return PlannerResult(
                None,
                PlannerFailure(
                    "invalid_output",
                    "planner completion was invalid",
                    detail_code=exc.detail_code,
                    parse_stage=exc.parse_stage,
                    diagnostic=exc.diagnostic,
                ),
                failed_observation,
            )
        # 成功结果也保留 parse stage，方便 Debug Transcript 明确显示 decode/validation 已通过。
        return PlannerResult(plan, observation=replace(observation, parse_stage="plan_validation"))

    def _observation(
        self,
        prompt: str,
        started: float,
        completion_result: CompletionResult | None,
        *,
        parse_stage: str | None = None,
        failure_detail_code: str | None = None,
    ) -> PlannerObservation:
        """把 completion callback 结果规整成不含 SDK 对象的 Planner observation。"""

        completion = None if completion_result is None else completion_result.observation
        # Provider response request 优先；timeout/exception 则使用构造时的 projection。
        request = dict(self._completion_request)
        if completion is not None and completion.request:
            request = dict(completion.request)
        # Provider content 优先使用 adapter 的原始公开文本，fake 没提供时使用 callback 文本。
        response_content = None if completion_result is None else completion_result.content
        if completion is not None and completion.response_content is not None:
            response_content = completion.response_content
        # provider/model 从 response observation 读取，timeout 时从 request projection 读取。
        provider = None if completion is None else completion.provider
        model = None if completion is None else completion.model
        provider = provider or _optional_text(request.get("provider"))
        model = model or _optional_text(request.get("model"))
        return PlannerObservation(
            prompt=prompt,
            latency_ms=(perf_counter() - started) * 1000,
            request=request,
            provider=provider,
            model=model,
            provider_latency_ms=None if completion is None else completion.latency_ms,
            finish_reason=None if completion is None else completion.finish_reason,
            usage=None if completion is None else completion.usage,
            response_content=response_content,
            parse_stage=parse_stage,
            failure_detail_code=failure_detail_code,
        )

    @staticmethod
    def _build_prompt(
        context: QueryContext,
        capability_summaries: tuple[PlannerCapabilitySummary, ...] = (),
    ) -> str:
        """把 bounded query context 编译为 provider-neutral JSON 规划请求。"""

        snapshot = json.dumps(dict(context.data_snapshot), ensure_ascii=False, default=str)
        history = "\n".join(f"{message.role}: {message.content}" for message in context.prior_context)
        # allowlist 先过滤 summary；description 绝不能让未开放的 Tool 出现在 Planner 输入中。
        allowed = set(context.available_capabilities)
        summaries = [
            {
                "name": summary.name,
                "purpose": summary.purpose,
                "planning_guidance": summary.planning_guidance,
            }
            for summary in capability_summaries
            if summary.name in allowed
        ]
        return (
            "Create a concise soft plan for this Trivae query. Return JSON only with keys: "
            "version (1), title, intent, steps, success_criteria. "
            "intent MUST be exactly one of: summary, trend, relationship, search, comparison, evidence, mixed. "
            "steps MUST be a JSON array with 1 to 5 objects. Each step MUST have a non-empty string goal, "
            "suggested_tools as a JSON array of strings (it may be empty), and evidence_needed as a JSON array "
            "of strings (it may be empty). success_criteria MUST be a non-empty JSON array of strings with at "
            "most 5 items. Do not use a sentence or explanation as intent. Do not use null, an object, or a "
            "string where an array is required. Do not wrap the JSON in Markdown fences. Use only the supplied "
            "capabilities. The plan is guidance only, not an executable workflow. Keep every text concise. "
            # 全局规则只讲调查关系；Tool 选择条件由上面的短 guidance 承载。
            "Each step must add investigation value beyond the query; prefer one or two high-information "
            "steps over generic search, analysis, summary or verification. Keep a named entity as the "
            "primary investigation anchor, never a generic category alone; broaden only when anchored "
            "evidence cannot answer a requested need. For follow-up or actual-use feedback, find the "
            "relevant direct share, recommendation, invitation or usage discussion, then inspect its "
            "replies or context. A popularity update, repeated mention or intent to try is not firsthand use. "
            "Do not mechanically pair lexical and semantic search, browse recent messages for an entity "
            "follow-up, or use find_members for message-content questions. A complete scoped SQL count, "
            "rank or aggregation needs no retrieval verification. For a time-bounded question asking whether "
            "messages exist and what was discussed, use get_recent_messages before SQL: a complete empty "
            "window answers both. A SQL count alone is not verified zero-result evidence; do not add "
            "schema or SQL to recheck a complete empty retrieval.\n"
            f"locale: {context.locale}\nquery: {context.query}\n"
            f"prior model context:\n{history or '<none>'}\n"
            f"available capabilities: {list(context.available_capabilities)!r}\n"
            f"capability summaries: {json.dumps(summaries, ensure_ascii=False)}\n"
            f"data snapshot: {snapshot}"
        )

    @classmethod
    def _parse(cls, raw: str, available_capabilities: tuple[str, ...]) -> Plan:
        """严格解析、过滤未知 capability、去重并应用 5/5 bounded contract。"""

        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PlannerParseError(
                "json_decode_error",
                "json_decode",
                "planner output is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise PlannerParseError("invalid_root", "root_validation", "planner output must be a JSON object")
        if payload.get("version") != 1:
            raise PlannerParseError("invalid_version", "version_validation", "planner version must be 1")

        title = cls._text(payload.get("title"), "title")
        raw_intent = payload.get("intent")
        if raw_intent not in _INTENTS:
            raise PlannerParseError("invalid_intent", "intent_validation", "planner intent is invalid")
        if "steps" not in payload:
            raise PlannerParseError("missing_steps", "steps_validation", "planner steps are required")
        raw_steps = payload["steps"]
        raw_criteria = payload.get("success_criteria")
        if not isinstance(raw_steps, list):
            raise PlannerParseError("invalid_steps", "steps_validation", "planner steps must be a list")
        if not isinstance(raw_criteria, list):
            raise PlannerParseError(
                "invalid_success_criteria",
                "success_criteria_validation",
                "planner success_criteria must be a list",
            )

        allowed = set(available_capabilities)
        steps: list[PlanStep] = []
        for raw_step in raw_steps[:_MAX_STEPS]:
            if not isinstance(raw_step, dict):
                raise PlannerParseError("invalid_step", "steps_validation", "planner step must be an object")
            goal = cls._text(raw_step.get("goal"), "step goal")
            capabilities = cls._names(raw_step.get("suggested_tools", ()), allowed)
            evidence = cls._texts(raw_step.get("evidence_needed", ()), "evidence_needed")
            steps.append(PlanStep(goal, capabilities, evidence))

        criteria = cls._texts(raw_criteria[:_MAX_CRITERIA], "success_criteria")
        if not steps:
            raise PlannerParseError("empty_steps", "steps_validation", "planner steps must not be empty")
        if not criteria:
            raise PlannerParseError(
                "empty_success_criteria",
                "success_criteria_validation",
                "planner success_criteria must not be empty",
            )
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
            detail_code = {
                "title": "invalid_title",
                "step goal": "invalid_step_goal",
                "success_criteria": "invalid_success_criteria",
                "evidence_needed": "invalid_evidence_needed",
            }.get(field_name, "invalid_text")
            raise PlannerParseError(
                detail_code,
                f"{field_name.replace(' ', '_')}_validation",
                f"planner {field_name} must be non-empty text",
            )
        return value.strip()[:_MAX_FIELD_LENGTH]

    @classmethod
    def _texts(cls, values: object, field_name: str) -> tuple[str, ...]:
        """规范化文本数组；空数组可作为 step 的可选 evidence。"""

        if not isinstance(values, (list, tuple)):
            detail_code = "invalid_success_criteria" if field_name == "success_criteria" else "invalid_evidence_needed"
            raise PlannerParseError(
                detail_code,
                f"{field_name}_validation",
                f"planner {field_name} must be a list",
            )
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
            raise PlannerParseError(
                "invalid_suggested_tools",
                "suggested_tools_validation",
                "planner suggested_tools must be a list",
            )
        result: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise PlannerParseError(
                    "invalid_suggested_tools",
                    "suggested_tools_validation",
                    "planner capability name must be text",
                )
            if value in allowed and value not in result:
                result.append(value)
        return tuple(result)


def _optional_text(value: object) -> str | None:
    """只从 request projection 读取非空 identity，不把未知对象格式化进 Trace。"""

    return value if isinstance(value, str) and value else None


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
