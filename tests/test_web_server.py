"""Local Web API 测试：NDJSON streaming、取消、scope 契约、conversation 管理与 trace reveal 安全边界。

使用 httpx ASGITransport 在同一事件循环内驱动 app，与 SQLite 同线程约束一致。
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.interfaces.web.server import create_web_app
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeEvent, RuntimeResult


def _runtime_event(event_type: str, **kwargs: object) -> RuntimeEvent:
    values: dict[str, object] = {"provider": "test", "model": "test-model", "sequence": 1}
    values.update(kwargs)
    return RuntimeEvent(type=event_type, **values)  # type: ignore[arg-type]


def _completed_result() -> RuntimeResult:
    return RuntimeResult(
        final_answer="ok",
        provider="test",
        model="test-model",
        termination="completed",
        tool_calls=(),
        run_id="run-1",
    )


class _ScriptedRuntime:
    """流式 fake runtime：持续发 token delta，abort 置位后返回 aborted 终态。"""

    def stream(self, request: AgentRunRequest, abort_event: object | None = None) -> Any:
        async def _iterator() -> AsyncIterator[RuntimeEvent]:
            yield _runtime_event("run_started")
            for index in range(200):
                if abort_event is not None and getattr(abort_event, "is_set", lambda: False)():
                    yield _runtime_event("aborted", result=self._aborted())
                    return
                yield _runtime_event("content_delta", text=f"片段{index}\n")
                await asyncio.sleep(0.01)
            yield _runtime_event("completed", result=_completed_result())

        return _iterator()

    def _aborted(self) -> RuntimeResult:
        return RuntimeResult(
            final_answer=None,
            provider="test",
            model="test-model",
            termination="aborted",
            tool_calls=(),
        )

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        return _completed_result()


class _CompletedRuntime:
    """流式 completed runtime：plain-text 答案走真实 Finalizer。"""

    def stream(self, request: AgentRunRequest, abort_event: object | None = None) -> Any:
        async def _iterator() -> AsyncIterator[RuntimeEvent]:
            yield _runtime_event("run_started")
            yield _runtime_event("content_delta", text="ok")
            yield _runtime_event("completed", result=_completed_result())

        return _iterator()

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        return _completed_result()


class _FailingRuntime:
    """在 stream 中途抛出真实异常，验证 error 终态信封。"""

    def stream(self, request: AgentRunRequest, abort_event: object | None = None) -> Any:
        async def _iterator() -> AsyncIterator[RuntimeEvent]:
            yield _runtime_event("run_started")
            raise RuntimeError("provider exploded")
            yield _runtime_event("completed", result=_completed_result())  # pragma: no cover

        return _iterator()

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        raise RuntimeError("provider exploded")


def _ndjson_lines(raw: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]


def _scope_all() -> Any:
    from trivae.capabilities.contracts import ExecutionScope

    return ExecutionScope(allowed_session_ids=None, max_results=5)


def _scope_session(session_id: str) -> Any:
    from trivae.capabilities.contracts import ExecutionScope

    return ExecutionScope(allowed_session_ids=(session_id,), max_results=5)


class WebApiTests(unittest.TestCase):
    """覆盖 API contract 的核心行为。"""

    def _run(self, coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    def _app(self, database: Path, runtime: object) -> TrivaeApplication:
        return create_application(database, agent_runtime=runtime)

    # ---------- static endpoints ----------

    def test_readiness_and_source_sessions(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        readiness = (await client.get("/api/readiness")).json()
                        self.assertEqual(readiness["database"]["status"], "ready")
                        sessions = (await client.get("/api/source-sessions")).json()
                        self.assertEqual(sessions, [])
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_conversation_lifecycle(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        created = (await client.post("/api/conversations", json={"scope": {"mode": "all"}})).json()
                        conversation_id = created["conversation_id"]
                        self.assertEqual(created["scope"]["mode"], "all")

                        renamed = (
                            await client.patch(
                                f"/api/conversations/{conversation_id}",
                                json={"title": "自定义名"},
                            )
                        ).json()
                        self.assertEqual(renamed["scope"]["mode"], "all")

                        listing = (await client.get("/api/conversations?scope_mode=all")).json()
                        self.assertEqual(listing[0]["title"], "自定义名")

                        deleted = (await client.delete(f"/api/conversations/{conversation_id}")).json()
                        self.assertEqual(deleted["status"], "deleted")
                        missing = await client.get(f"/api/conversations/{conversation_id}")
                        self.assertEqual(missing.status_code, 404)
                        self.assertEqual(missing.json()["detail"]["error_code"], "CONVERSATION_NOT_FOUND")
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_invalid_scope_is_rejected(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await client.post(
                            "/api/conversations",
                            json={"scope": {"mode": "sessions", "session_ids": []}},
                        )
                        self.assertEqual(response.status_code, 422)
                finally:
                    await application.aclose()

        self._run(scenario())

    # ---------- streaming ----------

    async def _stream(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async with client.stream("POST", "/api/query/stream", json=payload) as response:
            response.raise_for_status()
            request_id = response.headers["X-Request-Id"]
            async for line in response.aiter_lines():
                if line.strip():
                    events.append(json.loads(line))
        for event in events:
            event.setdefault("request_id", request_id)
        return events

    def test_stream_query_completes_with_sources_and_end(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        events = await self._stream(client, {"query": "最近大家聊了什么", "scope": {"mode": "all"}})
                        types = [event["type"] for event in events]
                        self.assertEqual(types[0], "stream.started")
                        self.assertIn("query.started", types)
                        self.assertIn("answer.delta", types)
                        end = events[-1]
                        self.assertEqual(end["type"], "stream.end")
                        self.assertEqual(end["status"], "completed")
                        self.assertTrue(str(end["conversation_id"]))
                        self.assertTrue(str(end["trace_id"]).startswith("trace-"))
                        # 测试 runtime 不产生 tool/evidence，sources 为空列表而不是伪造。
                        self.assertEqual(end.get("sources"), [])
                        # conversation 已在 backend 持久化一问一答。
                        listing = (await client.get("/api/conversations?scope_mode=all")).json()
                        self.assertEqual(listing[0]["message_count"], 2)
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_stream_follow_up_reuses_conversation_and_rejects_scope_change(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        events = await self._stream(client, {"query": "第一问", "scope": {"mode": "all"}})
                        conversation_id = events[-1]["conversation_id"]
                        follow_up = await self._stream(
                            client,
                            {"query": "第二问", "scope": {"mode": "all"}, "conversation_id": conversation_id},
                        )
                        self.assertEqual(follow_up[-1]["conversation_id"], conversation_id)

                        mismatch = await client.post(
                            "/api/query/stream",
                            json={
                                "query": "第三问",
                                "scope": {"mode": "sessions", "session_ids": ["qq:other"]},
                                "conversation_id": conversation_id,
                            },
                        )
                        self.assertEqual(mismatch.status_code, 409)
                        self.assertEqual(mismatch.json()["detail"]["error_code"], "SCOPE_MISMATCH")
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_stream_stop_cancels_backend_query(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                runtime = _ScriptedRuntime()
                application = self._app(Path(directory) / "stop.sqlite3", runtime)
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        request_id = "web-request-stop-test"
                        stream_task = asyncio.create_task(
                            self._stream(
                                client,
                                {"query": "长问题", "scope": {"mode": "all"}, "request_id": request_id},
                            )
                        )
                        # 等待 stream.started 出现后再 Stop。
                        await asyncio.sleep(0.05)
                        stop = await client.post("/api/query/stop", json={"request_id": request_id})
                        self.assertEqual(stop.status_code, 200)
                        events = await stream_task
                    end = events[-1]
                    self.assertEqual(end["type"], "stream.end")
                    self.assertEqual(end["status"], "aborted")
                    # Stop 之后 backend registry 释放，重复 stop 404。
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        again = await client.post("/api/query/stop", json={"request_id": request_id})
                        self.assertEqual(again.status_code, 404)
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_stream_error_envelope_when_runtime_fails(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "fail.sqlite3", _FailingRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        events = await self._stream(client, {"query": "问题", "scope": {"mode": "all"}})
                    end = events[-1]
                    self.assertEqual(end["status"], "error")
                    self.assertIn("RuntimeError", end["error_message"])
                finally:
                    await application.aclose()

        self._run(scenario())

    # ---------- trace reveal ----------

    def test_reveal_rejects_unknown_trace(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await client.post("/api/traces/trace-does-not-exist/reveal")
                        self.assertEqual(response.status_code, 404)
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_reveal_is_forbidden_on_remote_bind(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "remote.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="0.0.0.0")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await client.post("/api/traces/trace-x/reveal")
                        self.assertEqual(response.status_code, 403)
                        self.assertEqual(response.json()["detail"]["error_code"], "REVEAL_LOCAL_ONLY")
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_reveal_invokes_open_dash_r_with_array_args(self) -> None:
        from trivae.interfaces.web import trace_actions

        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app(Path(directory) / "web.sqlite3", _CompletedRuntime())
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        events = await self._stream(client, {"query": "产生 trace", "scope": {"mode": "all"}})
                        trace_id = events[-1]["trace_id"]
                        detail = (await client.get(f"/api/conversations/{events[-1]['conversation_id']}")).json()
                        assistant_trace = next(
                            message["trace_id"] for message in detail["messages"] if message["role"] == "assistant"
                        )
                        self.assertEqual(assistant_trace, trace_id)

                        calls: list[list[str]] = []

                        def fake_run(cmd: list[str], **kwargs: object) -> object:
                            calls.append(cmd)

                            class _Completed:
                                returncode = 0

                            return _Completed()

                        original_run = trace_actions.subprocess.run
                        try:
                            trace_actions.subprocess.run = fake_run
                            result = await client.post(f"/api/traces/{trace_id}/reveal")
                            self.assertEqual(result.status_code, 200)
                            self.assertEqual(result.json()["status"], "revealed")
                        finally:
                            trace_actions.subprocess.run = original_run
                        # 参数数组调用 open -R，不是 shell string；trace_id 无法注入路径。
                        self.assertEqual(calls[0][0], "open")
                        self.assertEqual(calls[0][1], "-R")
                        self.assertTrue(calls[0][2].endswith(f"{trace_id}.log"))
                finally:
                    await application.aclose()

        self._run(scenario())


class ConversationListSelectorApiTests(unittest.TestCase):
    """GET /api/conversations 的 bounded selector contract：filter-before-limit + 稳定错误信封。"""

    def _run(self, coroutine: Any) -> Any:
        return asyncio.run(coroutine)

    def _app_with_sessions_and_conversations(self, database: Path) -> TrivaeApplication:
        """canonical catalog 提供真实 session qq:100；conversation 混合三种 scope。"""

        application = create_application(database)
        raw_directory = database.parent / "raw"
        raw_directory.mkdir(parents=True, exist_ok=True)
        write_export(
            raw_directory,
            "web-selector(100).json",
            [make_message("m1", 1, 1_768_435_200_000, "selector fixture")],
            chat_name="Web Selector",
            peer_uid=None,
            version="5.5.64",
        )
        application.import_directory(raw_directory)
        application.create_conversation(_scope_all())
        application.create_conversation(_scope_session("qq:100"))
        application.create_conversation(_scope_session("qq:100"))
        return application

    def _list(self, client: httpx.AsyncClient, query: str) -> httpx.Response:
        return client.get(f"/api/conversations{query}")

    def test_missing_scope_mode_returns_stable_selector_error(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await self._list(client, "")
                        self.assertEqual(response.status_code, 422)
                        self.assertEqual(
                            response.json()["detail"]["error_code"],
                            "CONVERSATION_SCOPE_SELECTOR_INVALID",
                        )
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_all_mode_returns_only_all_scope_conversations(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await self._list(client, "?scope_mode=all&limit=100")
                        self.assertEqual(response.status_code, 200)
                        listing = response.json()
                        self.assertEqual(len(listing), 1)
                        self.assertEqual(listing[0]["scope"]["mode"], "all")
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_single_session_mode_returns_exact_identity(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await self._list(client, "?scope_mode=sessions&session_id=qq:100&limit=100")
                        self.assertEqual(response.status_code, 200)
                        listing = response.json()
                        self.assertEqual(len(listing), 2)
                        for item in listing:
                            self.assertEqual(item["scope"]["mode"], "sessions")
                            self.assertEqual(item["scope"]["session_ids"], ["qq:100"])
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_invalid_selector_combinations_return_stable_error(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        for query in (
                            "?scope_mode=all&session_id=qq:100",
                            "?scope_mode=sessions",
                            "?scope_mode=sessions&session_id=%20%20",
                            "?scope_mode=everything",
                        ):
                            response = await self._list(client, query)
                            self.assertEqual(response.status_code, 422, query)
                            self.assertEqual(
                                response.json()["detail"]["error_code"],
                                "CONVERSATION_SCOPE_SELECTOR_INVALID",
                                query,
                            )
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_unknown_session_returns_stable_error(self) -> None:
        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        response = await self._list(client, "?scope_mode=sessions&session_id=qq:missing")
                        self.assertEqual(response.status_code, 404)
                        self.assertEqual(
                            response.json()["detail"]["error_code"],
                            "SOURCE_SESSION_NOT_FOUND",
                        )
                finally:
                    await application.aclose()

        self._run(scenario())

    def test_execution_scope_query_fields_cannot_penetrate(self) -> None:
        """start/end/max_results 不是 list selector 字段：不被读取，也不改变结果。"""

        async def scenario() -> None:
            with tempfile.TemporaryDirectory() as directory:
                application = self._app_with_sessions_and_conversations(Path(directory) / "web.sqlite3")
                try:
                    app = create_web_app(application, host="127.0.0.1")
                    transport = httpx.ASGITransport(app=app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                        plain = (await self._list(client, "?scope_mode=all&limit=100")).json()
                        penetrated = (
                            await self._list(
                                client,
                                "?scope_mode=all&limit=100&start_timestamp=1&end_timestamp=2&max_results=1",
                            )
                        ).json()
                        self.assertEqual(plain, penetrated)
                        self.assertEqual(len(penetrated), 1)
                finally:
                    await application.aclose()

        self._run(scenario())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
