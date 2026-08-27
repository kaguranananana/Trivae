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
)
from trivae.query.evidence import (
    MessageSource,
    SourceInspectionError,
    answer_source_summaries,
)

from .contracts import ConversationCreateRequest, ConversationRenameRequest
from .projection import project_context_messages, project_conversation, project_conversation_summary

MAX_CONVERSATION_CONTEXT_BEFORE = 5
MAX_CONVERSATION_CONTEXT_AFTER = 5


def _conversation_http_error(exc: Exception, status_code: int, error_code: str) -> HTTPException:
    """把 Conversation Store 的分类异常映射为稳定 API 错误信封。"""

    return HTTPException(status_code=status_code, detail={"error_code": error_code, "message": str(exc)})


def list_conversations(application: TrivaeApplication, limit: int) -> list[dict[str, object]]:
    """侧栏 conversation 列表（按 updated_at 倒序、bounded metadata）。"""

    try:
        summaries = application.list_conversations(limit)
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
