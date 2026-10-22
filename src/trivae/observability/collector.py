"""Trace capture boundary、RuntimeEvent mapper 与 Tool operation context。"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal, cast

from trivae.observability.contracts import (
    FailureInfo,
    NormalizedQueryEvent,
    TraceContractError,
    TraceOutcome,
    TraceProfile,
    TraceStage,
    TraceStore,
)
from trivae.query.evidence import ToolResultRecord
from trivae.query.runtime.contracts import (
    AgentRunRequest,
    AgentRuntime,
    ModelBehaviorError,
    RuntimeErrorInfo,
    RuntimeEvent,
    RuntimeResult,
    RuntimeToolCall,
)
from trivae.query.runtime.usage import aggregate_usage


class TraceCaptureError(ValueError):
    """payload 无法在 bounded/redacted capture boundary 中安全投影。"""


def utc_now() -> str:
    """统一生成带 UTC offset 的观测时间。"""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class CapturePolicy:
    """normal/debug 两档 bounded capture policy，不扩展 Data Access Scope。"""

    profile: TraceProfile
    max_string_length: int
    max_items: int
    max_depth: int = 6
    secret_values: tuple[str, ...] = ()

    @classmethod
    def for_profile(
        cls,
        profile: TraceProfile,
        *,
        secret_values: tuple[str, ...] = (),
    ) -> CapturePolicy:
        """按显式 profile 选择固定上限；debug 只增加边界内完整度。"""

        if profile == "normal":
            return cls(profile, max_string_length=512, max_items=16, secret_values=secret_values)
        if profile == "debug":
            # Debug 要覆盖 AnswerArtifact 的 20,000 字符上限，避免最终答案被 Trace 提前截断。
            # 结构化 model-visible Tool Result 比普通 payload 多一层嵌套，因此放宽深度但仍有明确上限。
            return cls(
                profile,
                max_string_length=20_000,
                max_items=128,
                max_depth=10,
                secret_values=secret_values,
            )
        raise TraceCaptureError(f"unsupported trace profile: {profile!r}")

    def capture(self, payload: Mapping[str, object]) -> tuple[dict[str, object], tuple[str, ...]]:
        """递归投影普通值、去除 secret，并返回可见 limitation。"""

        if not isinstance(payload, Mapping):
            raise TraceCaptureError("trace payload must be a mapping")
        limitations: list[str] = []
        projected = self._project(payload, "payload", 0, limitations)
        if not isinstance(projected, dict):
            raise TraceCaptureError("trace payload projection must be a mapping")
        return projected, tuple(dict.fromkeys(limitations))

    def _project(
        self,
        value: object,
        path: str,
        depth: int,
        limitations: list[str],
    ) -> object:
        """逐层限制字符串、集合和嵌套深度，避免 JSON 编码器替我们猜类型。"""

        if depth > self.max_depth:
            limitations.append(f"{path}.depth_limited")
            return "[DEPTH_LIMITED]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            redacted = self._redact_string(value)
            if len(redacted) > self.max_string_length:
                limitations.append(f"{path}.truncated")
                return redacted[: self.max_string_length]
            return redacted
        if isinstance(value, Mapping):
            projected_mapping: dict[str, object] = {}
            items = list(value.items())
            for index, (key, item) in enumerate(items):
                if index >= self.max_items:
                    limitations.append(f"{path}.items_truncated")
                    break
                if not isinstance(key, str) or not key:
                    raise TraceCaptureError(f"{path} contains a non-string mapping key")
                child_path = f"{path}.{key}"
                if self._is_forbidden_context_key(key):
                    projected_mapping[key] = "[REDACTED]"
                    limitations.append(f"{child_path}.hidden_reasoning_redacted")
                    continue
                if self._is_secret_key(key):
                    projected_mapping[key] = "[REDACTED]"
                    continue
                projected_mapping[key] = self._project(item, child_path, depth + 1, limitations)
            return projected_mapping
        if isinstance(value, (list, tuple)):
            projected_items: list[object] = []
            for index, item in enumerate(value):
                if index >= self.max_items:
                    limitations.append(f"{path}.items_truncated")
                    break
                projected_items.append(self._project(item, f"{path}[{index}]", depth + 1, limitations))
            return projected_items
        raise TraceCaptureError(f"{path} contains unsupported value type: {type(value).__name__}")

    def _redact_string(self, value: str) -> str:
        """处理显式 secret marker 与常见 Authorization/Bearer 文本。"""

        redacted = value
        for secret in sorted((item for item in self.secret_values if item), key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        redacted = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]", redacted)
        return redacted

    @staticmethod
    def _is_secret_key(key: str) -> bool:
        """只匹配 credential 语义字段，不把 token count 等 operational facts 隐藏。"""

        normalized = key.lower().replace("-", "_")
        secret_fragments = (
            "api_key",
            "access_token",
            "client_secret",
            "authorization",
            "bearer",
            "password",
            "private_key",
            "deepseek_api",
            "openai_api",
            "dotenv_secret",
        )
        return any(fragment in normalized for fragment in secret_fragments)

    @staticmethod
    def _is_forbidden_context_key(key: str) -> bool:
        """显式阻断 hidden CoT 字段，即使调用方误把它交给 capture 也不落盘。"""

        normalized = key.lower().replace("-", "_")
        return normalized in {
            "chain_of_thought",
            "cot",
            "hidden_reasoning",
            "reasoning_content",
        }


class TraceCollector:
    """为单次 Query 分配 event identity/sequence，并持久化安全 payload。"""

    schema_version = 1

    def __init__(
        self,
        store: TraceStore,
        *,
        trace_id: str,
        request_id: str,
        profile: TraceProfile = "normal",
        started_at: str | None = None,
        secret_values: tuple[str, ...] = (),
        logger: logging.Logger | None = None,
        event_observer: Callable[[NormalizedQueryEvent], None] | None = None,
    ) -> None:
        """创建 Trace metadata；Store 失败只影响诊断完整度，不改变业务控制流。"""

        self.store = store
        self.trace_id = self._identity(trace_id, "trace_id")
        self.request_id = self._identity(request_id, "request_id")
        self.profile = profile
        self.started_at = started_at or utc_now()
        self.policy = CapturePolicy.for_profile(profile, secret_values=secret_values)
        self.logger = logger or logging.getLogger(__name__)
        # live observer 接收同 identity/sequence 的短生命周期 event；Query adapter 必须按字段白名单投影。
        self._event_observer = event_observer
        self._sequence = 0
        self._degraded = False
        self._warnings: list[str] = []
        try:
            self.store.create_trace(self.trace_id, self.request_id, self.profile, self.started_at)
        except Exception as exc:
            # 这里只捕获 Store 写入异常；Router/Runtime 等业务异常不会经过此分支。
            self._record_store_failure("CREATE_FAILED", exc)

    @property
    def is_degraded(self) -> bool:
        """返回是否发生过 capture/store diagnostic failure。"""

        return self._degraded

    @property
    def warnings(self) -> tuple[str, ...]:
        """返回稳定 warning code，避免把 provider/secret 异常正文带出。"""

        return tuple(self._warnings)

    def operation_context(
        self,
        operation_id: str,
        *,
        parent_operation_id: str | None = None,
    ) -> TraceOperationContext:
        """创建只携带本地 collector 的 operation context。"""

        return TraceOperationContext(self, operation_id, parent_operation_id)

    def emit(
        self,
        *,
        stage: TraceStage,
        operation: str,
        phase: Literal[
            "started",
            "completed",
            "failed",
            "degraded",
            "skipped",
            "aborted",
            "observed",
        ],
        operation_id: str,
        payload: Mapping[str, object] | None = None,
        parent_operation_id: str | None = None,
        outcome: TraceOutcome | None = None,
        duration_ms: float | None = None,
        limitations: tuple[str, ...] = (),
        failure: FailureInfo | None = None,
        occurred_at: str | None = None,
    ) -> NormalizedQueryEvent | None:
        """捕获、规范化并追加 event；capture/store 异常显式记录为 TRACE warning。"""

        self._sequence += 1
        raw_payload: Mapping[str, object] = {} if payload is None else payload
        try:
            captured_payload, capture_limitations = self.policy.capture(raw_payload)
            live_limitations = list(limitations)
            if self._degraded:
                live_limitations.append("trace_collector_degraded")
            all_limitations = live_limitations + list(capture_limitations)
            # 两个 projection 必须复用同一 identity/time，区别只在持久化 data-minimization。
            event_id = f"event-{uuid.uuid4().hex}"
            event_occurred_at = occurred_at or utc_now()
            event_observed_at = utc_now()
            event = NormalizedQueryEvent(
                schema_version=self.schema_version,
                event_id=event_id,
                trace_id=self.trace_id,
                request_id=self.request_id,
                sequence=self._sequence,
                occurred_at=event_occurred_at,
                observed_at=event_observed_at,
                stage=stage,
                operation=operation,
                phase=phase,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
                outcome=outcome,
                duration_ms=duration_ms,
                payload=captured_payload,
                limitations=tuple(dict.fromkeys(all_limitations)),
                failure=failure,
            )
            live_event = NormalizedQueryEvent(
                schema_version=self.schema_version,
                event_id=event_id,
                trace_id=self.trace_id,
                request_id=self.request_id,
                sequence=self._sequence,
                occurred_at=event_occurred_at,
                observed_at=event_observed_at,
                stage=stage,
                operation=operation,
                phase=phase,
                operation_id=operation_id,
                parent_operation_id=parent_operation_id,
                outcome=outcome,
                duration_ms=duration_ms,
                payload=raw_payload,
                limitations=tuple(dict.fromkeys(live_limitations)),
                failure=failure,
            )
        except (TraceCaptureError, TraceContractError) as exc:
            self._record_capture_failure("PAYLOAD_INVALID", exc)
            return None

        try:
            self.store.append_event(event)
        except Exception as exc:
            # append/constraint/connection failure 是 Trace degradation，不是业务 fallback。
            self._record_store_failure("APPEND_FAILED", exc)

        if stage == "query" and operation in {"query.completed", "query.failed", "query.aborted"}:
            terminal = {
                "query.completed": "completed",
                "query.failed": "failed",
                "query.aborted": "aborted",
            }[operation]
            try:
                self.store.mark_terminal(self.trace_id, terminal, event.observed_at)
            except Exception as exc:
                self._record_store_failure("TERMINAL_UPDATE_FAILED", exc)
        if self._event_observer is not None:
            # Store 使用 captured event；live consumer 使用同 identity 的 pre-capture event，避免答案被截断。
            # Observer 异常属于实时 consumer 本身，不能被误记为 Trace degradation 或静默吞掉。
            self._event_observer(live_event)
        return event

    def _record_capture_failure(self, code: str, exc: Exception) -> None:
        """把 capture failure 写入进程日志和 collector 状态，不伪造 persisted event。"""

        self._degraded = True
        self._warnings.append(f"TRACE.{code}")
        self.logger.error(
            "TRACE.%s trace_id=%s request_id=%s exception_type=%s",
            code,
            self.trace_id,
            self.request_id,
            type(exc).__name__,
        )

    def _record_store_failure(self, code: str, exc: Exception) -> None:
        """Store failure 必须可见，但不能阻塞原本可继续的 Query。"""

        self._degraded = True
        self._warnings.append(f"TRACE.{code}")
        self.logger.error(
            "TRACE.%s trace_id=%s request_id=%s exception_type=%s",
            code,
            self.trace_id,
            self.request_id,
            type(exc).__name__,
        )

    @staticmethod
    def _identity(value: str, field_name: str) -> str:
        """collector 不替调用者修正空 identity，避免 replay 关联漂移。"""

        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")
        return value.strip()


@dataclass(frozen=True)
class TraceOperationContext:
    """RuntimeContext/Tool 之间传递的本地 operation parent。"""

    collector: TraceCollector
    operation_id: str
    parent_operation_id: str | None = None

    def child(self, operation_id: str) -> TraceOperationContext:
        """为 Tool/Retrieval 建立稳定的父子 operation identity。"""

        return TraceOperationContext(self.collector, operation_id, self.operation_id)

    def emit(self, **kwargs: Any) -> NormalizedQueryEvent | None:
        """默认把当前 operation 作为 child event 的 operation identity。"""

        kwargs.setdefault("operation_id", self.operation_id)
        kwargs.setdefault("parent_operation_id", self.parent_operation_id)
        return self.collector.emit(**kwargs)


class TraceableAgentRuntime(AgentRuntime):
    """把 RuntimeEvent 或 run-only runtime 投影进当前 Trace，不改变 Runtime 结果。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        collector: TraceCollector,
        *,
        runtime_event_observer: Callable[[RuntimeEvent], None] | None = None,
        abort_event: object | None = None,
    ) -> None:
        self.runtime = runtime
        self.collector = collector
        self._runtime_event_observer = runtime_event_observer
        # 优雅取消信号原样透传给 streaming runtime；run-only runtime 不支持时显式暴露。
        self._abort_event = abort_event
        self._run_operation_id = "runtime.run"
        self._last_turn_operation_id: str | None = None

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        """优先消费 stream；缺少 stream 的测试 runtime 只补 start/terminal 边界。"""

        self._last_turn_operation_id = None
        trace_context = self._request_trace_context(request)
        runtime_request = replace(request, trace_context=trace_context)
        stream = getattr(self.runtime, "stream", None)
        if callable(stream):
            if self._abort_event is not None:
                return await self._run_stream(stream, runtime_request, abort_event=self._abort_event)
            return await self._run_stream(stream, runtime_request)
        if self._abort_event is not None:
            # 静默忽略 abort 会把 Stop 变成假取消，这里必须显式暴露 contract 缺口。
            raise ValueError("graceful abort requires a streaming runtime")

        self.collector.emit(
            stage="runtime",
            operation="runtime.run",
            phase="started",
            operation_id=self._run_operation_id,
            payload={"runtime_mode": "run_only"},
        )
        try:
            result = await self.runtime.run(runtime_request)
        except Exception as exc:
            self._emit_runtime_exception(exc)
            raise
        if result.run_id is None and not result.tool_results:
            # run-only 注入 runtime 没有 provider identity 时补充 Trivae-owned run identity；
            # 有 provenance record 却缺 run_id 则保持缺失，让 Finalizer 显式暴露 contract error。
            result = replace(result, run_id=f"run-{uuid.uuid4().hex}")
        self._map_terminal_result(result)
        return result

    async def _run_stream(
        self,
        stream: Any,
        request: AgentRunRequest,
        *,
        abort_event: object | None = None,
    ) -> RuntimeResult:
        """逐条映射非 delta RuntimeEvent，并保留底层 terminal result。"""

        terminal: RuntimeResult | None = None
        # 记录 observer 失败前已经观察到的 canonical provenance，确保失败终态不丢失真实进度。
        observed_tool_calls: list[RuntimeToolCall] = []
        observed_tool_results: list[ToolResultRecord] = []
        response_usage: dict[int, Mapping[str, int | float] | None] = {}
        response_number = 0
        terminal_usage: Mapping[str, int | float] | None = None
        last_tool_round = 0
        last_event: RuntimeEvent | None = None
        last_provider_observation: Mapping[str, object] | None = None
        stream_iterator = stream(request) if abort_event is None else stream(request, abort_event)
        try:
            async for event in stream_iterator:
                if not isinstance(event, RuntimeEvent):
                    raise TypeError("runtime stream must yield RuntimeEvent values")
                # 先保存当前事件及其 terminal 快照，再调用 live observer；parser 可能在 observer 内失败。
                last_event = event
                if event.type == "turn_started":
                    # 在途响应即使用量未知也占一个位置，不能把它当成零 Token。
                    response_number += 1
                    response_usage[response_number] = None
                if event.provider_observation is not None:
                    # parser 可能在后续 content delta 中失败，不能因 last_event 被覆盖而丢掉
                    # 最近一次 provider response 的 bounded transport facts。
                    last_provider_observation = event.provider_observation
                if event.tool_call is not None and event.tool_call not in observed_tool_calls:
                    observed_tool_calls.append(event.tool_call)
                if event.tool_result is not None and event.tool_result not in observed_tool_results:
                    observed_tool_results.append(event.tool_result)
                if event.result is not None:
                    for tool_call in event.result.tool_calls:
                        if tool_call not in observed_tool_calls:
                            observed_tool_calls.append(tool_call)
                    for tool_result in event.result.tool_results:
                        if tool_result not in observed_tool_results:
                            observed_tool_results.append(tool_result)
                    if event.result.usage is not None:
                        terminal_usage = event.result.usage
                    last_tool_round = max(last_tool_round, event.result.tool_rounds)
                if event.usage is not None:
                    if event.type == "usage_update":
                        # usage_update 是单次响应事实，同一响应更新只覆盖本响应，不能覆盖整个 Run。
                        response_usage[response_number] = event.usage
                if event.type == "tool_completed":
                    # 模型回合编号可能属于最终综合；只有实际完成的工具才推进工具轮次。
                    completed_round = event.tool_call.round if event.tool_call is not None else event.tool_round
                    if completed_round is not None:
                        last_tool_round = max(last_tool_round, completed_round)
                if self._runtime_event_observer is not None:
                    # 同一 RuntimeEvent 先进入 live projection，再由 persistent mapper选择可落盘事实。
                    self._runtime_event_observer(event)
                self._map_runtime_event(event)
                if event.type in {"completed", "failed", "aborted"}:
                    terminal = event.result
            if terminal is None:
                raise RuntimeError("runtime stream ended without a terminal result")
            return terminal
        except ModelBehaviorError as exc:
            # 模型输出解析失败是 Runtime 的已知行为错误：保留稳定 type，转换为失败 terminal，禁止裸异常穿透 Query。
            if last_event is None:
                raise
            result = RuntimeResult(
                final_answer=None,
                provider=last_event.provider,
                model=last_event.model,
                termination="failed",
                tool_calls=tuple(observed_tool_calls),
                error=RuntimeErrorInfo(
                    code="RUNTIME_ERROR",
                    message="agent runtime execution failed",
                    category="model_behavior",
                    diagnostic_type=type(exc).__name__,
                    exception_type=type(exc).__name__,
                ),
                usage=terminal_usage if terminal_usage is not None else aggregate_usage(response_usage.values()),
                tool_rounds=last_tool_round,
                run_id=last_event.run_id or (last_event.result.run_id if last_event.result else None),
                tool_results=tuple(observed_tool_results),
            )
            failed_event = RuntimeEvent(
                type="failed",
                provider=result.provider,
                model=result.model,
                sequence=last_event.sequence + 1,
                result=result,
                run_id=result.run_id,
                usage=result.usage,
                provider_observation=last_provider_observation,
            )
            if self._runtime_event_observer is not None:
                # failed event 不再携带 content delta；live adapter 可以明确关闭开放段并展示失败。
                self._runtime_event_observer(failed_event)
            self._map_runtime_event(failed_event)
            return result
        except Exception as exc:
            # 先记录稳定异常类型，再原样抛出，业务层仍能看到真实根因。
            self._emit_runtime_exception(exc)
            raise
        finally:
            # Observer 在 delta 事件中失败时，async for 不保证立即关闭底层 async generator；
            # 显式收口，避免 provider client 和 ContextVar cleanup 泄漏到 event loop shutdown。
            close = getattr(stream_iterator, "aclose", None)
            if callable(close):
                await close()

    def _request_trace_context(self, request: AgentRunRequest) -> TraceOperationContext:
        """复用上游 Query operation context，否则建立 runtime root context。"""

        existing = request.trace_context
        if isinstance(existing, TraceOperationContext):
            return existing
        return self.collector.operation_context(self._run_operation_id)

    def _map_runtime_event(self, event: RuntimeEvent) -> None:
        """将 RuntimeEvent 家族映射为 Trivae normalized Runtime/Model facts。"""

        run_id = event.run_id or self._run_operation_id
        run_operation = f"runtime:{run_id}"
        turn_operation = self._turn_operation_id(run_operation, event)
        payload: dict[str, object] = {
            "runtime_event_type": event.type,
            "provider": event.provider,
            "model": event.model,
        }
        if event.run_id is not None:
            payload["run_id"] = event.run_id
        if event.tool_round is not None:
            payload["tool_round"] = event.tool_round
        if event.tool_name is not None:
            payload["tool_name"] = event.tool_name
        if event.tool_call_id is not None:
            payload["tool_call_id"] = event.tool_call_id
        if event.tool_call is not None:
            # RuntimeToolCall 已是 Trivae-owned 状态；只把状态/错误码带入 Trace，不带 SDK 参数对象。
            payload["tool_status"] = event.tool_call.status
            if event.tool_call.error_code is not None:
                payload["tool_error_code"] = event.tool_call.error_code
            if event.tool_call.tool_result_budget is not None:
                # 每个 completed Tool 都保留自己的预算快照，便于解释累计 pool 的归因。
                payload["tool_result_budget"] = event.tool_call.tool_result_budget.to_dict()
            for field_name, payload_name in (
                ("model_result_projected_messages", "projected_messages"),
                ("model_result_omitted_messages", "omitted_messages"),
                ("model_result_omitted_context_messages", "omitted_context_messages"),
                ("model_result_omitted_hit_messages", "omitted_hit_messages"),
            ):
                value = getattr(event.tool_call, field_name)
                if isinstance(value, int) and not isinstance(value, bool):
                    payload[payload_name] = value
            if event.tool_call.model_result_truncated is not None:
                payload["projection_truncated"] = event.tool_call.model_result_truncated
        if event.usage is not None:
            payload["usage"] = dict(event.usage)
        if event.model_visible_context is not None:
            payload["model_visible_context"] = [dict(item) for item in event.model_visible_context]
        if event.observable_output is not None:
            payload["observable_output"] = [dict(item) for item in event.observable_output]
        if event.provider_observation is not None:
            # Provider 诊断只落 shape/status/id/usage 等 bounded facts，不落正文或 hidden reasoning。
            payload["provider_observation"] = dict(event.provider_observation)

        if event.type == "run_started":
            self.collector.emit(
                stage="runtime",
                operation="runtime.run",
                phase="started",
                operation_id=run_operation,
                payload=payload,
            )
        elif event.type == "turn_started":
            self.collector.emit(
                stage="model",
                operation="model.turn",
                phase="started",
                operation_id=turn_operation,
                parent_operation_id=run_operation,
                payload=payload,
            )
        elif event.type == "model_output":
            self.collector.emit(
                stage="model",
                operation="model.output",
                phase="completed",
                operation_id=turn_operation,
                parent_operation_id=run_operation,
                outcome="ok",
                payload=payload,
            )
        elif event.type == "usage_update":
            self.collector.emit(
                stage="model",
                operation="model.usage",
                phase="observed",
                operation_id=turn_operation,
                parent_operation_id=run_operation,
                payload=payload,
            )
        elif event.type == "tool_started":
            tool_operation = f"{run_operation}:runtime-tool:{event.tool_call_id or event.sequence}"
            self.collector.emit(
                stage="runtime",
                operation="runtime.tool.started",
                phase="started",
                operation_id=tool_operation,
                parent_operation_id=run_operation,
                payload=payload,
            )
        elif event.type == "tool_completed":
            tool_operation = f"{run_operation}:runtime-tool:{event.tool_call_id or event.sequence}"
            status = event.tool_call.status if event.tool_call is not None else "ok"
            failure = None
            outcome: TraceOutcome = "ok"
            phase: Literal["completed", "failed"] = "completed"
            if status in {"error", "failed"}:
                outcome = "error"
                phase = "failed"
                failure = FailureInfo(
                    error_code=(event.tool_call.error_code if event.tool_call is not None else None)
                    or "TOOL_EXECUTION_FAILED",
                    origin_stage="tool",
                    observed_stage="runtime",
                    category="tool",
                    handling="returned_to_agent" if status == "error" else "terminal",
                    cause_operation_id=tool_operation,
                )
            self.collector.emit(
                stage="runtime",
                operation="runtime.tool.completed",
                phase=phase,
                operation_id=tool_operation,
                parent_operation_id=run_operation,
                outcome=outcome,
                payload=payload,
                # canonical ToolResult 已确认的限制必须进入 Trace 顶层，不能只留在最终 Artifact。
                limitations=event.tool_result.limitations if event.tool_result is not None else (),
                failure=failure,
            )
        elif event.type == "turn_completed":
            self.collector.emit(
                stage="model",
                operation="model.turn",
                phase="completed",
                operation_id=turn_operation,
                parent_operation_id=run_operation,
                outcome="ok",
                payload=payload,
            )
        elif event.type == "finalizing":
            payload["budget_kind"] = event.budget_kind or "tool_rounds"
            self.collector.emit(
                stage="runtime",
                operation="runtime.finalizing",
                phase="started",
                operation_id=f"{run_operation}:finalizing",
                parent_operation_id=run_operation,
                payload=payload,
                limitations=(
                    "tool_result_budget_exhausted" if event.budget_kind == "tool_result_tokens"
                    else "tool_budget_exhausted",
                ),
            )
        elif event.type in {"completed", "failed", "aborted"}:
            self._map_terminal_event(event, run_operation, payload)
        # thinking/content delta 有意不进入 persistent Trace，避免 reasoning/token 永久存储。

    def _turn_operation_id(self, run_operation: str, event: RuntimeEvent) -> str:
        """把同一模型轮次的 started/usage/completed 绑定到同一个 operation。"""

        if event.type == "turn_started" or self._last_turn_operation_id is None:
            round_number = event.tool_round if event.tool_round and event.tool_round > 0 else event.sequence
            self._last_turn_operation_id = f"{run_operation}:turn:{round_number}"
        return self._last_turn_operation_id

    def _map_terminal_event(
        self,
        event: RuntimeEvent,
        run_operation: str,
        payload: dict[str, object],
    ) -> None:
        """区分 completed、budget、runtime failure 和 abort 的 terminal 语义。"""

        result = event.result
        if result is None:
            raise RuntimeError("terminal RuntimeEvent is missing RuntimeResult")
        payload["termination"] = result.termination
        payload["tool_count"] = len(result.tool_calls)
        payload["tool_rounds"] = result.tool_rounds
        # 终态是 Runtime 累计快照；Trace metrics 必须据此替换逐响应统计，不能重复相加。
        payload["usage"] = None if result.usage is None else dict(result.usage)
        projection_estimates = [
            call.model_result_estimated_tokens
            for call in result.tool_calls
            if call.model_result_estimated_tokens is not None
        ]
        payload["tool_result_estimated_tokens"] = (
            0
            if not result.tool_calls
            else sum(projection_estimates)
            if len(projection_estimates) == len(result.tool_calls)
            else "unavailable"
        )
        payload["tool_result_projection_truncated_count"] = sum(
            1 for call in result.tool_calls if call.model_result_truncated is True
        )
        payload["tool_result_projection_omitted_hit_messages"] = sum(
            call.model_result_omitted_hit_messages or 0 for call in result.tool_calls
        )
        payload["tool_result_projection_omitted_context_messages"] = sum(
            call.model_result_omitted_context_messages or 0 for call in result.tool_calls
        )
        payload["tool_result_projection_projected_messages"] = sum(
            call.model_result_projected_messages or 0 for call in result.tool_calls
        )
        payload["tool_result_projection_omitted_messages"] = sum(
            call.model_result_omitted_messages or 0 for call in result.tool_calls
        )
        budget_snapshots = [
            call.tool_result_budget
            for call in result.tool_calls
            if call.tool_result_budget is not None
        ]
        if budget_snapshots:
            # 同一 Runtime run 的配置一致；terminal 额外保存首个配置和最后余额，具体调用仍在 timeline。
            first_budget = budget_snapshots[0]
            last_budget = budget_snapshots[-1]
            payload["budget_mode"] = first_budget.budget_mode
            payload["context_window_tokens"] = first_budget.context_window_tokens
            payload["context_window_source"] = first_budget.context_window_source
            payload["per_call_tool_result_percent"] = first_budget.per_call_tool_result_percent
            payload["per_call_tool_result_cap"] = first_budget.per_call_tool_result_cap
            payload["per_call_tool_result_ceiling"] = first_budget.per_call_tool_result_ceiling
            payload["run_tool_evidence_percent"] = first_budget.run_tool_evidence_percent
            payload["run_tool_evidence_cap"] = first_budget.run_tool_evidence_cap
            payload["run_tool_evidence_budget"] = first_budget.run_tool_evidence_budget
            payload["remaining_run_tool_evidence_budget"] = (
                last_budget.remaining_run_tool_evidence_budget_after_call
            )
            payload["tool_result_budget_call_count"] = len(budget_snapshots)
        if result.final_answer is not None:
            payload["final_answer"] = result.final_answer
        if result.error is not None:
            payload["error_code"] = result.error.code
            payload["error_category"] = result.error.category
            payload["diagnostic_type"] = result.error.diagnostic_type
            payload["exception_type"] = result.error.exception_type

        if event.type == "completed":
            self.collector.emit(
                stage="runtime",
                operation="runtime.run",
                phase="completed",
                operation_id=run_operation,
                outcome="ok",
                payload=payload,
            )
            return

        if event.type == "aborted" or result.termination == "aborted":
            failure = FailureInfo(
                error_code=result.error.code if result.error is not None else "RUN_ABORTED",
                origin_stage="runtime",
                observed_stage="runtime",
                category="cancellation",
                handling="aborted",
                cause_operation_id=run_operation,
            )
            self.collector.emit(
                stage="runtime",
                operation="runtime.run",
                phase="aborted",
                operation_id=run_operation,
                outcome="aborted",
                payload=payload,
                failure=failure,
            )
            return

        is_budget = result.termination == "max_turns_exceeded"
        failure = FailureInfo(
            error_code="BUDGET_MAX_TURNS" if is_budget else (result.error.code if result.error else "RUNTIME_ERROR"),
            origin_stage="runtime",
            observed_stage="runtime",
            category="budget" if is_budget else (result.error.category or "terminal" if result.error else "terminal"),
            handling="terminal",
            cause_operation_id=run_operation,
        )
        self.collector.emit(
            stage="runtime",
            operation="runtime.run",
            phase="failed",
            operation_id=run_operation,
            outcome="error",
            payload=payload,
            limitations=("budget_exhausted",) if is_budget else (),
            failure=failure,
        )

    def _map_terminal_result(self, result: RuntimeResult) -> None:
        """run-only runtime 的结果映射复用同一 terminal ownership。"""

        event_type = {
            "completed": "completed",
            "aborted": "aborted",
            "failed": "failed",
            "max_turns_exceeded": "failed",
        }[result.termination]
        event = RuntimeEvent(
            type=cast(Literal["completed", "failed", "aborted"], event_type),
            provider=result.provider,
            model=result.model,
            sequence=0,
            result=result,
            run_id=result.run_id,
            usage=result.usage,
        )
        self._map_terminal_event(
            event,
            self._run_operation_id,
            {
                "runtime_mode": "run_only",
                "provider": result.provider,
                "model": result.model,
            },
        )

    def _emit_runtime_exception(self, exc: Exception) -> None:
        """记录 wrapper 观察到的 runtime exception，然后让原异常继续上抛。"""

        self.collector.emit(
            stage="runtime",
            operation="runtime.run",
            phase="failed",
            operation_id=self._run_operation_id,
            outcome="error",
            payload={"exception_type": type(exc).__name__},
            failure=FailureInfo(
                error_code="RUNTIME_EXCEPTION",
                origin_stage="runtime",
                observed_stage="runtime",
                category="exception",
                handling="propagated",
                cause_operation_id=self._run_operation_id,
                diagnostic_reference=type(exc).__name__,
            ),
        )

    async def complete_text(self, prompt: str) -> str:
        """转发可选 Router/Planner completion，不把它伪装成 Query Runtime。"""

        completion = getattr(self.runtime, "complete_text", None)
        if not callable(completion):
            raise RuntimeError("wrapped runtime does not provide complete_text")
        return await completion(prompt)

    async def aclose(self) -> None:
        """关闭底层 runtime，不负责关闭 Trace Store。"""

        close = getattr(self.runtime, "aclose", None)
        if callable(close):
            result = close()
            if hasattr(result, "__await__"):
                await result
