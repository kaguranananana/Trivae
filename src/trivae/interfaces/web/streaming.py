"""QueryStreamEvent → NDJSON streaming 与优雅取消生命周期。

Web streaming 不建立第二套执行链：每个请求仍然只调用一次 ``application.query``。
事件按 ``request_id`` 归属，Stop 与浏览器断连都通过 graceful abort_event 取消，
终态保持 ``query.aborted`` 语义。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Mapping
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from trivae.bootstrap.application import TrivaeApplication
from trivae.capabilities.contracts import ExecutionScope
from trivae.conversation.contracts import ConversationNotFoundError
from trivae.query.contracts import QueryRequest, QueryResult
from trivae.query.evidence import answer_source_summaries
from trivae.query.streaming import QueryStreamEvent

from .contracts import QueryStreamRequest, WebScopeError
from .projection import project_answer_blocks, project_source_summary

NDJSON_MEDIA_TYPE = "application/x-ndjson"
_DISCONNECT_POLL_SECONDS = 0.2
WEB_THINKING_VISIBILITY_POLICY = frozenset({"public_summary", "provider_reasoning"})


class QueryStopRegistry:
    """request_id → abort_event 的进程内注册表；本地单进程 Web 使用。"""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def register(self, request_id: str, abort_event: asyncio.Event) -> None:
        self._events[request_id] = abort_event

    def unregister(self, request_id: str) -> None:
        self._events.pop(request_id, None)

    def abort(self, request_id: str) -> bool:
        """触发优雅取消；未知 request_id 返回 False。"""

        event = self._events.get(request_id)
        if event is None:
            return False
        event.set()
        return True


def _ndjson(payload: Mapping[str, Any]) -> bytes:
    """一行 JSON；事件含中文正文，必须 ensure_ascii=False。"""

    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def encode_stream_event(event: QueryStreamEvent) -> bytes:
    """把 UI-neutral QueryStreamEvent 编码为 NDJSON 行。"""

    payload: dict[str, Any] = {"type": event.type, "sequence": event.sequence}
    for name in (
        "trace_id",
        "content",
        "thinking_visibility",
        "route",
        "plan",
        "tool_name",
        "tool_call_id",
        "arguments",
        "result_summary",
        "result_detail",
        "result_projection",
        "provisional",
        "error_code",
        "error_message",
        "duration_ms",
        "usage",
        "source_operation",
        "source_sequence",
        "parent_operation_id",
        "metadata",
    ):
        value = getattr(event, name)
        if value is not None:
            payload[name] = value
    return _ndjson(payload)


def _validate_request(application: TrivaeApplication, payload: QueryStreamRequest) -> ExecutionScope:
    """编译 scope 并预检 conversation 契约，把错误留在 streaming 开始之前。"""

    try:
        scope = payload.scope.to_scope()
    except WebScopeError as exc:
        raise HTTPException(status_code=422, detail={"error_code": "SCOPE_INVALID", "message": str(exc)}) from exc

    if payload.conversation_id is None:
        return scope
    try:
        conversation = application.read_conversation(payload.conversation_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "CONVERSATION_NOT_FOUND", "message": str(exc)},
        ) from exc
    # follow-up 的 scope 必须与 conversation 契约一致；这是 Application 校验之外的早期反馈。
    if conversation.scope is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "CONVERSATION_SCOPE_MISSING",
                "message": "conversation scope metadata is unavailable",
            },
        )
    if conversation.scope != scope:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SCOPE_MISMATCH",
                "message": "request scope does not match the conversation scope",
            },
        )
    return scope


async def stream_query(
    application: TrivaeApplication,
    http_request: Request,
    payload: QueryStreamRequest,
    *,
    registry: QueryStopRegistry,
) -> StreamingResponse:
    """校验契约后启动 NDJSON streaming 响应。"""

    scope = _validate_request(application, payload)
    request_id = payload.request_id or f"web-request-{uuid4().hex}"
    return StreamingResponse(
        _event_generator(application, http_request, payload, scope, request_id, registry),
        media_type=NDJSON_MEDIA_TYPE,
        headers={"X-Request-Id": request_id, "Cache-Control": "no-store"},
    )


async def _event_generator(
    application: TrivaeApplication,
    http_request: Request,
    payload: QueryStreamRequest,
    scope: ExecutionScope,
    request_id: str,
    registry: QueryStopRegistry,
) -> AsyncIterator[bytes]:
    """单一 query task + 事件队列 + 断连轮询的最小 streaming loop。"""

    queue: asyncio.Queue[QueryStreamEvent] = asyncio.Queue()

    def on_event(event: QueryStreamEvent) -> None:
        queue.put_nowait(event)

    abort_event = asyncio.Event()
    registry.register(request_id, abort_event)
    conversation_id = payload.conversation_id
    yield _ndjson({
        "type": "stream.started",
        "request_id": request_id,
        "conversation_id": conversation_id,
    })

    async def run_query() -> QueryResult:
        return await application.query(
            QueryRequest(
                query=payload.query,
                scope=scope,
                conversation_id=payload.conversation_id,
                request_id=None,
            ),
            on_event=on_event,
            abort_event=abort_event,
            thinking_visibility_policy=WEB_THINKING_VISIBILITY_POLICY,
            provisional_answer_streaming=True,
        )

    task = asyncio.create_task(run_query())
    try:
        while True:
            if task.done():
                while not queue.empty():
                    yield encode_stream_event(queue.get_nowait())
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_DISCONNECT_POLL_SECONDS)
                yield encode_stream_event(event)
            except asyncio.TimeoutError:
                # Browser disconnect（关闭页面 / AbortController）必须真正取消 backend query。
                if await http_request.is_disconnected():
                    abort_event.set()
        for chunk in await _finish_stream(task, request_id, conversation_id):
            yield chunk
    except asyncio.CancelledError:
        # streaming response 自身被取消（客户端断开）时仍要取消 query task。
        abort_event.set()
        task.cancel()
        raise
    finally:
        registry.unregister(request_id)
        if not task.done():
            task.cancel()


async def _finish_stream(
    task: asyncio.Task[QueryResult],
    request_id: str,
    conversation_id: str | None,
) -> list[bytes]:
    """等待 query task 结束并产出确定性 stream.end 终态信封。"""

    result: QueryResult | None = None
    failure: BaseException | None = None
    try:
        result = await task
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 已取消连接的异常不能撕断 NDJSON 终态，转成显式 error 信封
        failure = exc

    status = "error"
    error_code: str | None = None
    error_message: str | None = None
    if failure is not None:
        error_code = type(failure).__name__
        error_message = f"{type(failure).__name__}: {failure}"
    elif result is not None:
        status = {
            "completed": "completed",
            "completed_degraded": "completed",
            "failed": "failed",
            "aborted": "aborted",
        }[result.execution_status]
        conversation_id = result.conversation_id or conversation_id
        if result.finalization_error is not None:
            error_code = result.finalization_error.code
            error_message = result.finalization_error.message
        elif result.runtime_result.error is not None:
            error_code = result.runtime_result.error.code
            error_message = result.runtime_result.error.message

    end: dict[str, Any] = {
        "type": "stream.end",
        "request_id": request_id,
        "status": status,
        "conversation_id": conversation_id,
    }
    if result is not None:
        end["trace_id"] = result.trace_id
        if result.answer_artifact is not None:
            # Sources 来自 validated artifact，不从模型文本猜测。
            end["sources"] = [
                project_source_summary(summary) for summary in answer_source_summaries(result.answer_artifact)
            ]
            end["limitations"] = list(result.answer_artifact.limitations)
            end["answer_blocks"] = project_answer_blocks(result.answer_artifact)
    if error_code is not None:
        end["error_code"] = error_code
    if error_message is not None:
        end["error_message"] = error_message
    return [_ndjson(end)]


__all__ = [
    "NDJSON_MEDIA_TYPE",
    "QueryStopRegistry",
    "encode_stream_event",
    "stream_query",
]
