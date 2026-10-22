"""真实SQLite计算超过执行期限时须返回显式错误，不能由max_rows冒充计算上限。"""

from __future__ import annotations

from time import perf_counter

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecuteSQLInput, ExecutionScope
from trivae.data.storage import sqlite_read


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
