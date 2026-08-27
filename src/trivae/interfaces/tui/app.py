"""Trivae interactive chat 的 Textual TUI 应用。

只消费 QueryStreamEvent（经 TuiProjectionEngine 投影）；
不重建执行链路，不订阅 provider SDK。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Collapsible, Footer, Input, Label, ListItem, ListView, Static

from trivae.capabilities.contracts import ExecutionScope
from trivae.interfaces.tui.models import (
    PROCESS_BLOCK_KINDS,
    TuiBlock,
    TuiChange,
    TuiProjectionEngine,
)
from trivae.interfaces.tui.widgets import AnswerBlock, ProcessGroupWidget, ProcessRow
from trivae.query.contracts import QueryRequest

if TYPE_CHECKING:
    from textual.worker import Worker

    from trivae.bootstrap.application import TrivaeApplication
    from trivae.data.model import ChatSession
    from trivae.query.evidence import AnswerSourceSummary


class StreamChanges(Message):
    """engine 投影结果的批量送达；由 ChatScreen 消费并落到 widget。"""

    def __init__(self, changes: tuple[TuiChange, ...]) -> None:
        super().__init__()
        self.changes = changes


class QuerySubmitted(Message):
    """用户提交一条输入。"""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class PickerScreen(Screen["int | None"]):
    """群聊选择屏；选择结果经 dismiss 回调进入 ChatScreen。"""

    CSS = """
    PickerScreen {
        align: center middle;
    }
    #picker-panel {
        width: 60%;
        max-width: 64;
        height: auto;
        max-height: 80%;
        border: round $primary;
        padding: 1 2;
    }
    #picker-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #picker-hint {
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "quit_app", "退出", show=False),
    ]

    def __init__(self, session_names: list[str], readiness_summary: str) -> None:
        super().__init__()
        self._session_names = ["全部群聊"] + session_names
        self._readiness_summary = readiness_summary

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-panel"):
            yield Label("Trivae", id="picker-title")
            yield Label("↑ ↓ 选择群聊 · Enter 确认（第一项为全部群聊）· Esc 退出", id="picker-hint")
            yield Label(self._readiness_summary)
            items = [ListItem(Label(f"{index}. {name}")) for index, name in enumerate(self._session_names)]
            yield ListView(*items)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """把选中的绝对序号交给 App；0 表示 unrestricted。"""

        event.stop()
        index = event.list_view.index
        self.dismiss(None if index is None else max(0, int(index)))

    def action_quit_app(self) -> None:
        self.app.exit()


@dataclass
class _Entry:
    """会话区内一个可见行的顺序记录。"""

    kind: str
    block_id: str | None
    widget: Widget


@dataclass
class _RoundState:
    """ChatScreen 内单轮的 widget 登记簿。"""

    container: Vertical
    entries: list[_Entry] = field(default_factory=list)
    rows: dict[str, Widget] = field(default_factory=dict)


class ChatScreen(Screen[None]):
    """会话屏：滚动历史 + 底部固定输入。"""

    AUTO_FOCUS = "#prompt"

    BINDINGS = [
        Binding("escape", "focus_prompt", "回到输入", show=False),
    ]

    CSS = """
    #history {
        height: 1fr;
        padding: 0 1;
    }
    .round-header {
        color: $accent;
        text-style: bold;
        margin-top: 1;
    }
    .process-row.kind-route {
        color: $text-muted;
    }
    .process-row.status-failed {
        color: $error;
    }
    .note-line {
        color: $text-muted;
    }
    #prompt-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
    }
    #prompt {
        border: round $primary;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._rounds: dict[int, _RoundState] = {}

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="history")
        with Vertical(id="prompt-bar"):
            yield Input(placeholder="You > 输入问题，/help 查看命令", id="prompt")
        yield Footer()

    @property
    def history(self) -> VerticalScroll:
        return self.query_one("#history", VerticalScroll)

    @property
    def prompt(self) -> Input:
        return self.query_one("#prompt", Input)

    def set_running(self, running: bool) -> None:
        """run 进行中禁用输入，结束后 focus 回输入框。"""

        self.prompt.disabled = running
        if not running:
            self.prompt.focus()

    def begin_round_view(self, round_id: int, query_text: str) -> None:
        """为一轮新问答建立容器与 You > 标题行。"""

        container = Vertical(classes="round")
        self._rounds[round_id] = _RoundState(container=container)
        bounded_query = query_text if len(query_text) <= 200 else f"{query_text[:199]}…"
        self.history.mount(container)
        container.mount(Static(f"You > {bounded_query}", classes="round-header"))
        self.history.scroll_end(animate=False, force=True)

    def round_has_answer(self, round_id: int) -> bool:
        state = self._rounds.get(round_id)
        if state is None:
            return False
        return any(entry.kind == "answer" for entry in state.entries)

    def mount_answer_fallback(self, round_id: int, answer_text: str) -> None:
        """无 streaming delta 时补挂正式回答 block（authoritative 文本）。"""

        state = self._rounds.get(round_id)
        if state is None or not answer_text:
            return
        fallback = TuiBlock(
            block_id=f"answer:{round_id}",
            kind="answer",
            status="completed",
            title="回答",
            expanded=True,
            streaming_text=answer_text,
        )
        widget = AnswerBlock(fallback)
        state.entries.append(_Entry(kind="answer", block_id=fallback.block_id, widget=widget))
        state.rows[fallback.block_id] = widget
        state.container.mount(widget)
        self.history.scroll_end(animate=False, force=True)

    def append_note_lines(self, lines: list[str], *, classes: str = "note-line") -> None:
        """命令输出与系统提示追加到最近一轮容器或历史区底部。"""

        if not lines:
            return
        target_container = self._latest_round_container()
        widgets = [Static(line, classes=classes) for line in lines]
        if target_container is None:
            self.history.mount(*widgets)
        else:
            target_container.mount(*widgets)
        self.history.scroll_end(animate=False, force=True)

    def append_collapsible_note(self, title: str, lines: list[str]) -> None:
        """折叠式备注块（如来源/证据），默认收起保证回答视觉权重。"""

        if not lines:
            return
        target_container = self._latest_round_container()
        block = Collapsible(
            *[Static(line, classes="note-line") for line in lines],
            title=title,
            collapsed=True,
        )
        if target_container is None:
            self.history.mount(block)
        else:
            target_container.mount(block)
        self.history.scroll_end(animate=False, force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        self.prompt.value = ""
        if not value or self.prompt.disabled:
            return
        self.post_message(QuerySubmitted(value))

    async def on_stream_changes(self, message: StreamChanges) -> None:
        pending_answer_updates: list[Awaitable[None]] = []
        for change in message.changes:
            update = self._apply_change(change)
            if isinstance(update, Awaitable):
                pending_answer_updates.append(update)
        for update in pending_answer_updates:
            await update
        self.history.scroll_end(animate=False, force=True)

    def on_process_row_toggled(self, event: ProcessRow.Toggled) -> None:
        """用户开合请求 → engine 确认（手动标记）→ 回写快照。"""

        event.stop()
        row = event.process_row
        app = self.app
        assert isinstance(app, TrivaeChatApp)
        app.handle_manual_toggle(event.block_id, event.expanded, row)

    def action_focus_prompt(self) -> None:
        self.prompt.focus()

    def _apply_change(self, change: TuiChange) -> object | None:
        """应用一个 change；答案更新返回协程由调用方按序 await。"""

        if change.action == "round_started":
            return None
        state = self._rounds.get(change.round_id)
        if state is None:
            return None
        if change.action == "block_created" and change.block is not None:
            block = change.block
            widget: Widget = AnswerBlock(block) if block.kind == "answer" else ProcessRow(block)
            state.rows[block.block_id] = widget
            state.entries.append(_Entry(kind=block.kind, block_id=block.block_id, widget=widget))
            state.container.mount(widget)
            return None
        if change.action == "block_updated" and change.block is not None:
            row = state.rows.get(change.block.block_id)
            if isinstance(row, ProcessRow):
                row.update_block(change.block)
            return None
        if change.action in {"answer_appended", "answer_finalized"} and change.block is not None:
            answer_row = state.rows.get(change.block.block_id)
            if isinstance(answer_row, AnswerBlock):
                text = change.block.streaming_text or ""
                return answer_row.update_text(text)
            return None
        if change.action == "round_collapsed" and change.group is not None:
            self._collapse_round(state, change)
        return None

    def _collapse_round(self, state: _RoundState, change: TuiChange) -> None:
        assert change.group is not None
        group_widget = ProcessGroupWidget(change.group)
        entries = state.entries
        first_process_index = next(
            (index for index, entry in enumerate(entries) if entry.kind in PROCESS_BLOCK_KINDS),
            len(entries),
        )
        removed = [entry for entry in entries if entry.kind in PROCESS_BLOCK_KINDS]
        kept_with_index = [
            (index, entry) for index, entry in enumerate(entries) if entry.kind not in PROCESS_BLOCK_KINDS
        ]
        anchor = next((entry.widget for index, entry in kept_with_index if index > first_process_index), None)
        for entry in removed:
            state.rows.pop(entry.block_id or "", None)
            entry.widget.remove()
        entries[:] = [entry for entry in entries if entry.kind not in PROCESS_BLOCK_KINDS]
        entries.append(_Entry(kind="group", block_id=None, widget=group_widget))
        anchor_group_id = f"group:{id(group_widget)}"
        state.rows[anchor_group_id] = group_widget
        state.container.mount(group_widget, before=anchor)

    def _latest_round_container(self) -> Vertical | None:
        states = list(self._rounds.values())
        return states[-1].container if states else None


class TrivaeChatApp(App[None]):
    """TUI 应用外壳：状态归属、query worker 与事件投影接线。"""

    TITLE = "Trivae"

    BINDINGS = [
        Binding("ctrl+c", "interrupt_or_quit", priority=True),
    ]

    def __init__(
        self,
        application: TrivaeApplication,
        *,
        sessions: tuple[ChatSession, ...],
        readiness_summary: str,
        verbose: bool = False,
    ) -> None:
        super().__init__()
        self._application = application
        self._sessions = sessions
        self._readiness_summary = readiness_summary
        self._verbose = verbose
        self._engine = TuiProjectionEngine()
        self._scope: ExecutionScope | None = None
        self._selected_name: str | None = None
        self._conversation_id: str | None = None
        self._last_sources: tuple[AnswerSourceSummary, ...] = ()
        self._last_result: object | None = None
        self._chat_screen: ChatScreen | None = None
        self._active_worker: Worker | None = None
        self._active_round_id: int | None = None
        # /exit、/quit 只标记意图；由输入回路在渲染完成后统一退出，避免关闭竞态。
        self._exit_requested = False

    def on_mount(self) -> None:
        names = [session.name for session in self._sessions]
        picker = PickerScreen(names, self._readiness_summary)
        self.push_screen(picker, callback=self._handle_picker_selection)

    # ---------- picker ----------

    def _handle_picker_selection(self, index: int | None) -> None:
        if index is None:
            self.exit()
            return
        if index == 0:
            # 0 是 contract 约定的 unrestricted 选择。
            self._scope = ExecutionScope(allowed_session_ids=None)
            selected_name = "全部群聊"
        elif 1 <= index <= len(self._sessions):
            selected_session = self._sessions[index - 1]
            self._scope = ExecutionScope(allowed_session_ids=(selected_session.session_id,))
            selected_name = selected_session.name
        else:
            self.exit()
            return
        self._selected_name = selected_name
        self._reset_conversation_state()
        chat_screen = ChatScreen()
        self._chat_screen = chat_screen
        self.push_screen(chat_screen)
        self.call_after_refresh(self._on_chat_ready)

    def _on_chat_ready(self) -> None:
        screen = self._chat_screen
        if screen is None:
            return
        screen.append_note_lines([f"Selected: {self._selected_name}"])
        # 启动只给一行轻提示；完整命令清单按需 /help，避免 12 行帮助把内容推出视口。
        screen.append_note_lines(["提示：直接提问开始检索；/help 查看全部命令"])
        screen.set_running(False)

    def _reset_conversation_state(self) -> None:
        self._conversation_id = None
        self._last_sources = ()
        self._last_result = None

    # ---------- input routing ----------

    async def on_query_submitted(self, message: QuerySubmitted) -> None:
        screen = self._chat_screen
        busy = self._active_worker is not None and self._active_worker.is_running
        if screen is None or busy:
            return
        if message.text.startswith("/"):
            lines = await self.execute_command(message.text)
            command = message.text.split(maxsplit=1)[0]
            # /help 是主动索取的命令清单，用正常前景色；其余备注保持暗色。
            screen.append_note_lines(lines, classes="" if command == "/help" else "note-line")
            if self._exit_requested:
                self.call_after_refresh(self.exit)
            return
        self.start_query(message.text)

    def start_query(self, text: str) -> None:
        screen = self._chat_screen
        if screen is None or self._scope is None:
            return
        worker_running = self._active_worker is not None and self._active_worker.is_running
        if worker_running:
            return
        request = QueryRequest(
            query=text,
            scope=self._scope,
            conversation_id=self._conversation_id,
        )
        round_id, begin_change = self._engine.begin_round(text)
        self._active_round_id = round_id
        screen.begin_round_view(round_id, text)
        screen.post_message(StreamChanges((begin_change,)))
        screen.set_running(True)
        self._active_worker = self.run_worker(
            self._query_flow(round_id, request),
            exclusive=True,
            exit_on_error=False,
            group="query",
        )

    def handle_manual_toggle(self, block_id: str, expanded: bool, row: ProcessRow) -> None:
        """用户开合的权威落点：先经 engine 确认，再回写 widget。"""

        for round_id in (*self._engine.finished_round_ids(), *([] if self._engine.active_round_id is None else [self._engine.active_round_id])):
            updated = self._engine.set_manual_expanded(round_id, block_id, expanded)
            if updated is not None:
                row.update_block(updated)
                return

    # ---------- streaming projection ----------

    def _on_stream_event(self, event: object) -> None:
        from trivae.query.streaming import QueryStreamEvent

        if not isinstance(event, QueryStreamEvent):
            return
        changes = self._engine.apply(event)
        if changes and self._chat_screen is not None:
            self._chat_screen.post_message(StreamChanges(changes))

    async def _query_flow(
        self,
        round_id: int,
        request: QueryRequest,
    ) -> None:
        """唯一 Query 主链路；TUI 不执行第二次 Agent run。"""

        screen = self._chat_screen
        try:
            result = await self._application.query(request, on_event=self._on_stream_event)
        except asyncio.CancelledError:
            await self._post_changes(self._engine.finalize_interrupted(round_id))
            self._finish_round_ui()
            return
        except Exception as exc:  # noqa: BLE001 - 分类与未知错误都必须恢复输入状态
            await self._post_changes(
                self._engine.finalize_failed(
                    round_id,
                    error_code=getattr(exc, "error_code", type(exc).__name__),
                    message=str(exc),
                )
            )
            trace_id = getattr(exc, "trace_id", None)
            if isinstance(trace_id, str) and trace_id and screen is not None:
                screen.append_note_lines([f"[trace: {trace_id}]"])
            logging.getLogger(__name__).debug("TRIVAE_TUI_QUERY_FAILED", exc_info=exc)
            self._finish_round_ui()
            return

        await self._present_result(round_id, result)
        self._finish_round_ui(trace_export=result.trace_id)

    async def _present_result(self, round_id: int, result: object) -> None:
        """补齐事件流没有覆盖的 QueryResult 层事实（对齐 plain 行为的子集）。"""
        from trivae.interfaces.cli import (
            _answer_limitations,
            _print_evidence_block,
            _print_source_block,
        )
        from trivae.query.evidence import AnswerArtifact, answer_source_summaries

        screen = self._chat_screen
        if screen is None:
            return
        conversation_id = getattr(result, "conversation_id", None)
        if isinstance(conversation_id, str):
            self._conversation_id = conversation_id
        successful = bool(getattr(result, "is_successful", False))
        final_answer = getattr(result, "final_answer", None)
        artifact = getattr(result, "answer_artifact", None)

        if successful and isinstance(artifact, AnswerArtifact):
            sources = answer_source_summaries(artifact)
            self._last_sources = sources
            self._last_result = result
        elif not successful:
            self._reset_conversation_state()

        if successful and not screen.round_has_answer(round_id) and isinstance(final_answer, str) and final_answer:
            screen.mount_answer_fallback(round_id, final_answer)
        if not successful and not self._engine.round_has_error(round_id):
            message = self._result_failure_message(result)
            await self._post_changes(
                self._engine.finalize_failed(round_id, title="查询失败", error_code=None, message=message)
            )
            return

        evidence_lines: list[str] = []
        if successful and isinstance(artifact, AnswerArtifact):
            _print_evidence_block(artifact, self._last_sources, output_fn=evidence_lines.append)
        source_lines: list[str] = []
        if successful and self._last_sources:
            _print_source_block(self._last_sources, output_fn=source_lines.append, verbose=self._verbose)
        combined: list[str] = []
        combined.extend(source_lines)
        combined.extend(evidence_lines)
        if combined:
            screen.append_collapsible_note(f"来源与证据 · {len(combined)} 行", combined)
        limitations = (
            _answer_limitations(artifact)
            if successful and isinstance(artifact, AnswerArtifact)
            else ()
        )
        notes: list[str] = []
        if limitations:
            notes.append(f"Note: answer limitations — {'; '.join(limitations)}")
        if getattr(result, "is_degraded", False):
            notes.append("Note: answer validation was degraded; inspect the trace diagnostics.")
        if notes:
            screen.append_note_lines(notes)

    @staticmethod
    def _result_failure_message(result: object) -> str:
        finalization_error = getattr(result, "finalization_error", None)
        if finalization_error is not None:
            return str(getattr(finalization_error, "message", finalization_error))
        runtime_result = getattr(result, "runtime_result", None)
        runtime_error = getattr(runtime_result, "error", None) if runtime_result is not None else None
        if runtime_error is not None:
            return str(getattr(runtime_error, "message", runtime_error))
        termination = getattr(result, "termination", "unknown")
        return f"query did not complete: {termination}"

    def _finish_round_ui(self, *, trace_export: str | None = None) -> None:
        """统一收尾：折叠过程组、导出 trace log、恢复输入焦点。"""

        collapse = self._engine.drain_pending_collapse()
        screen = self._chat_screen
        changes: tuple[TuiChange, ...] = (collapse,) if collapse is not None else ()
        trace_line: list[str] = []
        if trace_export is not None:
            try:
                exported = self._application.export_trace_log(trace_export)
                trace_line.append(f"[trace: {trace_export}]")
                trace_line.append(f"[log: {exported}]")
            except Exception as exc:  # noqa: BLE001 - plain CLI 相同：日志失败不影响答案展示
                trace_line.append(f"[trace: {trace_export}]")
                trace_line.append(f"[trace log unavailable: {exc}]")
        if screen is None:
            return
        if changes:
            screen.post_message(StreamChanges(changes))
        if trace_line:
            screen.append_note_lines(trace_line)
        screen.set_running(False)
        self._active_worker = None
        self._active_round_id = None

    async def _post_changes(self, changes: tuple[TuiChange, ...]) -> None:
        if not changes or self._chat_screen is None:
            return
        await self._chat_screen.on_stream_changes(StreamChanges(changes))

    # ---------- slash commands ----------

    async def execute_command(self, text: str) -> list[str]:
        """与 plain CLI 保持同一语义的交互命令子集。"""

        from trivae.feedback.contracts import FeedbackError
        from trivae.interfaces.cli import (
            _print_chat_commands,
            _print_feedback,
            _print_history,
            _print_readiness,
            _print_scope,
            _print_source_detail,
            _scope_name_from_sessions,
        )

        command, _, argument = text.partition(" ")
        if command in {"/exit", "/quit"}:
            # 先让调用方渲染 Bye.，再由输入回路延迟退出；同步 exit 会让 screen 在挂载前 detach。
            self._exit_requested = True
            return ["Bye."]
        if command == "/help":
            help_lines: list[str] = []
            _print_chat_commands(output_fn=help_lines.append)
            return help_lines
        if command == "/new":
            self._reset_conversation_state()
            return ["Started a new conversation."]
        if command == "/chats":
            self._reset_conversation_state()
            if self.screen_stack and isinstance(self.screen_stack[-1], ChatScreen):
                self.pop_screen()
                self._chat_screen = None
                self.push_picker_again()
            return []
        if self._scope is None:
            return ["先选择一个群聊。"]
        if command == "/scope":
            scope_lines: list[str] = []
            _print_scope(self._scope, self._selected_name or "", self._conversation_id, output_fn=scope_lines.append)
            return scope_lines
        if command == "/status":
            status_lines: list[str] = []
            readiness_reader = getattr(self._application, "readiness", None)
            if callable(readiness_reader):
                _print_readiness(readiness_reader(), output_fn=status_lines.append)
            else:
                status_lines.append("Status is unavailable from this application.")
            _print_scope(
                self._scope,
                self._selected_name or "",
                self._conversation_id,
                output_fn=lambda line: status_lines.append(line),
            )
            return status_lines
        if command == "/history":
            history_lines: list[str] = []
            summaries = self._list_conversations()
            if summaries is None:
                return ["History unavailable."]
            _print_history(summaries, sessions=self._sessions, output_fn=history_lines.append)
            return history_lines
        if command == "/resume":
            parts = argument.split()
            if len(parts) != 1 or not parts[0].isdigit():
                return ["Usage: /resume n"]
            summaries = self._list_conversations()
            if summaries is None:
                return ["History unavailable."]
            resume_index = int(parts[0])
            if resume_index < 1 or resume_index > len(summaries):
                return ["Conversation number is not available."]
            summary = summaries[resume_index - 1]
            resumed = self._resume_conversation(summary)
            if resumed is None:
                return ["Conversation cannot be resumed."]
            scope, conversation_id = resumed
            self._scope = scope
            self._conversation_id = conversation_id
            self._last_sources = ()
            name = _scope_name_from_sessions(scope, self._sessions)
            return [f"Resumed: {summary.title}", f"Scope: {name}", "Started a new conversation context."]
        if command in {"/good", "/bad"}:
            note = argument.strip() or ""
            target = self._feedback_target()
            if target is None:
                return ["Feedback is available after a completed answer."]
            try:
                self._application.save_feedback(
                    conversation_id=target[0],
                    trace_id=target[1],
                    run_id=target[2],
                    scope=self._scope,
                    rating="good" if command == "/good" else "bad",
                    note=note or None,
                )
            except FeedbackError as exc:
                return [f"Feedback was not saved: {exc}"]
            return ["Feedback saved."]
        if command == "/feedback":
            feedback_target = self._feedback_target()
            if feedback_target is None:
                return ["Feedback is available after a completed answer."]
            try:
                record = self._application.read_feedback(feedback_target[0], feedback_target[1])
            except FeedbackError as exc:
                return [f"Feedback unavailable: {exc}"]
            feedback_lines: list[str] = []
            _print_feedback(record, output_fn=feedback_lines.append)
            return feedback_lines
        if command == "/source":
            parts = argument.split()
            if len(parts) != 1 or not parts[0].isdigit():
                return ["Usage: /source n"]
            source_index = int(parts[0])
            selected_source = next(
                (summary for summary in self._last_sources if summary.index == source_index),
                None,
            )
            if selected_source is None:
                return ["Source number is not available from the last answer."]
            source_lines_out: list[str] = []
            _print_source_detail(
                selected_source,
                application=self._application,
                scope=self._scope,
                output_fn=source_lines_out.append,
                verbose=self._verbose,
            )
            return source_lines_out
        return [f"Unknown command: {command}; /help 查看可用命令"]

    def push_picker_again(self) -> None:
        names = [session.name for session in self._sessions]
        picker = PickerScreen(names, self._readiness_summary)
        self.push_screen(picker, callback=self._handle_picker_selection)

    # ---------- small state helpers ----------

    def _list_conversations(self) -> tuple | None:
        from trivae.conversation.contracts import ConversationError

        try:
            return self._application.list_conversations()
        except ConversationError:
            return None

    def _resume_conversation(self, summary: object) -> tuple[ExecutionScope, str] | None:
        from trivae.conversation.contracts import ConversationError

        try:
            resumed = self._application.resume_conversation(summary.conversation_id)  # type: ignore[attr-defined]
        except ConversationError:
            return None
        if resumed.scope is None:
            return None
        return resumed.scope, resumed.conversation_id

    def _feedback_target(self) -> tuple[str, str, str] | None:
        result = self._last_result
        if result is None or not getattr(result, "is_successful", False):
            return None
        conversation_id = getattr(result, "conversation_id", None)
        trace_id = getattr(result, "trace_id", None)
        runtime_result = getattr(result, "runtime_result", None)
        run_id = getattr(runtime_result, "run_id", None) if runtime_result is not None else None
        if conversation_id is None or trace_id is None or run_id is None:
            return None
        return conversation_id, trace_id, run_id

    # ---------- global actions ----------

    def action_interrupt_or_quit(self) -> None:
        """run 活跃时中断当前 run；空闲时退出应用。"""

        if self._active_worker is not None and self._active_worker.is_running:
            self._active_worker.cancel()
            return
        self.exit()
