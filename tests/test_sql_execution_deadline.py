"""真实SQLite计算超过执行期限时须返回显式错误，不能由max_rows冒充计算上限。"""

from __future__ import annotations

import asyncio
import json
import threading
from time import perf_counter

import httpx
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.tool_context import ToolContext

from tests.test_ingestion import make_message, write_export
from tests.test_tool_result_budget import _dynamic_settings
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecuteSQLInput, ExecutionScope
from trivae.data.storage import sqlite_read
from trivae.interfaces.web.server import create_web_app
from trivae.observability.collector import TraceCollector
from trivae.observability.projection import project_trace
from trivae.query.router import RuleRouter
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.openai_tools import ExecuteSQLSDKToolAdapter


def test_expired_sql_is_interrupted_and_next_query_still_works(tmp_path, monkeypatch):
    """模拟时间越过期限，走VM中断和真实Tool错误映射；随后普通查询不受影响。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_export(raw, "deadline(100).json", [
        make_message(f"m{i}", i, 1_700_000_000_000 + i, "SQL执行期限") for i in range(1000)
    ], chat_name="SQL期限", peer_uid=None, version="5.5.64")
    with create_application(tmp_path / "messages.sqlite3") as application:
        application.import_directory(raw)
        ticks = iter((0.0, 10.0))
        # 仅替换SQL adapter本地时钟，使VM回调第一次检查时就超过5秒，测试无需真等5秒。
        monkeypatch.setattr(sqlite_read, "perf_counter", lambda: next(ticks, 10.0))
        envelope = application.invoke_tool("execute_sql", ExecuteSQLInput(
            sql="SELECT COUNT(*) AS n FROM messages a CROSS JOIN messages b", max_rows=1,
        ), ExecutionScope())
        assert envelope.status == "error", "expired SQL computation completed without a deadline error"
        assert envelope.error.code == "SQL_EXECUTION_TIMEOUT"
        assert envelope.data is None
        # 恢复正常时间后，新连接可继续提供真实统计，超时不能污染后续请求。
        monkeypatch.setattr(sqlite_read, "perf_counter", perf_counter)
        following = application.invoke_tool("execute_sql", ExecuteSQLInput(
            sql="SELECT COUNT(*) AS n FROM messages", max_rows=1,
        ), ExecutionScope())
        assert following.status == "ok"
        assert following.data.rows == ({"n": 1000},)


def test_sdk_sql_yields_event_loop_and_keeps_trace_on_owner_thread(tmp_path, monkeypatch):
    """同一 SDK 慢 SQL 期间其他回调须能执行，真实 SQLite Trace 仍可写入并保留超时。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_export(raw, "responsive(100).json", [
        make_message(f"m{i}", i, 1_700_000_000_000 + i, "SQL响应性") for i in range(1000)
    ], chat_name="SQL响应性", peer_uid=None, version="5.5.64")
    # 只缩短同一 VM 期限让回归快速结束；仍运行真实四表交叉计算，不用 sleep 冒充 SQL。
    monkeypatch.setattr(sqlite_read, "SQL_QUERY_TIMEOUT_SECONDS", 0.25)
    with create_application(tmp_path / "messages.sqlite3") as application:
        application.import_directory(raw)
        collector = TraceCollector(application._trace_store, trace_id="sql-responsive", request_id="sql-responsive")

        async def exercise():
            runtime = RuntimeContext(
                scope=ExecutionScope(), capability_registry=application.capability_registry,
                available_capabilities=("execute_sql",), run_id="sql-responsive",
                trace_context=collector.operation_context("query"),
            )
            runtime.allocate_tool_call_id("sql-responsive")
            arguments = json.dumps({"sql": "SELECT COUNT(*) AS n FROM messages a CROSS JOIN messages b "
                                    "CROSS JOIN messages c CROSS JOIN messages d", "max_rows": 1})
            wrapper = ToolContext(context=runtime, tool_name="execute_sql", tool_call_id="sql-responsive",
                                  tool_arguments=arguments)
            tool = ExecuteSQLSDKToolAdapter(application.capability_registry).as_sdk_tool()
            finished = False
            seen = []
            # 断言回调发生时 SQL 仍在运行，避免依赖机器快慢的绝对毫秒阈值。
            asyncio.get_running_loop().call_later(0.01, lambda: seen.append(finished))
            envelope = await tool.on_invoke_tool(wrapper, arguments)
            finished = True
            await asyncio.sleep(0.02)
            assert seen == [False], "SQL blocked the event loop until the query finished"
            assert envelope["error"]["code"] == "SQL_EXECUTION_TIMEOUT"

        asyncio.run(exercise())
        trace = project_trace(application._trace_store.read_trace("sql-responsive"))
        assert any(event.operation == "sql.execute.failed" for event in trace.timeline)
        assert not collector.is_degraded


def test_web_stop_and_readiness_work_during_real_sdk_sql(tmp_path, monkeypatch):
    """同一 ASGI 事件循环执行真实 SQL 时，readiness 和 Stop 仍能在计算结束前处理。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_export(raw, "web-sql(100).json", [
        make_message(f"m{i}", i, 1_700_000_000_000 + i, "并发 SQL") for i in range(1000)
    ], chat_name="并发SQL", peer_uid=None, version="5.5.64")
    monkeypatch.setattr(sqlite_read, "SQL_QUERY_TIMEOUT_SECONDS", 0.4)
    model = ScriptedModel([
        ModelStep(output=[function_call("execute_sql", {
            "sql": "SELECT COUNT(*) FROM messages a CROSS JOIN messages b CROSS JOIN messages c CROSS JOIN messages d",
            "max_rows": 1,
        }, call_id="sql")]),
        ModelStep(output=[assistant_message("已完成")]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(model=model, settings=_dynamic_settings())

    async def exercise():
        application = create_application(tmp_path / "messages.sqlite3", agent_runtime=runtime, router=RuleRouter())
        runtime.capability_registry = application.capability_registry
        application.import_directory(raw)
        entered = asyncio.Event()
        finished = threading.Event()
        loop = asyncio.get_running_loop()
        execute = application.read_repository.execute_readonly_sql

        def observe_sql(query, scope):
            # 只观察实际计算入口；事件循环唤醒后继续调用原 SQLite 实现。
            loop.call_soon_threadsafe(entered.set)
            try:
                return execute(query, scope)
            finally:
                finished.set()

        monkeypatch.setattr(application.read_repository, "execute_readonly_sql", observe_sql)
        try:
            transport = httpx.ASGITransport(app=create_web_app(application))
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                request = asyncio.create_task(client.post("/api/query/stream", json={
                    "query": "查一下记录", "scope": {"mode": "all"}, "request_id": "sql-stop",
                }))
                await asyncio.wait_for(entered.wait(), timeout=2)
                assert (await client.get("/api/readiness")).status_code == 200
                assert not finished.is_set(), "readiness waited for SQL to finish"
                stopped = await client.post("/api/query/stop", json={"request_id": "sql-stop"})
                assert stopped.status_code == 200
                response = await request
                events = [json.loads(line) for line in response.text.splitlines()]
                assert events[-1]["status"] == "aborted"
        finally:
            await application.aclose()

    asyncio.run(exercise())
