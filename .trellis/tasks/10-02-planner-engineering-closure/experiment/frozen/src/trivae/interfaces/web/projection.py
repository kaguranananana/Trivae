"""Application facade 结果到 Web JSON 的 bounded projection。

只输出普通值；不把 canonical 大 payload、secret 或 raw SDK object 带进浏览器。
"""

from __future__ import annotations

from typing import Any, Mapping

from trivae.bootstrap.status import ApplicationReadiness
from trivae.capabilities.contracts import ExecutionScope
from trivae.conversation.contracts import Conversation, ConversationMessage, ConversationSummary
from trivae.data.model import ChatSession
from trivae.query.evidence import (
    AnswerSourceSummary,
    MessageDisplaySnapshot,
    MessageSource,
    StructuredSource,
    answer_source_summaries,
)
from trivae.retrieval.structured import MessageProjection

MAX_SOURCE_CONTEXT_MESSAGES = 10


def project_readiness(readiness: ApplicationReadiness) -> dict[str, object]:
    """readiness 已是 secret-safe projection；直接复用其 to_dict。"""

    return readiness.to_dict()


def project_sessions(sessions: tuple[ChatSession, ...]) -> list[dict[str, object]]:
    """Source Session 列表（scope picker 数据源）；与 AI Conversation 是不同概念。"""

    return [
        {
            "session_id": session.session_id,
            "platform": session.platform,
            "name": session.name,
            "chat_type": session.chat_type,
        }
        for session in sessions
    ]


def project_scope(scope: ExecutionScope | None) -> dict[str, object] | None:
    """把 trusted scope 快照回给前端，保证 follow-up 能原样回传。"""

    if scope is None:
        return None
    return {
        "mode": "all" if scope.allowed_session_ids is None else "sessions",
        "session_ids": None if scope.allowed_session_ids is None else list(scope.allowed_session_ids),
        "start_timestamp": scope.start_timestamp,
        "end_timestamp": scope.end_timestamp,
        "max_results": scope.max_results,
    }


def project_conversation_summary(summary: ConversationSummary) -> dict[str, object]:
    """Conversation 侧栏条目；preview/title 由 Conversation Store 提供。"""

    return {
        "conversation_id": summary.conversation_id,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "title": summary.title,
        "message_count": summary.message_count,
        "preview": summary.preview,
        "scope": project_scope(summary.scope),
    }


def project_source_snapshot(snapshot: MessageDisplaySnapshot) -> dict[str, object]:
    """message citation 的可信展示快照。"""

    return {
        "session_display": snapshot.session_display,
        "author_display": snapshot.author_display,
        "timestamp_ms": snapshot.timestamp_ms,
        "timezone": snapshot.timezone,
        "excerpt": snapshot.excerpt,
        "excerpt_truncated": snapshot.excerpt_truncated,
        "source_message_id": snapshot.source_message_id,
        "urls": list(snapshot.urls),
    }


def project_source_summary(summary: AnswerSourceSummary) -> dict[str, object]:
    """一个去重后的 answer source；locator 细节按 source 类型投影。"""

    reference = summary.reference
    base: dict[str, object] = {
        "index": summary.index,
        "evidence_ids": list(summary.evidence_ids),
        "relations": list(summary.relations),
    }
    if isinstance(reference, MessageSource):
        base["kind"] = "message"
        base["session_id"] = reference.session_id
        base["internal_message_id"] = reference.internal_message_id
        if reference.snapshot is not None:
            base["snapshot"] = project_source_snapshot(reference.snapshot)
        return base
    if isinstance(reference, StructuredSource):
        base["kind"] = "structured"
        base["locator_kind"] = reference.locator_kind
        base["locator"] = reference.locator
        base["value"] = _json_safe(reference.value_snapshot)
        if reference.execution_limitations:
            base["limitations"] = list(reference.execution_limitations)
        return base
    # SourceHandleReference 是未完成 finalization 的残余引用；显式表达 unavailable。
    base["kind"] = "unavailable"
    base["source_id"] = reference.source_id
    return base


def project_message(message: ConversationMessage) -> dict[str, object]:
    """一条 conversation message 的完整 UI projection（含 sources/trace/过程摘要）。"""

    payload: dict[str, object] = {
        "message_id": message.message_id,
        "ordinal": message.ordinal,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "trace_id": message.trace_id,
        "process_projection": _json_safe(message.process_projection),
    }
    if message.answer_artifact is not None:
        payload["sources"] = [
            project_source_summary(summary)
            for summary in answer_source_summaries(message.answer_artifact)
        ]
        payload["limitations"] = list(message.answer_artifact.limitations)
    return payload


def project_conversation(conversation: Conversation) -> dict[str, object]:
    """Open/Resume conversation 的完整响应。"""

    return {
        "conversation_id": conversation.conversation_id,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "scope": project_scope(conversation.scope),
        "messages": [project_message(message) for message in conversation.messages],
    }


def project_context_messages(
    messages: tuple[MessageProjection, ...],
    *,
    target_internal_message_id: str,
) -> dict[str, object]:
    """来源上下文 drill-down；目标消息与邻居都来自 canonical read。"""

    return {
        "messages": [
            {
                "internal_message_id": message.internal_message_id,
                "session_id": message.session_id,
                "session_display": message.session_display,
                "sender": message.sender_name or message.sender_user_id or message.sender_platform_id,
                "timestamp": message.timestamp,
                "content": message.normalized_content,
                "is_target": message.internal_message_id == target_internal_message_id,
            }
            for message in messages[:MAX_SOURCE_CONTEXT_MESSAGES]
        ]
    }


def _json_safe(value: Any) -> Any:
    """递归把普通值转成 JSON-safe 值；tuple → list。"""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)
