"""TUI 应用级测试：基于 Textual Pilot 的真实交互回路。"""

from __future__ import annotations

import os

# Home/PageUp 等导航动作默认带 ease-out 补间动画，尾部收敛帧数随负载波动；
# 曾出现 scroll_y=0.0077 被 assertEqual(..., 0) 偶发拒绝。这些测试验证的是
# 滚动位置与 follow_tail 状态机的终态语义而非动画过程，因此统一禁用补间，
# 让 Animator 直接落到目标值（on_complete 回调仍按序触发）。
os.environ.setdefault("TEXTUAL_ANIMATIONS", "none")

import asyncio
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from textual import events
from textual.widgets import Input, ListView, Markdown, Static

from trivae.interfaces.tui.app import ChatScreen, PickerScreen, TrivaeChatApp
from trivae.interfaces.tui.widgets import AnswerBlock, ProcessGroupWidget, ProcessRow
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
        if callable(handler):
            for event in self.script:
                handler(event)
                await asyncio.sleep(0)
        if self.hang_forever:
            await asyncio.Event().wait()
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
        tool_call_id="call-A",
        result_summary={"candidate_count": 128, "returned_messages": 100},
        duration_ms=1700,
    ),
    _event(
        "tool.completed",
        tool_name="search_messages",
        tool_call_id="call-A",
        duration_ms=1800,
        result_detail="[1]\nsender: 小明\ncontent: 工具返回的真实正文",
    ),
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


_TOOL_SCRIPT_LONG_ANSWER = [
    *_TOOL_SCRIPT[:-4],
    *[
        _event("answer.delta", content="\n".join(f"回答段落第 {index} 行" for index in range(1, 41))),
        _event("answer.completed", content="\n".join(f"回答段落第 {index} 行" for index in range(1, 41))),
        _event("query.completed"),
    ],
]


# 完成态往返测试脚本：public thinking 多段正文 + tool detail + 较长 answer，
# 保证展开/收起前后的几何差异足够大。
_COLLAPSE_ROUND_SCRIPT = [
    _event("query.started"),
    _event("route.completed", route="planned_execution"),
    _event("thinking.started"),
    *(
        _event(
            "thinking.delta",
            content=f"公开摘要第 {index} 行正文，混合中文字符宽度。" * 2,
            thinking_visibility="public_summary",
        )
        for index in range(6)
    ),
    _event("thinking.completed"),
    _event("tool.started", tool_name="search_messages", tool_call_id="call-A", arguments={"keywords": ["github"]}),
    _event(
        "tool.completed",
        tool_name="search_messages",
        tool_call_id="call-A",
        duration_ms=1800,
        result_detail="\n".join(f"[{i}] sender: u{i} content: 工具返回的第 {i} 条详细正文。" for i in range(8)),
    ),
    _event("answer.delta", content="\n".join(f"回答段落 {index}" for index in range(1, 12))),
    _event("answer.completed", content="\n".join(f"回答段落 {index}" for index in range(1, 12))),
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
                collapsed_height = target.region.height
                target.focus()
                await pilot.press("space")
                for _ in range(3):
                    await pilot.pause()
                self.assertTrue(target.block.expanded)
                self.assertTrue(target.block.manually_expanded)

                summary_plain = target.render().plain
                self.assertIn("128 hits", summary_plain)
                self.assertIn("工具返回的真实正文", summary_plain)
                # 用户看到的是实际布局，不是 render() 的离屏字符串；展开后必须真实增高。
                self.assertGreater(target.region.height, collapsed_height)
                del chat

        asyncio.run(scenario())

    def test_manual_expand_collapse_roundtrip_reclaims_history_geometry(self) -> None:
        """A5：group 内行 expanded → collapsed 往返后几何必须完整回收。

        三个断言对应 handoff addendum A5 的三条验收：
        (a) 行可见高度回到 summary 单行；
        (b) #history 总内容高度恢复到展开前；
        (c) AnswerBlock 自身高度与其内容一致——不允许弹性容器
            吞掉相邻行释放的空间，在历史区中间留下空白。
        """

        async def scenario() -> None:
            scripted = _ScriptedApplication(list(_COLLAPSE_ROUND_SCRIPT))
            app = self._make_app(scripted)
            async with app.run_test(size=(96, 30)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "检查折叠往返")
                await _wait_idle(app, pilot)

                history = chat.history
                groups = list(app.screen.query(ProcessGroupWidget))
                self.assertEqual(len(groups), 1)
                group = groups[0]
                group.collapsed = False
                for _ in range(8):
                    await pilot.pause()

                rows = list(group.walk_children(ProcessRow))
                target = next(row for row in rows if row.block.kind == "thinking")
                base_row_h = target.region.height
                base_vsize = history.virtual_size.height

                target.focus()
                await pilot.press("space")
                for _ in range(8):
                    await pilot.pause()
                expanded_row_h = target.region.height
                self.assertGreater(expanded_row_h, base_row_h)

                target.focus()
                await pilot.press("space")
                for _ in range(8):
                    await pilot.pause()
                self.assertFalse(target.block.expanded)

                # (a) 行可见高度回到 summary 单行。
                self.assertEqual(target.region.height, base_row_h)
                # (b) #history 内容总高恢复到展开前。
                self.assertEqual(history.virtual_size.height, base_vsize)

                # (c) 每个 AnswerBlock 高度必须等于标题 + 正文内容高度；
                # 超出即为折叠后不可见的弹性空白。
                answers = list(app.screen.query(AnswerBlock))
                self.assertTrue(answers)
                for answer in answers:
                    body = answer.query_one(".answer-body", Markdown)
                    slack = answer.region.height - body.region.height
                    self.assertLessEqual(
                        slack,
                        1,
                        f"AnswerBlock 高度 {answer.region.height} 与其内容 {body.region.height} "
                        f"相差超过 1 行：存在未回收的布局空白",
                    )

        asyncio.run(scenario())

    def test_live_running_thinking_collapse_reclaims_height_during_stream(self) -> None:
        """A5：running 态 live 行手动收起必须立即回收高度（timeline 路径）。

        历史先用长占位内容撑过一屏再开始查询：内容小于视口时
        #history.virtual_size 被 Textual clamp 到视口高度，无法体现回收；
        只有内容超出视口，折叠释放的行数才会反映到总内容高度上。
        """

        async def scenario() -> None:
            live_script = [
                _event("query.started"),
                _event("thinking.started"),
                *(
                    _event(
                        "thinking.delta",
                        content=f"运行中公开摘要第 {index} 行。" * 4,
                        thinking_visibility="public_summary",
                    )
                    for index in range(8)
                ),
                _event("answer.delta", content="流式回答预览"),
            ]
            scripted = _ScriptedApplication(live_script, hang_forever=True)
            app = self._make_app(scripted)
            async with app.run_test(size=(96, 30)) as pilot:
                chat = await _enter_chat(app, pilot)
                chat.begin_round_view(998, "前置长历史")
                chat.append_note_lines([f"历史消息 {index}" for index in range(48)])
                for _ in range(4):
                    await pilot.pause()
                await _submit(chat, pilot, "运行中收起")
                for _ in range(10):
                    await pilot.pause()

                history = chat.history
                target = next(
                    row for row in app.screen.walk_children(ProcessRow) if row.block.kind == "thinking"
                )
                self.assertTrue(target.block.expanded)
                self.assertGreater(history.max_scroll_y, 0, "前置历史必须撑出滚动余量")

                expanded_row_h = target.region.height
                expanded_vsize = history.virtual_size.height

                app.handle_manual_toggle(target.block.block_id, False, target)
                for _ in range(8):
                    await pilot.pause()
                self.assertFalse(target.block.expanded)

                # 收起后行高立即回到单行；释放的高度完整反映到总内容高度上。
                self.assertEqual(target.region.height, 1)
                released = expanded_row_h - target.region.height
                self.assertGreater(released, 1)
                self.assertLess(
                    history.virtual_size.height,
                    expanded_vsize,
                    "收起运行中的思考行后 #history 总内容高度没有缩减",
                )
                self.assertAlmostEqual(
                    expanded_vsize - history.virtual_size.height,
                    released,
                    delta=1,
                    msg="释放的行数应与行高缩减量一致",
                )

                answers = list(app.screen.query(AnswerBlock))
                for answer in answers:
                    body = answer.query_one(".answer-body", Markdown)
                    slack = answer.region.height - body.region.height
                    self.assertLessEqual(slack, 1, "running 态 AnswerBlock 不允许存在弹性空白")

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

    def test_selection_ctrl_c_copies_before_interrupting_active_query(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication(
                [
                    _event(
                        "tool.started",
                        tool_name="search_messages",
                        tool_call_id="copy-call",
                        arguments={"keyword": "复制目标"},
                    )
                ],
                hang_forever=True,
            )
            app = self._make_app(scripted)
            async with app.run_test(size=(110, 40)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "运行中复制")
                for _ in range(5):
                    await pilot.pause()

                row = next(iter(app.screen.query("ProcessRow")))
                self.assertTrue(row.block.expanded)
                await pilot.click(row, offset=(2, 0))
                await pilot.pause()
                self.assertFalse(row.block.expanded)
                await pilot.click(row, offset=(2, 0))
                await pilot.pause()
                self.assertTrue(row.block.expanded)
                # 双击详情正文建立 Textual 原生选择；详情点击不得触发折叠。
                await pilot.double_click(row, offset=(6, 3))
                selected = app.screen.get_selected_text()
                self.assertIsNotNone(selected)
                self.assertTrue(row.block.expanded)

                await pilot.press("ctrl+c")
                await pilot.pause()
                self.assertEqual(app._clipboard, selected)
                self.assertIsNotNone(app._active_worker)
                self.assertTrue(app._active_worker.is_running)

                # 清除选择后，同一快捷键才中断当前 run。
                app.screen.clear_selection()
                await pilot.press("ctrl+c")
                await _wait_idle(app, pilot)
                self.assertFalse(chat.prompt.disabled)

        asyncio.run(scenario())

    def test_idle_ctrl_c_does_not_exit(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication([])
            app = self._make_app(scripted)
            async with app.run_test(size=(100, 32)) as pilot:
                chat = await _enter_chat(app, pilot)
                await pilot.press("ctrl+c")
                await pilot.pause()
                self.assertIs(app.screen, chat)
                self.assertTrue(app.is_running)

        asyncio.run(scenario())

    def test_ctrl_q_is_the_explicit_quit_key(self) -> None:
        """PRD R3：空闲与运行中 Ctrl+Q 都是显式退出路径；与 Ctrl+C 三态语义无关。"""

        async def scenario() -> None:
            scripted = _ScriptedApplication([], hang_forever=True)
            app = self._make_app(scripted)
            async with app.run_test(size=(100, 32)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "运行中退出")
                for _ in range(3):
                    await pilot.pause()
                self.assertIsNotNone(app._active_worker)
                self.assertTrue(app._active_worker.is_running)
                await pilot.press("ctrl+q")
                for _ in range(3):
                    await pilot.pause()
                self.assertFalse(app.is_running)

        asyncio.run(scenario())

    def test_thinking_and_answer_bodies_participate_in_native_selection(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication(
                [
                    _event("thinking.started"),
                    _event("thinking.delta", content="公开思考摘要", thinking_visibility="public_summary"),
                    _event("answer.delta", content="可复制的回答正文"),
                ],
                hang_forever=True,
            )
            app = self._make_app(scripted)
            async with app.run_test(size=(110, 40)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "选择两类正文")
                for _ in range(6):
                    await pilot.pause()

                thinking = next(
                    row for row in app.screen.query("ProcessRow") if row.block.kind == "thinking"
                )
                # Thinking delta 从单行标题更新成多行正文后，真实布局不得被裁成 1 行。
                self.assertGreater(thinking.region.height, 1)
                await pilot.double_click(thinking, offset=(6, 1))
                thinking_selection = app.screen.get_selected_text()
                self.assertIsNotNone(thinking_selection)
                self.assertIn("公开思考摘要", thinking_selection)
                self.assertTrue(thinking.block.expanded)

                app.screen.clear_selection()
                answer = next(iter(app.screen.query(Markdown)))
                await pilot.double_click(answer, offset=(5, 0))
                answer_selection = app.screen.get_selected_text()
                self.assertIsNotNone(answer_selection)
                await pilot.press("ctrl+c")
                await pilot.pause()
                self.assertEqual(app._clipboard, answer_selection)
                self.assertTrue(app._active_worker.is_running)

                app.screen.clear_selection()
                await pilot.press("ctrl+c")
                await _wait_idle(app, pilot)

        asyncio.run(scenario())

    def test_follow_tail_detaches_on_upward_scroll_and_reattaches_at_end(self) -> None:
        async def scenario() -> None:
            scripted = _ScriptedApplication([])
            app = self._make_app(scripted)
            async with app.run_test(size=(90, 18)) as pilot:
                chat = await _enter_chat(app, pilot)
                # 真实问答内容都挂在 round 容器内；直接向 history 挂行会绕过实际故障。
                chat.begin_round_view(98, "历史滚动")
                chat.append_note_lines([f"历史消息 {index}" for index in range(80)])
                for _ in range(5):
                    await pilot.pause()
                self.assertTrue(chat.history.follow_tail)
                self.assertGreater(chat.history.max_scroll_y, 0)
                self.assertTrue(chat.history.is_vertical_scroll_end)

                chat.history.focus()
                await pilot.press("pageup")
                await pilot.pause()
                self.assertFalse(chat.history.follow_tail)
                detached_y = chat.history.scroll_y
                self.assertLess(detached_y, chat.history.max_scroll_y)

                chat.append_note_lines(["流式新增 A", "流式新增 B"])
                for _ in range(3):
                    await pilot.pause()
                self.assertEqual(chat.history.scroll_y, detached_y)

                await pilot.press("end")
                for _ in range(3):
                    await pilot.pause()
                self.assertTrue(chat.history.follow_tail)
                self.assertTrue(chat.history.is_vertical_scroll_end)

                await pilot.press("home")
                await pilot.pause()
                self.assertFalse(chat.history.follow_tail)
                self.assertEqual(chat.history.scroll_y, 0)
                await pilot.press("end")
                await pilot.pause()
                await pilot.press("pageup")
                await pilot.pause()
                await pilot.press("pagedown")
                for _ in range(3):
                    await pilot.pause()
                self.assertTrue(chat.history.follow_tail)
                self.assertTrue(chat.history.is_vertical_scroll_end)

                # 滚轮向上同样解除跟随，覆盖真实鼠标事件路径。
                await pilot._post_mouse_events(  # type: ignore[attr-defined]
                    [events.MouseScrollUp],
                    chat.history,
                    offset=(2, 2),
                )
                self.assertFalse(chat.history.follow_tail)
                # 旧测试只看 follow_tail bool，会漏掉“状态变了但视口完全没滚”的真实故障。
                self.assertLess(chat.history.scroll_y, chat.history.max_scroll_y)

                # 新一轮是用户主动导航意图，必须重新跟随到新轮起点。
                chat.begin_round_view(99, "新一轮")
                for _ in range(3):
                    await pilot.pause()
                self.assertTrue(chat.history.follow_tail)
                self.assertTrue(chat.history.is_vertical_scroll_end)

        asyncio.run(scenario())

    def test_wheel_bubbles_from_inner_children_to_history(self) -> None:
        """悬停在 history 内部子组件上的滚轮必须冒泡到 #history 并移动真实 scroll_y。

        背景（handoff A3）：旧测试只把 wheel 直接投递给 #history 自身；真机用户
        的指针悬停在正文、工具行等内层组件上。本测试把滚轮事件发往视口内实际
        命中 #history 后代的屏幕坐标；若任何内层 widget 截获滚动，
        此测试会以真实 scroll_y 变化失败暴露截获者。
        """

        def _history_descendant(app: TrivaeChatApp, x: int, y: int) -> object | None:
            """返回该屏幕坐标命中的、位于 #history 子树内的最深 widget。"""

            hit, _ = app.get_widget_at(x, y)
            node = hit
            while node is not None and node is not app.screen.query_one("#history"):
                node = node.parent
            return hit if node is not None else None

        async def scenario() -> None:
            scripted = _ScriptedApplication(_TOOL_SCRIPT_LONG_ANSWER)
            app = self._make_app(scripted)
            async with app.run_test(size=(90, 18)) as pilot:
                chat = await _enter_chat(app, pilot)
                await _submit(chat, pilot, "滚动悬停目标")
                await _wait_idle(app, pilot)

                history = chat.history
                self.assertTrue(history.follow_tail)
                self.assertGreater(history.max_scroll_y, 0)

                # 底部跟随态下，视口下缘附近命中 AnswerBlock 正文：向上滚轮应解除跟随并离开底部。
                answer_point = (history.region.x + 3, history.region.bottom - 5)
                answer_hit = _history_descendant(app, *answer_point)
                self.assertIsNotNone(answer_hit, "视口底部没有命中任何 #history 后代")
                await pilot._post_mouse_events([events.MouseScrollUp], offset=answer_point)  # type: ignore[attr-defined]
                for _ in range(6):
                    await pilot.pause()
                self.assertFalse(history.follow_tail, "悬停在正文上的滚轮未解除 follow_tail")
                self.assertLess(history.scroll_y, history.max_scroll_y)

                # 回到顶部让 process group 进入视口，再从其标题区域向下滚轮冒泡。
                chat.history.focus()
                await pilot.press("home")
                for _ in range(3):
                    await pilot.pause()
                self.assertEqual(history.scroll_y, 0)
                group = next(iter(app.screen.query("ProcessGroupWidget")))
                group_point = (group.region.x + 3, group.region.y)
                group_hit = _history_descendant(app, *group_point)
                self.assertIsNotNone(group_hit, "视口顶部没有命中 process group 区域")

                # 向下逐格滚动到达真实底部时由位置 watcher 恢复跟随。
                for _ in range(40):
                    await pilot._post_mouse_events([events.MouseScrollDown], offset=group_point)  # type: ignore[attr-defined]
                    await pilot.pause()
                    if history.is_vertical_scroll_end:
                        break
                for _ in range(4):
                    await pilot.pause()
                self.assertTrue(
                    history.is_vertical_scroll_end,
                    "悬停在 process group 上的向下滚轮未移动 #history 真实 scroll_y",
                )
                self.assertTrue(history.follow_tail)

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

                headers = list(app.screen.query(".round-header"))
                rendered = [header.render().plain for header in headers if isinstance(header, Static)]
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
