"""Retrieval-facing Tool wrapper。"""

from __future__ import annotations

from time import perf_counter
from typing import Literal

from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecutionScope,
    SearchMessagesInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.observability.collector import TraceOperationContext
from trivae.observability.contracts import FailureInfo
from trivae.retrieval.structured import (
    InvalidRetrievalQuery,
    LexicalIndexError,
    RetrievalError,
    RetrievalResult,
)


class SearchMessagesTool:
    """只负责 Tool envelope；SQL/FTS/context/order 全部留在 Retrieval Core。"""

    name = "search_messages"

    def __init__(self, capability: SearchMessagesCapability) -> None:
        self.capability = capability

    def invoke(self, request: SearchMessagesInput, scope: ExecutionScope) -> ToolEnvelope:
        """把已分类的 contract/retrieval 错误投影为统一状态，未知异常继续暴露。"""

        envelope, _ = self._invoke_with_origin(request, scope)
        return envelope

    def _invoke_with_origin(
        self,
        request: SearchMessagesInput,
        scope: ExecutionScope,
    ) -> tuple[ToolEnvelope, Literal["tool", "retrieval"] | None]:
        """内部保留错误 owner，公开 invoke 仍只返回既有 ToolEnvelope。"""

        try:
            result = self.capability.execute(request, scope)
        except CapabilityContractError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code=exc.error_code, message=str(exc)),
                ),
                "tool",
            )
        except InvalidRetrievalQuery as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="INVALID_ARGUMENT", message=str(exc)),
                ),
                "retrieval",
            )
        except LexicalIndexError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="CAPABILITY_UNAVAILABLE", message=str(exc)),
                ),
                "retrieval",
            )
        except RetrievalError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="EXECUTION_ERROR", message=str(exc)),
                ),
                "retrieval",
            )

        return (
            ToolEnvelope(
                status="partial" if result.partial else "ok",
                data=result,
                meta={
                    "truncated": result.truncated,
                    "total_hits": result.total_hits,
                    "returned_messages": result.returned_messages,
                },
                error=None,
            ),
            None,
        )

    def invoke_with_trace(
        self,
        request: SearchMessagesInput,
        scope: ExecutionScope,
        trace_context: object,
    ) -> ToolEnvelope:
        """记录 Tool→Retrieval 因果，但不改变既有 envelope 和 exception 语义。"""

        if not isinstance(trace_context, TraceOperationContext):
            raise TypeError("SearchMessagesTool requires TraceOperationContext")
        tool_operation = trace_context.operation_id
        retrieval_operation = f"{tool_operation}:retrieval"
        started = perf_counter()
        trace_context.emit(
            stage="tool",
            operation="tool.call.started",
            phase="started",
            operation_id=tool_operation,
            parent_operation_id=trace_context.parent_operation_id,
            payload={"tool_name": self.name, "request": self._request_payload(request)},
        )
        retrieval_started = perf_counter()
        trace_context.emit(
            stage="retrieval",
            operation="retrieval.search.started",
            phase="started",
            operation_id=retrieval_operation,
            parent_operation_id=tool_operation,
            payload={"strategy": "lexical", "query": self._request_payload(request)},
        )
        try:
            envelope, origin = self._invoke_with_origin(request, scope)
        except Exception as exc:
            # 未知异常保持原样上抛；Trace 只补充 observed failure attribution。
            trace_context.emit(
                stage="retrieval",
                operation="retrieval.search.failed",
                phase="failed",
                operation_id=retrieval_operation,
                parent_operation_id=tool_operation,
                outcome="error",
                duration_ms=(perf_counter() - retrieval_started) * 1000,
                payload={"exception_type": type(exc).__name__},
                failure=self._failure(
                    "RETRIEVAL_EXCEPTION",
                    origin_stage="retrieval",
                    observed_stage="tool",
                    handling="propagated",
                    diagnostic_reference=type(exc).__name__,
                    cause_operation_id=retrieval_operation,
                ),
            )
            trace_context.emit(
                stage="tool",
                operation="tool.call.failed",
                phase="failed",
                operation_id=tool_operation,
                parent_operation_id=trace_context.parent_operation_id,
                outcome="error",
                duration_ms=(perf_counter() - started) * 1000,
                payload={"tool_name": self.name, "exception_type": type(exc).__name__},
                failure=self._failure(
                    "TOOL_EXCEPTION",
                    origin_stage="tool",
                    observed_stage="tool",
                    handling="propagated",
                    diagnostic_reference=type(exc).__name__,
                    cause_operation_id=tool_operation,
                ),
            )
            raise

        error = envelope.error
        if error is None and isinstance(envelope.data, RetrievalResult):
            trace_context.emit(
                stage="retrieval",
                operation="retrieval.search.completed",
                phase="completed",
                operation_id=retrieval_operation,
                parent_operation_id=tool_operation,
                outcome="partial" if envelope.status == "partial" else "ok",
                duration_ms=(perf_counter() - retrieval_started) * 1000,
                payload=self._retrieval_payload(envelope.data),
            )
        elif error is not None and origin == "retrieval":
            # 已进入 Retrieval 后的错误仍归 Retrieval ownership，Tool 只是观察并返回 envelope。
            trace_context.emit(
                stage="retrieval",
                operation="retrieval.search.failed",
                phase="failed",
                operation_id=retrieval_operation,
                parent_operation_id=tool_operation,
                outcome="error",
                duration_ms=(perf_counter() - retrieval_started) * 1000,
                payload={"error_code": error.code},
                failure=self._failure(
                    error.code,
                    origin_stage="retrieval",
                    observed_stage="tool",
                    handling="returned_to_agent",
                    cause_operation_id=retrieval_operation,
                ),
            )
        elif error is not None and origin == "tool":
            # Tool contract 在 capability boundary 已失败，补一个显式 skipped 结尾避免悬空 retrieval.started。
            trace_context.emit(
                stage="retrieval",
                operation="retrieval.search.skipped",
                phase="skipped",
                operation_id=retrieval_operation,
                parent_operation_id=tool_operation,
                outcome="error",
                duration_ms=(perf_counter() - retrieval_started) * 1000,
                payload={"error_code": error.code},
                limitations=("tool_contract_error",),
            )
        tool_phase = "failed" if error is not None else "completed"
        trace_context.emit(
            stage="tool",
            operation="tool.call.failed" if error is not None else "tool.call.completed",
            phase=tool_phase,
            operation_id=tool_operation,
            parent_operation_id=trace_context.parent_operation_id,
            outcome="error" if error is not None else ("partial" if envelope.status == "partial" else "ok"),
            duration_ms=(perf_counter() - started) * 1000,
            payload={
                "tool_name": self.name,
                "status": envelope.status,
                "error_code": None if error is None else error.code,
            },
            failure=(
                None
                if error is None
                else self._failure(
                    error.code,
                    origin_stage="tool" if origin == "tool" else "retrieval",
                    observed_stage="tool",
                    handling="returned_to_agent",
                    cause_operation_id=tool_operation,
                )
            ),
        )
        return envelope

    @staticmethod
    def _request_payload(request: SearchMessagesInput) -> dict[str, object]:
        """只投影 typed request 字段，不把 trusted scope 混入 Tool payload。"""

        return {
            "keyword": request.keyword,
            "session_ids": request.session_ids,
            "start_timestamp": request.start_timestamp,
            "end_timestamp": request.end_timestamp,
            "sender_user_ids": request.sender_user_ids,
            "message_types": request.message_types,
            "limit": request.limit,
            "context_before": request.context_before,
            "context_after": request.context_after,
        }

    @staticmethod
    def _retrieval_payload(result: RetrievalResult) -> dict[str, object]:
        """保留策略、候选 identity/rank、coverage 与 context expansion operational facts。"""

        return {
            "strategy": result.strategy,
            "query": result.query.to_dict(),
            "filters": dict(result.filters),
            "candidate_count": len(result.hits),
            "candidate_ids": [hit.message.internal_message_id for hit in result.hits],
            "candidate_scores": [hit.score for hit in result.hits],
            "total_hits": result.total_hits,
            "returned_messages": result.returned_messages,
            "coverage": {
                "status": result.coverage.status,
                "basis": result.coverage.basis,
            },
            "partial": result.partial,
            "truncated": result.truncated,
            "context_expansion": {
                "expanded_count": len(result.expanded_messages),
                "details": dict(result.metadata.details),
            },
            "latency_ms": result.metadata.latency_ms,
        }

    @staticmethod
    def _failure(
        error_code: str,
        *,
        origin_stage: Literal["tool", "retrieval"],
        observed_stage: Literal["tool", "retrieval"],
        handling: str,
        diagnostic_reference: str | None = None,
        cause_operation_id: str | None = None,
    ) -> FailureInfo:
        """集中构造 Tool/Retrieval 失败归因，避免 wrapper 覆盖根因层。"""

        return FailureInfo(
            error_code=error_code,
            origin_stage=origin_stage,
            observed_stage=observed_stage,
            category="tool" if origin_stage == "tool" else "retrieval",
            handling=handling,
            diagnostic_reference=diagnostic_reference,
            cause_operation_id=cause_operation_id,
        )
