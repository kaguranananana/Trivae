"""get_message_context Capability：复用 canonical read 与 bounded Context Expansion。"""

from __future__ import annotations

from time import perf_counter

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    CapabilityScopeError,
    ExecutionScope,
    GetMessageContextInput,
)
from trivae.capabilities.scope import scope_filters
from trivae.retrieval.context import (
    MAX_CONTEXT_EXPANSION_MESSAGES,
    ContextExpander,
    ContextReadRepository,
    MessageContextResult,
)
from trivae.retrieval.structured import Coverage, MessageHit, RetrievalMetadata


class MessageContextNotFound(CapabilityContractError):
    """稳定 message locator 不存在时的显式 Tool contract 错误。"""

    error_code = "MESSAGE_NOT_FOUND"


class GetMessageContextCapability:
    """对已确认的 message 做显式、同 session、bounded context deepening。"""

    metadata = CapabilityMetadata(
        name="get_message_context",
        description=(
            "Recover a larger but bounded same-conversation context around a known message_id. "
            "Use only after lexical_search or semantic_search returned an important message whose "
            "local context is insufficient; do not call mechanically for every hit."
        ),
        bounded=True,
        # SDK adapter 可把当前 Tool Result 的 source_id 解析成同一个 canonical message_id。
        input_fields=("message_id", "source_id", "context_before", "context_after"),
    )

    def __init__(
        self,
        repository: ContextReadRepository,
        context_expander: ContextExpander | None = None,
    ) -> None:
        """接收 Application 已拥有的 read port，不在 Capability 内打开数据库连接。"""

        self.repository = repository
        self.context_expander = context_expander or ContextExpander(repository)

    def execute(self, request: GetMessageContextInput, scope: ExecutionScope) -> MessageContextResult:
        """先验证 anchor 属于 trusted scope，再复用统一 ContextExpander。"""

        if not isinstance(request, GetMessageContextInput):
            raise CapabilityContractError("get_message_context received an invalid request type")
        reader = getattr(self.repository, "read_message_by_id", None)
        if not callable(reader):
            raise RuntimeError("canonical read repository does not provide message lookup")

        started = perf_counter()
        anchor = reader(request.message_id)
        if anchor is None:
            raise MessageContextNotFound(f"message_id does not exist: {request.message_id}")
        if not _scope_allows_anchor(anchor, scope):
            raise CapabilityScopeError("message_id is outside trusted data access scope")

        # scope.max_results 同时约束显式 context 的可返回数量，transport bound 保护 ToolResultRecord。
        result_limit = min(scope.max_results, MAX_CONTEXT_EXPANSION_MESSAGES)
        expansion = self.context_expander.expand(
            hits=(MessageHit(anchor, (), 0.0, "context_anchor"),),
            before=request.context_before,
            after=request.context_after,
            limit=result_limit,
            scope=scope_filters(scope),
        )
        if any(message.session_id != anchor.session_id for message in expansion.messages):
            # repository 跨 conversation boundary 是主链路错误，不能把它投影成正常结果。
            raise RuntimeError("context expansion crossed conversation boundary")

        return MessageContextResult(
            strategy="context",
            message_id=anchor.internal_message_id,
            session_id=anchor.session_id,
            messages=expansion.messages,
            requested_before=request.context_before,
            requested_after=request.context_after,
            coverage=Coverage(status="complete", basis="canonical_store"),
            partial=expansion.partial,
            truncated=expansion.truncated,
            metadata=RetrievalMetadata(
                filters={
                    "message_id": request.message_id,
                    "context_before": request.context_before,
                    "context_after": request.context_after,
                    "scope": scope_filters(scope).scope_dict(),
                },
                ordering="timestamp ASC, present seq ASC, missing seq after present seq, internal_message_id ASC",
                latency_ms=(perf_counter() - started) * 1000,
                details={
                    "explicit_deepening": True,
                    "automatic_search_context": False,
                    "anchor_message_id": anchor.internal_message_id,
                    "candidate_count": expansion.candidate_count,
                    "result_limit": result_limit,
                    "conversation_boundary": anchor.session_id,
                },
            ),
        )


def _scope_allows_anchor(anchor: object, scope: ExecutionScope) -> bool:
    """在读取 context 前检查 anchor session/time，避免越权 locator 进入 expansion。"""

    session_id = getattr(anchor, "session_id", None)
    timestamp = getattr(anchor, "timestamp", None)
    if not isinstance(session_id, str) or not isinstance(timestamp, int):
        raise RuntimeError("canonical message anchor projection is invalid")
    if scope.allowed_session_ids is not None and session_id not in scope.allowed_session_ids:
        return False
    if scope.start_timestamp is not None and timestamp < scope.start_timestamp:
        return False
    if scope.end_timestamp is not None and timestamp >= scope.end_timestamp:
        return False
    return True
