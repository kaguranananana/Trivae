from __future__ import annotations

import asyncio
import inspect
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.data.model import ChatSession
from trivae.interfaces import cli
from trivae.query.contracts import QueryRequest


@dataclass(frozen=True)
class _FakeResult:
    """只模拟 CLI 读取的 QueryResult 正式投影，不连接真实 Provider。"""

    final_answer: str | None
    runtime_answer: str | None
    conversation_id: str | None
    trace_id: str | None
    is_successful: bool
    termination: str = "completed"
    finalization_error: object | None = None
    runtime_result: object = field(default_factory=lambda: SimpleNamespace(error=None))


class _FakeApplication:
    """提供正式 Application facade 形状，记录 CLI 传入的 QueryRequest。"""

    def __init__(self, sessions: tuple[ChatSession, ...], results: list[_FakeResult]) -> None:
        self.sessions = sessions
        self.results = results
        self.requests: list[QueryRequest] = []
        self.list_sessions_calls = 0

    def list_sessions(self) -> tuple[ChatSession, ...]:
        """返回 fake read facade 的 session projection。"""

        self.list_sessions_calls += 1
        return self.sessions

    async def query(self, request: QueryRequest) -> _FakeResult:
        """记录正式 QueryRequest，并按脚本返回 QueryResult 投影。"""

        self.requests.append(request)
        if not self.results:
            raise AssertionError("the scripted query result list is exhausted")
        return self.results.pop(0)


def _session(session_id: str, name: str) -> ChatSession:
    """构造与 Canonical Store 相同语义的群聊 metadata。"""

    platform, external_chat_id = session_id.split(":", maxsplit=1)
    return ChatSession(
        platform=platform,
        external_chat_id=external_chat_id,
        name=name,
        chat_type="group",
        self_uid=None,
        self_uin=None,
    )


def _scripted_input(values: list[object]) -> tuple[list[str], object]:
    """返回记录 prompt 的输入函数，支持显式模拟 EOF/Ctrl+C。"""

    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        if not values:
            raise AssertionError("the scripted input list is exhausted")
        value = values.pop(0)
        if isinstance(value, BaseException):
            raise value
        if not isinstance(value, str):
            raise AssertionError("scripted input must be text or an exception")
        return value

    return prompts, read


class ChatCliTests(unittest.TestCase):
    """验证 chat interface 的 scope、conversation 和正式结果 projection。"""

    def test_chat_parser_uses_the_default_database(self) -> None:
        """chat parser 应识别命令并沿用现有默认数据库路径。"""

        args = cli.build_parser().parse_args(["chat"])

        self.assertEqual(args.command, "chat")
        self.assertEqual(args.database, Path("data/trivae.sqlite3"))

    def test_chat_parser_keeps_existing_import_trace_and_eval_commands(self) -> None:
        """新增子命令不能让原有入口失去 parser 识别能力。"""

        parser = cli.build_parser()

        self.assertEqual(parser.parse_args(["import", "--raw-dir", "raw"]).command, "import")
        self.assertEqual(parser.parse_args(["trace", "show", "trace-1"]).trace_command, "show")
        self.assertEqual(parser.parse_args(["eval", "regression"]).evaluation_command, "regression")

    def test_application_lists_sessions_through_the_read_facade(self) -> None:
        """session 列表来自 Application，且按稳定名称顺序返回真实 Canonical 数据。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_directory = root / "raw"
            raw_directory.mkdir()
            write_export(
                raw_directory,
                "beta(200).json",
                [make_message("b1", 1, 1_700_000_000_000, "beta")],
                chat_name="Beta 群",
                peer_uid=None,
                version="5.5.64",
            )
            write_export(
                raw_directory,
                "alpha(100).json",
                [make_message("a1", 1, 1_700_000_000_001, "alpha")],
                chat_name="Alpha 群",
                peer_uid=None,
                version="5.5.64",
            )

            with create_application(root / "chat.sqlite3") as application:
                application.import_directory(raw_directory)
                sessions = application.list_sessions()

            self.assertEqual([session.name for session in sessions], ["Alpha 群", "Beta 群"])
            self.assertEqual([session.session_id for session in sessions], ["qq:100", "qq:200"])

    def test_selected_chat_scope_and_conversation_are_kept_across_queries(self) -> None:
        """连续问题复用 conversation，但 scope 始终绑定初始群聊。"""

        application = _FakeApplication(
            (_session("qq:100", "AI 群"), _session("qq:200", "秋招群")),
            [
                _FakeResult("answer-1", "runtime-1", "conversation-1", "trace-1", True),
                _FakeResult("answer-2", "runtime-2", "conversation-1", "trace-2", True),
            ],
        )
        prompts, input_fn = _scripted_input(["1", "第一问", "第二问", "/exit"])
        output: list[str] = []

        exit_code = asyncio.run(cli._run_interactive_chat(application, input_fn=input_fn, output_fn=output.append))

        self.assertEqual(exit_code, 0)
        self.assertEqual(application.list_sessions_calls, 1)
        self.assertEqual(prompts, ["Select chat > ", "You > ", "You > ", "You > "])
        self.assertEqual([request.conversation_id for request in application.requests], [None, "conversation-1"])
        self.assertEqual(
            [request.scope.allowed_session_ids for request in application.requests],
            [("qq:100",), ("qq:100",)],
        )
        self.assertIn("Selected: AI 群", output)
        self.assertIn("answer-1", output)
        self.assertIn("answer-2", output)
        self.assertIn("[trace: trace-1]", output)
        self.assertIn("[trace: trace-2]", output)

    def test_all_chats_uses_unrestricted_scope(self) -> None:
        """选择 0 使用 None 表示 unrestricted，不伪造 ALL 或星号 session。"""

        application = _FakeApplication(
            (_session("qq:100", "AI 群"),),
            [_FakeResult("answer", "runtime", "conversation", "trace", True)],
        )
        _, input_fn = _scripted_input(["0", "问题", "/quit"])

        exit_code = asyncio.run(cli._run_interactive_chat(application, input_fn=input_fn, output_fn=lambda _: None))

        self.assertEqual(exit_code, 0)
        self.assertEqual(application.requests[0].scope.allowed_session_ids, None)

    def test_new_resets_only_conversation(self) -> None:
        """/new 使下一轮 conversation_id 为空，但不改变选中的群聊 scope。"""

        application = _FakeApplication(
            (_session("qq:100", "AI 群"),),
            [
                _FakeResult("answer-1", "runtime-1", "conversation-1", "trace-1", True),
                _FakeResult("answer-2", "runtime-2", "conversation-2", "trace-2", True),
            ],
        )
        _, input_fn = _scripted_input(["1", "第一问", "/new", "新会话问题", "/quit"])

        exit_code = asyncio.run(cli._run_interactive_chat(application, input_fn=input_fn, output_fn=lambda _: None))

        self.assertEqual(exit_code, 0)
        self.assertEqual([request.conversation_id for request in application.requests], [None, None])
        self.assertEqual(
            [request.scope.allowed_session_ids for request in application.requests],
            [("qq:100",), ("qq:100",)],
        )

    def test_final_answer_is_displayed_without_runtime_fallback(self) -> None:
        """成功 Query 只展示 final_answer，runtime_answer 只能留在诊断 contract。"""

        application = _FakeApplication(
            (_session("qq:100", "AI 群"),),
            [_FakeResult("formal final answer", "raw runtime answer", "conversation", "trace", True)],
        )
        _, input_fn = _scripted_input(["1", "问题", "/exit"])
        output: list[str] = []

        asyncio.run(cli._run_interactive_chat(application, input_fn=input_fn, output_fn=output.append))

        self.assertIn("formal final answer", output)
        self.assertNotIn("raw runtime answer", output)

    def test_failed_query_displays_readable_error_without_runtime_fallback(self) -> None:
        """没有 final_answer 时显示正式错误投影，不能偷偷退回 runtime 文本。"""

        finalization_error = SimpleNamespace(message="citation finalization failed")
        application = _FakeApplication(
            (_session("qq:100", "AI 群"),),
            [
                _FakeResult(
                    None,
                    "raw runtime answer",
                    "conversation",
                    "trace",
                    False,
                    termination="failed",
                    finalization_error=finalization_error,
                )
            ],
        )
        _, input_fn = _scripted_input(["1", "问题", "/exit"])
        output: list[str] = []

        asyncio.run(cli._run_interactive_chat(application, input_fn=input_fn, output_fn=output.append))

        self.assertIn("Error: citation finalization failed", output)
        self.assertIn("[trace: trace]", output)
        self.assertNotIn("raw runtime answer", output)

    def test_exit_and_quit_do_not_call_query(self) -> None:
        """/exit 和 /quit 都是正常退出命令。"""

        for command in ("/exit", "/quit"):
            with self.subTest(command=command):
                application = _FakeApplication((_session("qq:100", "AI 群"),), [])
                _, input_fn = _scripted_input(["1", command])

                exit_code = asyncio.run(
                    cli._run_interactive_chat(application, input_fn=input_fn, output_fn=lambda _: None)
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(application.requests, [])

    def test_eof_and_ctrl_c_exit_without_query(self) -> None:
        """picker 和聊天输入遇到 EOF/Ctrl+C 都不产生长 traceback。"""

        for interrupt in (EOFError(), KeyboardInterrupt()):
            with self.subTest(interrupt=type(interrupt).__name__):
                application = _FakeApplication((_session("qq:100", "AI 群"),), [])
                _, input_fn = _scripted_input(["1", interrupt])
                output: list[str] = []

                exit_code = asyncio.run(
                    cli._run_interactive_chat(application, input_fn=input_fn, output_fn=output.append)
                )

                self.assertEqual(exit_code, 0)
                self.assertEqual(application.requests, [])
                self.assertIn("Bye.", output)

    def test_chat_loop_uses_application_query_not_runtime_or_retrieval(self) -> None:
        """静态边界回归：交互 loop 只能通过 Application query 进入生产链路。"""

        source = inspect.getsource(cli._run_interactive_chat)

        self.assertIn("application.query", source)
        self.assertNotIn("run_agent", source)
        self.assertNotIn("retrieve_messages", source)
        self.assertNotIn("invoke_tool", source)

    def test_known_settings_error_is_readable(self) -> None:
        """Provider 配置缺失时显示分类错误，而不是吞错或打印未知成功。"""

        output = StringIO()
        with patch.object(cli, "create_application", side_effect=cli.SettingsError("DEEPSEEK_API_KEY is required")):
            with redirect_stdout(output):
                # 使用 main 验证 parser 到 chat command 的完整同步入口；错误由 CLI 转投影。
                exit_code = cli.main(["chat"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: DEEPSEEK_API_KEY is required", output.getvalue())


if __name__ == "__main__":
    unittest.main()
