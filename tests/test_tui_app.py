"""TUI 应用级测试：基于 Textual Pilot 的真实交互回路。"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from textual.widgets import Input, ListView

from trivae.interfaces.tui.app import ChatScreen, PickerScreen, TrivaeChatApp
from trivae.interfaces.tui.widgets import ProcessRow
from trivae.query.streaming import QueryStreamEvent


def _event(event_type: str, **kwargs: object) -> QueryStreamEvent:
    counter = getattr(_event, "_counter", 0) + 1
    setattr(_event, "_counter", counter)
    return QueryStreamEvent(type=cast(object, event_type), sequence=counter, **kwargs)  # type: ignore[arg-type]


@dataclass
class _FakeSession:
    session_id: str = "session-1"
    name: str = "技术分享群"


@dataclass
class _FakeQueryResult:
    is_successful: bool = True
    final_answer: str = ""
    conversation_id: str | None = None
    trace_id: str | None = None
    termination: str = "completed"
    answer_artifact: object = None
    finalization_error: object = None
    is_degraded: bool = False
    runtime_result: object = field(default_factory=lambda: type("_R", (), {"run_id": None, "error": None})())


@dataclass
class _ScriptedApplication:
    """满足 TUI 所需最小接口的 Application 替身；不触碰 SQLite/Provider。"""

    script: list[QueryStreamEvent]
    result: _FakeQueryResult = field(default_factory=_FakeQueryResult)
    hang_forever: bool = False
    received_queries: list[str] = field(default_factory=list)

    @property
    def sessions(self) -> tuple[_FakeSession, ...]:
        return (_FakeSession(),)

    def list_sessions(self) -> tuple[_FakeSession, ...]:
        return self.sessions

    def readiness(self) -> None:
        return None

    async def query(self, request: object, *, on_event: object = None) -> _FakeQueryResult:
        handler = cast(object, on_event)
        self.received_queries.append(getattr(request, "query"))
        if self.hang_forever:
            await asyncio.Event().wait()
        if callable(handler):
            for event in self.script:
                handler(event)
                await asyncio.sleep(0)
        return self.result

    def export_trace_log(self, trace_id: str, **_: object) -> Path:
        return Path("/tmp") / f"{trace_id}.log"


_SIMPLE_SCRIPT = [
    _event("query.started"),
    _event("route.completed", route="planned_execution"),
    _event("thinking.delta", content="alpha", thinking_visibility="public_summary"),
    _event("thinking.delta", content="beta", thinking_visibility="public_summary"),
    _event("thinking.completed"),
    _event("answer.delta", content="最近推荐包括 "),
    _event("answer.delta", content="GitHub repos 与 skills"),
    _event("answer.completed", content="权威最终答案全文"),
    _event("query.completed"),
]

_TOOL_SCRIPT = [
    _event("tool.started", tool_name="search_messages", tool_call_id="call-A", arguments={"keywords": ["github"]}),
    _event(
        "retrieval.completed",
        result_summary={"candidate_count": 128, "returned_messages": 100},
        duration_ms=1700,
    ),
    _event("tool.completed", tool_name="search_messages", tool_call_id="call-A", duration_ms=1800),
    _event("tool.started", tool_name="semantic_search", tool_call_id="call-B"),
    _event(
        "tool.failed",
        tool_name="semantic_search",
        tool_call_id="call-B",
        duration_ms=10,
        error_code="SEMANTIC_INDEX_STALE",
        error_message="rebuild required",
    ),
    _event("answer.delta", content="回答正文"),
    _event("answer.completed", content="回答正文"),
    _event("query.completed"),
]


async def _enter_chat(app: TrivaeChatApp, pilot: object) -> ChatScreen:
    """模拟 picker 选择第一个群聊并进入会话屏。"""

    app._handle_picker_selection(1)
    await pilot.pause()  # type: ignore[attr-defined]
    screen = app.screen
    assert isinstance(screen, ChatScreen)
    return screen


async def _submit(chat: ChatScreen, pilot: object, text: str) -> None:
    chat.prompt.focus()
    chat.prompt.value = text
    await pilot.press("enter")  # type: ignore[attr-defined]


async def _wait_idle(app: TrivaeChatApp, pilot: object, limit: int = 500) -> None:
    for _ in range(limit):
        await pilot.pause()  # type: ignore[attr-defined]
        worker = app._active_worker
        if worker is None or not worker.is_running:
            break
        await asyncio.sleep(0.005)


class TuiAppInteractionTests(unittest.TestCase):
    """Textual Pilot 驱动的端到端交互验证。"""

    def _make_app(self, scripted: _ScriptedApplication) -> TrivaeChatApp:
        return TrivaeChatApp(
            scripted,  # type: ignore[arg-type]
            sessions=scripted.sessions,
            readiness_summary="ready",
        )

    def test_simple_run_streams_answer_then_collapses_process_group(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication(_SIMPLE_SCRIPT)
            app = self._make_app(scripted)
            async with app.run_test(size=(110, 40)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "整理最近的 GitHub 推荐")
                await _wait_idle(app, pilot)

                answers = list(app.screen.query("AnswerBlock"))
                self.assertEqual(len(answers), 1)
                body_text = answers[0].answer_text
                self.assertEqual(body_text, "权威最终答案全文")

                groups = list(app.screen.query("ProcessGroupWidget"))
                self.assertEqual(len(groups), 1)
                # route 行 + thinking 行聚合为 2 步。
                self.assertIn("执行过程 · 2 步", groups[0].title)

                self.assertFalse(chat.prompt.disabled)
                container_count = len(list(app.screen.query(".round")))
                self.assertEqual(container_count, 1)

        asyncio.run(scenario())

    def test_tool_rows_show_merged_metrics_and_manual_expand_survives(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication(_TOOL_SCRIPT)
            app = self._make_app(scripted)
            async with app.run_test(size=(120, 44)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "找一下推荐")
                await _wait_idle(app, pilot)

                rows = [row for row in app.screen.query("ProcessRow")]
                group = next(iter(app.screen.query("ProcessGroupWidget")), None)
                self.assertIsNotNone(group)
                # Collapsible 会把 children 包进内部容器；walk_children 直接找所有 ProcessRow。
                all_rows_in_group = list(group.walk_children(ProcessRow))
                self.assertGreaterEqual(len(rows), 1)

                # 展开 group（默认收起）后检查行内容与手动展开保持策略。
                group.collapsed = False
                await pilot.pause()

                target = next(row for row in all_rows_in_group if row.block.block_id == "tool:call-A")
                target.focus()
                await pilot.press("space")
                await pilot.pause()
                self.assertTrue(target.block.expanded)
                self.assertTrue(target.block.manually_expanded)

                summary_plain = target.render().plain
                self.assertIn("128 hits", summary_plain)
                del chat

        asyncio.run(scenario())

    def test_failed_tool_row_is_auto_expanded_with_error_details(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication(_TOOL_SCRIPT)
            app = self._make_app(scripted)
            async with app.run_test(size=(120, 44)) as pilot:
                await _enter_chat(app, pilot)
                await _submit(app.screen, pilot, "找一下推荐")
                await _wait_idle(app, pilot)

                failed = [
                    row
                    for row in app.screen.walk_children(ProcessRow)
                    if getattr(row, "block").status == "failed"
                ]
                self.assertEqual(len(failed), 1)
                detail_plain = failed[0].render().plain
                # 失败行自动展开，错误码与工具名直接可见。
                self.assertIn("语义检索", detail_plain)
                self.assertIn("SEMANTIC_INDEX_STALE", detail_plain)

        asyncio.run(scenario())

    def test_ctrl_c_interrupts_running_query_and_recovers_input(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication([], hang_forever=True)
            app = self._make_app(scripted)
            async with app.run_test(size=(110, 40)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "长时间的问题")
                await pilot.pause()
                self.assertTrue(chat.prompt.disabled)

                await pilot.press("ctrl+c")
                await _wait_idle(app, pilot)

                self.assertFalse(chat.prompt.disabled)
                error_lines = [
                    row.render().plain
                    for row in app.screen.query("ProcessRow")
                    if getattr(row, "block").kind == "error"
                ]
                self.assertTrue(any("已中断" in line for line in error_lines))

        asyncio.run(scenario())

    def test_multi_turn_queries_accumulate_rounds_without_clearing_history(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication([*_SIMPLE_SCRIPT])
            scripted.result.conversation_id = "conv-1"
            app = self._make_app(scripted)
            async with app.run_test(size=(110, 46)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "第一问")
                await _wait_idle(app, pilot)
                await _submit(chat, pilot, "第二问")
                await _wait_idle(app, pilot)

                headers = [static.renderable for static in app.screen.query(".round-header")]
                rendered = [h.plain if hasattr(h, "plain") else str(h) for h in headers]  # type: ignore[attr-defined]
                self.assertEqual(len(rendered), 2)
                self.assertIn("You > 第一问", rendered[0])
                self.assertEqual(scripted.received_queries, ["第一问", "第二问"])

        asyncio.run(scenario())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class PlainFallbackTests(unittest.TestCase):
    """--plain 与非 TTY fallback 的入口契约。"""

    def test_chat_parser_plain_flag_is_additive_and_defaults_off(self) -> None:
        from trivae.interfaces import cli

        default_args = cli.build_parser().parse_args(["chat"])
        self.assertFalse(default_args.plain)

        plain_args = cli.build_parser().parse_args(["chat", "--plain"])
        self.assertTrue(plain_args.plain)


class RealKeyPathTests(unittest.TestCase):
    """完全通过 Pilot 按键驱动的真实交互路径回归。

    背景：此前手工调用 `_handle_picker_selection()` 绕过了 picker 屏，
    导致「Enter 默认直通」与「/exit 关闭竞态」两类缺陷漏测；本组测试禁止任何 hook。
    """

    def test_picker_arrows_select_session_then_help_then_clean_exit(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication([])
            app = TrivaeChatApp(scripted, sessions=scripted.sessions, readiness_summary="ready")
            async with app.run_test(size=(110, 40)) as pilot:
                await pilot.pause()
                self.assertIsInstance(app.screen, PickerScreen)
                # 初始焦点在列表上，第 0 项为「全部群聊」。
                self.assertIsInstance(app.focused, ListView)

                # ↓ 移动到第一个真实群聊再 Enter，进入会话屏。
                await pilot.press("down")
                await pilot.press("enter")
                for _ in range(5):
                    await pilot.pause()
                chat = app.screen
                self.assertIsInstance(chat, ChatScreen)
                self.assertEqual(app._selected_name, "技术分享群")
                self.assertEqual(
                    app._scope.allowed_session_ids,  # type: ignore[union-attr]
                    ("session-1",),
                )
                # AUTO_FOCUS 应把焦点交给输入框（文档化行为断言）。
                for _ in range(3):
                    if isinstance(app.focused, Input):
                        break
                    await pilot.pause()
                self.assertIsInstance(app.focused, Input)

                # /help 完整输出 12 行且不崩溃。
                before_help = len(list(chat.history.children))
                for char in "/help":
                    await pilot.press(char)
                await pilot.press("enter")
                for _ in range(8):
                    await pilot.pause()
                after_help = len(list(chat.history.children))
                self.assertEqual(after_help - before_help, 12)
                self.assertFalse(chat.prompt.disabled)

                # /exit 必须干净退出：run_test 在消息泵抛异常时会向外传播，
                # 走到这里即证明没有 MountError/crash。
                for char in "/exit":
                    await pilot.press(char)
                await pilot.press("enter")
                for _ in range(10):
                    await pilot.pause()

            self.assertEqual(app.return_code, 0)

        asyncio.run(scenario())

    def test_picker_enter_without_arrows_selects_all_chats_scope(self) -> None:
        """直接 Enter（提示行已写明）选择全部群聊，与 plain CLI 的 0 语义一致。"""

        async def scenario() -> None:
            scripted = _ScriptedApplication([])
            app = TrivaeChatApp(scripted, sessions=scripted.sessions, readiness_summary="ready")
            async with app.run_test(size=(110, 40)) as pilot:
                await pilot.pause()
                await pilot.press("enter")
                for _ in range(5):
                    await pilot.pause()
                self.assertIsInstance(app.screen, ChatScreen)
                assert app._scope is not None
                self.assertIsNone(app._scope.allowed_session_ids)
                self.assertEqual(app._selected_name, "全部群聊")

        asyncio.run(scenario())
