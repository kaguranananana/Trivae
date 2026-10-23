"""Local Web API 路由。

所有 endpoint 只通过 TrivaeApplication facade 工作；
frontend 不被允许直接访问 SQLite、Retrieval 或 provider。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from trivae.bootstrap.application import TrivaeApplication
from trivae.observability.contracts import TraceProjection
from trivae.observability.sqlite import TraceStoreError

from . import conversation as conversation_routes
from .contracts import (
    ConversationCreateRequest,
    ConversationRenameRequest,
    QueryStopRequest,
    QueryStreamRequest,
)
from .projection import project_readiness, project_sessions
from .streaming import QueryStopRegistry, stream_query
from .trace_actions import TraceRevealError, reveal_trace_in_finder, trace_log_path_payload

MAX_CONVERSATION_LIST_LIMIT = 100


def create_api_router(
    application: TrivaeApplication,
    *,
    registry: QueryStopRegistry,
    allow_reveal: bool,
) -> APIRouter:
    """构造 API 路由；reveal 类本地 OS 能力由 allow_reveal 显式开启。"""

    router = APIRouter(prefix="/api")

    @router.get("/readiness")
    async def readiness() -> dict[str, object]:
        return project_readiness(application.readiness())

    @router.get("/source-sessions")
    async def source_sessions() -> list[dict[str, object]]:
        return project_sessions(application.list_sessions())

    @router.get("/conversations")
    async def conversations(
        scope_mode: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        query: str = "",
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, object]]:
        # 列表只接受范围、文本搜索与分页；其他 query params 不被读取，
        # ExecutionScope 的时间/容量字段无法从列表接口穿透。
        bounded = max(1, min(limit, MAX_CONVERSATION_LIST_LIMIT))
        return conversation_routes.list_conversations(
            application,
            scope_mode=scope_mode,
            session_id=session_id,
            limit=bounded,
            query=query,
            offset=offset,
        )

    @router.post("/conversations", status_code=201)
    async def create_conversation(payload: ConversationCreateRequest) -> dict[str, object]:
        return conversation_routes.create_conversation(application, payload)

    @router.get("/conversations/{conversation_id}")
    async def read_conversation(conversation_id: str) -> dict[str, object]:
        return conversation_routes.read_conversation(application, conversation_id)

    @router.patch("/conversations/{conversation_id}")
    async def rename_conversation(conversation_id: str, payload: ConversationRenameRequest) -> dict[str, object]:
        return conversation_routes.rename_conversation(application, conversation_id, payload)

    @router.delete("/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str) -> dict[str, object]:
        return conversation_routes.delete_conversation(application, conversation_id)

    @router.get("/conversations/{conversation_id}/messages/{ordinal}/sources/{source_index}/context")
    async def source_context(
        conversation_id: str,
        ordinal: int,
        source_index: int,
        before: int = 2,
        after: int = 2,
    ) -> dict[str, object]:
        return conversation_routes.inspect_source_context(
            application,
            conversation_id,
            ordinal,
            source_index,
            before=before,
            after=after,
        )

    @router.post("/query/stream")
    async def query_stream(raw_request: Request, payload: QueryStreamRequest) -> object:
        return await stream_query(application, raw_request, payload, registry=registry)

    @router.post("/query/stop")
    async def query_stop(payload: QueryStopRequest) -> dict[str, object]:
        aborted = registry.abort(payload.request_id)
        if not aborted:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "QUERY_NOT_RUNNING", "message": "no running query for this request_id"},
            )
        return {"status": "abort_requested", "request_id": payload.request_id}

    @router.get("/traces/{trace_id}")
    async def read_trace(trace_id: str) -> TraceProjection:
        try:
            return application.read_trace(trace_id)
        except TraceStoreError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "TRACE_NOT_FOUND", "message": str(exc)},
            ) from exc

    @router.get("/traces/{trace_id}/path")
    async def trace_path(trace_id: str) -> dict[str, object]:
        try:
            return trace_log_path_payload(application, trace_id)
        except TraceRevealError as exc:
            return _reveal_error(exc)

    @router.post("/traces/{trace_id}/reveal")
    async def reveal_trace(trace_id: str) -> dict[str, object]:
        # Reveal in Finder 属于本机 OS 能力；remote/hosted 绑定必须禁用。
        if not allow_reveal:
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "REVEAL_LOCAL_ONLY",
                    "message": "reveal is only available when the server is bound to localhost",
                },
            )
        try:
            return reveal_trace_in_finder(application, trace_id)
        except TraceRevealError as exc:
            return _reveal_error(exc)

    def _reveal_error(exc: TraceRevealError) -> dict[str, object]:
        status_by_code = {
            "TRACE_NOT_FOUND": 404,
            "TRACE_FILE_NOT_FOUND": 404,
            "TRACE_ID_INVALID": 400,
            "TRACE_PATH_OUTSIDE_ALLOWED_DIRECTORY": 400,
            "REVEAL_UNSUPPORTED_PLATFORM": 501,
        }
        raise HTTPException(
            status_code=status_by_code.get(exc.error_code, 500),
            detail={"error_code": exc.error_code, "message": exc.message},
        )

    return router


__all__ = ["create_api_router"]
