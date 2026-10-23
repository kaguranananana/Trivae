"""Conversation 管理与来源查看的 route 实现。

数据全部来自正式 Conversation Store / Application facade；
删除只影响 AI conversation 聚合，canonical chat 数据不可通过本接口触碰。
"""

from __future__ import annotations

from fastapi import HTTPException

from trivae.bootstrap.application import TrivaeApplication
from trivae.capabilities.contracts import ExecutionScope
from trivae.conversation.contracts import (
    ConversationError,
    ConversationNotFoundError,
    ConversationPersistenceError,
    ConversationScopeError,
    ConversationScopeSelector,
)
from trivae.query.evidence import (
    MessageSource,
    SourceInspectionError,
    answer_source_summaries,
)

from .contracts import ConversationCreateRequest, ConversationRenameRequest, WebScopeError
from .projection import project_context_messages, project_conversation, project_conversation_summary

MAX_CONVERSATION_CONTEXT_BEFORE = 5
MAX_CONVERSATION_CONTEXT_AFTER = 5


def _conversation_http_error(exc: Exception, status_code: int, error_code: str) -> HTTPException:
    """把 Conversation Store 的分类异常映射为稳定 API 错误信封。"""

    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": str(exc)})


def compile_conversation_list_selector(
    scope_mode: str | None,
    session_id: str | None,
) -> ConversationScopeSelector:
    """把 GET /api/conversations 的 bounded selector 编译为 domain selector。

    只接受 ``scope_mode``/``session_id``；start/end/max_results 等 ExecutionScope
    字段不属于 list selector，无法通过 query params 穿透。
    """

    if scope_mode == "all":
        if session_id is not None:
            raise WebScopeError("scope_mode 'all' does not accept session_id")
        return ConversationScopeSelector(allowed_session_ids=None)
    if scope_mode == "sessions":
        if session_id is None or not session_id.strip():
            raise WebScopeError("scope_mode 'sessions' requires a non-empty session_id")
        return ConversationScopeSelector(allowed_session_ids=(session_id,))
    raise WebScopeError("scope_mode must be 'all' or 'sessions'")


def list_conversations(
    application: TrivaeApplication,
    *,
    scope_mode: str | None,
    session_id: str | None,
    limit: int,
    query: str = "",
    offset: int = 0,
) -> list[dict[str, object]]:
    """当前 scope 的侧栏 conversation 列表（filter → order → limit）。"""

    try:
        selector = compile_conversation_list_selector(scope_mode, session_id)
    except WebScopeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "CONVERSATION_SCOPE_SELECTOR_INVALID", "message": str(exc)},
        ) from exc
    if selector.allowed_session_ids is not None:
        # selector 的 session 必须是 canonical catalog 中的真实 Source Session；
        # 历史遗留的未知 ID 不能通过列表接口伪装成合法导航范围。
        catalog_ids = {session.session_id for session in application.list_sessions()}
        requested = selector.allowed_session_ids
        missing = next((item for item in requested if item not in catalog_ids), None)
        if missing is not None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "SOURCE_SESSION_NOT_FOUND",
                    "message": f"source session does not exist: {missing}",
                },
            )
    try:
        summaries = application.list_conversations(limit, selector=selector, query=query, offset=offset)
    except ConversationPersistenceError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    return [project_conversation_summary(summary) for summary in summaries]


def create_conversation(application: TrivaeApplication, payload: ConversationCreateRequest) -> dict[str, object]:
    """New Chat：先创建带 trusted scope 的 conversation，再在其上发送 query。"""

    try:
        scope = payload.scope.to_scope()
        conversation = application.create_conversation(scope)
    except ConversationPersistenceError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error_code": "SCOPE_INVALID", "message": str(exc)}) from exc
    return project_conversation(conversation)


def read_conversation(application: TrivaeApplication, conversation_id: str) -> dict[str, object]:
    """Open/Resume conversation：完整历史 + sources + trace 引用。"""

    try:
        conversation = application.read_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise _conversation_http_error(exc, 404, "CONVERSATION_NOT_FOUND") from exc
    except ConversationPersistenceError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    return project_conversation(conversation)


def rename_conversation(
    application: TrivaeApplication,
    conversation_id: str,
    payload: ConversationRenameRequest,
) -> dict[str, object]:
    """Rename 只改 AI conversation title。"""

    try:
        conversation = application.rename_conversation(conversation_id, payload.title)
    except ConversationNotFoundError as exc:
        raise _conversation_http_error(exc, 404, "CONVERSATION_NOT_FOUND") from exc
    except ConversationPersistenceError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    return project_conversation(conversation)


def delete_conversation(application: TrivaeApplication, conversation_id: str) -> dict[str, object]:
    """Delete 只删除 AI conversation；绝不触碰 canonical chat messages。"""

    try:
        application.delete_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise _conversation_http_error(exc, 404, "CONVERSATION_NOT_FOUND") from exc
    except ConversationPersistenceError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    return {"status": "deleted", "conversation_id": conversation_id}


def inspect_source_context(
    application: TrivaeApplication,
    conversation_id: str,
    ordinal: int,
    source_index: int,
    *,
    before: int = 2,
    after: int = 2,
) -> dict[str, object]:
    """来源上下文 drill-down：在 conversation 的 trusted scope 内重读 canonical 消息。"""

    try:
        conversation = application.read_conversation(conversation_id)
    except ConversationNotFoundError as exc:
        raise _conversation_http_error(exc, 404, "CONVERSATION_NOT_FOUND") from exc
    if conversation.scope is None:
        raise _conversation_http_error(
            ConversationScopeError("conversation scope metadata is unavailable"),
            409,
            "CONVERSATION_SCOPE_MISSING",
        )
    message = next((item for item in conversation.messages if item.ordinal == ordinal), None)
    if message is None or message.answer_artifact is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "MESSAGE_NOT_FOUND", "message": "assistant message is unavailable"},
        )
    summary = next(
        (item for item in answer_source_summaries(message.answer_artifact) if item.index == source_index),
        None,
    )
    if summary is None or not isinstance(summary.reference, MessageSource):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SOURCE_NOT_INSPECTABLE",
                "message": "source is unavailable or does not reference a message",
            },
        )
    before_bounded = max(0, min(before, MAX_CONVERSATION_CONTEXT_BEFORE))
    after_bounded = max(0, min(after, MAX_CONVERSATION_CONTEXT_AFTER))
    scope: ExecutionScope = conversation.scope
    try:
        messages = application.inspect_message_source(summary.reference, scope, before=before_bounded, after=after_bounded)
    except SourceInspectionError as exc:
        raise _conversation_http_error(exc, 409, "SOURCE_INSPECTION_FAILED") from exc
    except ConversationError as exc:
        raise _conversation_http_error(exc, 500, "CONVERSATION_STORE_ERROR") from exc
    payload = project_context_messages(messages, target_internal_message_id=summary.reference.internal_message_id)
    return {"source_index": source_index, **payload}


__all__ = [
    "create_conversation",
    "delete_conversation",
    "inspect_source_context",
    "list_conversations",
    "read_conversation",
    "rename_conversation",
]
