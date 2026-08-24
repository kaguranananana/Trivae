"""Retrieval-facing Tool wrapper。"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Literal

from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecutionScope,
    FindMembersInput,
    GetMessageContextInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.semantic_search import SemanticSearchCapability
from trivae.observability.contracts import FailureInfo
from trivae.retrieval.context import MessageContextResult
from trivae.retrieval.identity import FindMembersResult
from trivae.retrieval.semantic.contracts import SemanticError, SemanticQueryError, SemanticRetrievalResult
from trivae.retrieval.structured import (
    InvalidRetrievalQuery,
    LexicalIndexError,
    RetrievalError,
    RetrievalResult,
)

RetrievalToolData = RetrievalResult | SemanticRetrievalResult


class SearchMessagesTool:
    """只负责 Tool envelope；SQL/FTS/context/order 全部留在 Retrieval Core。"""

    name = "search_messages"
    strategy = "lexical"

    def __init__(self, capability: Any) -> None:
        self.capability = capability

    def invoke(self, request: SearchMessagesInput | SemanticSearchInput, scope: ExecutionScope) -> ToolEnvelope:
        """把已分类的 contract/retrieval 错误投影为统一状态，未知异常继续暴露。"""

        envelope, _ = self._invoke_with_origin(request, scope)
        return envelope

    def _invoke_with_origin(
        self,
        request: SearchMessagesInput | SemanticSearchInput,
        scope: ExecutionScope,
    ) -> tuple[ToolEnvelope, Literal["tool", "retrieval"] | None]:
        """内部保留错误 owner，公开 invoke 仍只返回既有 ToolEnvelope。"""

        expected_type = SemanticSearchInput if self.strategy == "semantic" else SearchMessagesInput
        if not isinstance(request, expected_type):
            # 不让错误输入落到 Capability 属性访问的 AttributeError，保持 Tool contract 错误可诊断。
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="INVALID_ARGUMENT", message=f"{self.name} received an invalid request type"),
                ),
                "tool",
            )
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
        except SemanticQueryError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="INVALID_ARGUMENT", message=str(exc)),
                ),
                "retrieval",
            )
        except SemanticError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False, "origin_error_code": exc.error_code},
                    error=ToolError(code=exc.error_code, message=str(exc)),
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
        request: SearchMessagesInput | SemanticSearchInput,
        scope: ExecutionScope,
        trace_context: object,
    ) -> ToolEnvelope:
        """记录 Tool→Retrieval 因果，但不改变既有 envelope 和 exception 语义。"""

        # 延迟读取 collector 类型，避免 observability collector 与 capabilities package 初始化互相回环。
        from trivae.observability.collector import TraceOperationContext

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
            payload={"strategy": self.strategy, "query": self._request_payload(request)},
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
        if error is None and isinstance(envelope.data, (RetrievalResult, SemanticRetrievalResult)):
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
    def _request_payload(request: SearchMessagesInput | SemanticSearchInput) -> dict[str, object]:
        """只投影 typed request 字段，不把 trusted scope 混入 Tool payload。"""

        if isinstance(request, SearchMessagesInput):
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
        return {
            "query": request.query,
            "session_ids": request.session_ids,
            "start_timestamp": request.start_timestamp,
            "end_timestamp": request.end_timestamp,
            "sender_user_ids": request.sender_user_ids,
            "message_types": request.message_types,
            "source_message_id": request.source_message_id,
            "reply_to_source_message_id": request.reply_to_source_message_id,
            "limit": request.limit,
            "context_before": request.context_before,
            "context_after": request.context_after,
            "dense_top_k": request.dense_top_k,
        }

    @staticmethod
    def _retrieval_payload(result: RetrievalToolData) -> dict[str, object]:
        """保留策略、候选 identity/rank、coverage 与 context expansion operational facts。"""

        payload: dict[str, object] = {
            "strategy": result.strategy,
            "query": result.query.to_dict(),
            "filters": dict(result.filters),
            "candidate_count": len(result.hits),
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
        if isinstance(result, RetrievalResult):
            payload["candidate_ids"] = [hit.message.internal_message_id for hit in result.hits]
        else:
            payload["candidate_ids"] = [hit.chunk_id for hit in result.hits]
            payload["candidate_parent_ids"] = [hit.parent_id for hit in result.hits]
            payload["candidate_score_type"] = [hit.score_type for hit in result.hits]
            payload["index_identity"] = [hit.index_identity for hit in result.hits]
        return payload

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


class LexicalSearchTool(SearchMessagesTool):
    """canonical lexical_search 名称，共用既有 lexical Retrieval 链路。"""

    name = "lexical_search"


class SemanticSearchTool(SearchMessagesTool):
    """semantic_search 的 Tool envelope/Trace wrapper，不复制 Retrieval 逻辑。"""

    name = "semantic_search"
    strategy = "semantic"

    def __init__(self, capability: SemanticSearchCapability) -> None:
        super().__init__(capability)


class _StageBTool:
    """Stage B Tool 的共同 envelope/trace 边界，不复制 Context/Identity 业务逻辑。"""

    name: str
    trace_stage: Literal["context", "tool"]
    internal_operation_prefix: str

    def __init__(self, capability: Any, request_type: type[Any]) -> None:
        self.capability = capability
        self.request_type = request_type

    def invoke(
        self,
        request: SearchMessagesInput | SemanticSearchInput | GetMessageContextInput | FindMembersInput,
        scope: ExecutionScope,
    ) -> ToolEnvelope:
        """向旧 registry caller 暴露同一 ToolEnvelope 语义。"""

        envelope, _ = self._invoke_with_origin(request, scope)
        return envelope

    def _invoke_with_origin(
        self,
        request: SearchMessagesInput | SemanticSearchInput | GetMessageContextInput | FindMembersInput,
        scope: ExecutionScope,
    ) -> tuple[ToolEnvelope, Literal["tool", "capability"] | None]:
        """把已知 Stage B contract/retrieval 错误投影为显式 envelope。"""

        if not isinstance(request, self.request_type):
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="INVALID_ARGUMENT", message=f"{self.name} received an invalid request type"),
                ),
                "tool",
            )
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
                "capability",
            )
        except RetrievalError as exc:
            return (
                ToolEnvelope(
                    status="error",
                    data=None,
                    meta={"truncated": False},
                    error=ToolError(code="EXECUTION_ERROR", message=str(exc)),
                ),
                "capability",
            )

        return (
            ToolEnvelope(
                status="partial" if result.partial else "ok",
                data=result,
                meta=self._result_meta(result),
                error=None,
            ),
            None,
        )

    def invoke_with_trace(
        self,
        request: SearchMessagesInput | SemanticSearchInput | GetMessageContextInput | FindMembersInput,
        scope: ExecutionScope,
        trace_context: object,
    ) -> ToolEnvelope:
        """记录 Tool 与 Context/Identity capability 的公开因果链。"""

        from trivae.observability.collector import TraceOperationContext

        if not isinstance(trace_context, TraceOperationContext):
            raise TypeError(f"{self.name} requires TraceOperationContext")
        started = perf_counter()
        tool_operation = trace_context.operation_id
        internal_operation = f"{tool_operation}:{self.internal_operation_prefix}"
        trace_context.emit(
            stage="tool",
            operation="tool.call.started",
            phase="started",
            operation_id=tool_operation,
            parent_operation_id=trace_context.parent_operation_id,
            payload={"tool_name": self.name, "request": self._request_payload(request)},
        )
        trace_context.emit(
            stage=self.trace_stage,
            operation=f"{self.internal_operation_prefix}.started",
            phase="started",
            operation_id=internal_operation,
            parent_operation_id=tool_operation,
            payload={"tool_name": self.name, "request": self._request_payload(request)},
        )
        internal_started = perf_counter()
        try:
            envelope, origin = self._invoke_with_origin(request, scope)
        except Exception as exc:
            # 未知异常必须原样上抛；Trace 只记录安全的异常类型和失败归属。
            self._emit_internal_failure(trace_context, internal_operation, tool_operation, internal_started, type(exc).__name__)
            trace_context.emit(
                stage="tool",
                operation="tool.call.failed",
                phase="failed",
                operation_id=tool_operation,
                parent_operation_id=trace_context.parent_operation_id,
                outcome="error",
                duration_ms=(perf_counter() - started) * 1000,
                payload={"tool_name": self.name, "exception_type": type(exc).__name__},
                failure=self._failure("TOOL_EXCEPTION", "tool", "propagated", tool_operation, type(exc).__name__),
            )
            raise

        if envelope.error is None:
            trace_context.emit(
                stage=self.trace_stage,
                operation=f"{self.internal_operation_prefix}.completed",
                phase="completed",
                operation_id=internal_operation,
                parent_operation_id=tool_operation,
                outcome="partial" if envelope.status == "partial" else "ok",
                duration_ms=(perf_counter() - internal_started) * 1000,
                payload=self._result_payload(envelope.data),
            )
        else:
            if origin == "tool":
                trace_context.emit(
                    stage=self.trace_stage,
                    operation=f"{self.internal_operation_prefix}.skipped",
                    phase="skipped",
                    operation_id=internal_operation,
                    parent_operation_id=tool_operation,
                    outcome="error",
                    duration_ms=(perf_counter() - internal_started) * 1000,
                    payload={"error_code": envelope.error.code},
                    limitations=("tool_contract_error",),
                )
            else:
                trace_context.emit(
                    stage=self.trace_stage,
                    operation=f"{self.internal_operation_prefix}.failed",
                    phase="failed",
                    operation_id=internal_operation,
                    parent_operation_id=tool_operation,
                    outcome="error",
                    duration_ms=(perf_counter() - internal_started) * 1000,
                    payload={"error_code": envelope.error.code},
                    failure=self._failure(
                        envelope.error.code,
                        "context" if self.trace_stage == "context" else "tool",
                        "returned_to_agent",
                        internal_operation,
                        None,
                    ),
                )

        error = envelope.error
        trace_context.emit(
            stage="tool",
            operation="tool.call.failed" if error is not None else "tool.call.completed",
            phase="failed" if error is not None else "completed",
            operation_id=tool_operation,
            parent_operation_id=trace_context.parent_operation_id,
            outcome="error" if error is not None else ("partial" if envelope.status == "partial" else "ok"),
            duration_ms=(perf_counter() - started) * 1000,
            payload={
                "tool_name": self.name,
                "status": envelope.status,
                "error_code": None if error is None else error.code,
            },
            failure=None
            if error is None
            else self._failure(
                error.code,
                "context" if self.trace_stage == "context" else "tool",
                "returned_to_agent",
                tool_operation,
                None,
            ),
        )
        return envelope

    def _emit_internal_failure(
        self,
        trace_context: Any,
        operation_id: str,
        parent_operation_id: str,
        started: float,
        exception_type: str,
    ) -> None:
        """记录未知 capability 异常的公开失败类型，不吞掉原异常。"""

        trace_context.emit(
            stage=self.trace_stage,
            operation=f"{self.internal_operation_prefix}.failed",
            phase="failed",
            operation_id=operation_id,
            parent_operation_id=parent_operation_id,
            outcome="error",
            duration_ms=(perf_counter() - started) * 1000,
            payload={"exception_type": exception_type},
            failure=self._failure(
                "CAPABILITY_EXCEPTION",
                "context" if self.trace_stage == "context" else "tool",
                "propagated",
                operation_id,
                exception_type,
            ),
        )

    @staticmethod
    def _failure(
        error_code: str,
        origin_stage: Literal["context", "tool"],
        handling: str,
        operation_id: str,
        diagnostic_reference: str | None,
    ) -> FailureInfo:
        """集中构造 Stage B failure attribution。"""

        return FailureInfo(
            error_code=error_code,
            origin_stage=origin_stage,
            observed_stage="tool",
            category="context" if origin_stage == "context" else "identity",
            handling=handling,
            cause_operation_id=operation_id,
            diagnostic_reference=diagnostic_reference,
        )

    @staticmethod
    def _request_payload(request: object) -> dict[str, object]:
        """只投影模型提供的 Stage B 参数，不把 ExecutionScope 写入 Tool arguments。"""

        if isinstance(request, GetMessageContextInput):
            return {
                "message_id": request.message_id,
                "context_before": request.context_before,
                "context_after": request.context_after,
            }
        if isinstance(request, FindMembersInput):
            return {"query": request.query, "session_ids": request.session_ids, "limit": request.limit}
        return {}

    def _result_payload(self, result: object) -> dict[str, object]:
        """保留 context/member 的 bounded 结果摘要，避免 Trace 保存完整聊天正文。"""

        if isinstance(result, MessageContextResult):
            return {
                "tool_name": "get_message_context",
                "message_id": result.message_id,
                "session_id": result.session_id,
                "returned_messages": len(result.messages),
                "candidate_count": result.metadata.details.get("candidate_count"),
                "partial": result.partial,
                "truncated": result.truncated,
                "explicit_deepening": True,
                "automatic_search_context": False,
            }
        if isinstance(result, FindMembersResult):
            return {
                "tool_name": "find_members",
                "returned_candidates": len(result.candidates),
                "total_candidates": result.total_candidates,
                "ambiguous": len(result.candidates) > 1,
                "partial": result.partial,
                "truncated": result.truncated,
            }
        return {"tool_name": self.name}

    @staticmethod
    def _result_meta(result: MessageContextResult | FindMembersResult) -> dict[str, object]:
        """构造统一 envelope meta，保留 no-result 与 truncation 事实。"""

        if isinstance(result, MessageContextResult):
            return {
                "truncated": result.truncated,
                "returned_messages": len(result.messages),
                "message_id": result.message_id,
            }
        return {
            "truncated": result.truncated,
            "returned_candidates": len(result.candidates),
            "total_candidates": result.total_candidates,
        }


class GetMessageContextTool(_StageBTool):
    """Agent-facing get_message_context Tool。"""

    name = "get_message_context"
    trace_stage = "context"
    internal_operation_prefix = "context.expansion"

    def __init__(self, capability: Any) -> None:
        super().__init__(capability, GetMessageContextInput)


class FindMembersTool(_StageBTool):
    """Agent-facing find_members Tool；多候选正常返回，不做唯一 resolve。"""

    name = "find_members"
    trace_stage = "tool"
    internal_operation_prefix = "member.lookup"

    def __init__(self, capability: Any) -> None:
        super().__init__(capability, FindMembersInput)
