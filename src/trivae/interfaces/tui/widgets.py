"""TUI block 的 Textual widget 投影。

widget 只渲染 TuiBlock 快照并回传用户交互；
开合状态的权威值保存在 projection engine。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import monotonic

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Collapsible, Markdown, Static

from trivae.interfaces.tui.models import ProcessGroupSummary, TuiBlock, metric_chips

# collapsed 行与展开详情的边界；防止长正文撑坏布局。
_MAX_DETAIL_ITEMS = 20
_MAX_DETAIL_FIELD_CHARS = 800

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

__all__ = [
    "AnswerBlock",
    "BlockToggleRequest",
    "ProcessGroupWidget",
    "ProcessRow",
    "format_duration_ms",
    "render_plan_detail",
    "render_summary_line",
    "render_tool_detail",
]


@dataclass(frozen=True)
class BlockToggleRequest:
    """用户切换某个 block 开合的 UI 请求。"""

    block_id: str
    expanded: bool


def format_duration_ms(duration_ms: float | None) -> str:
    """稳定的时长显示：<10s 显示一位小数秒，其余取整秒。"""

    if duration_ms is None:
        return ""
    seconds = duration_ms / 1000.0
    if seconds < 10:
        return f"{seconds:.1f}s"
    return f"{round(seconds)}s"


def render_summary_line(block: TuiBlock) -> Text:
    """三段式 Task Row：status glyph · display name · metric chips · duration。"""

    line = Text()
    step_prefix = f"{block.step_number}. " if block.step_number is not None and block.kind != "route" else ""
    if block.status == "failed":
        line.append("✗ ", style="bold red")
        line.append(f"{step_prefix}{block.title}", style="red")
    elif block.status == "running":
        line.append(f"{_spinner_frame()} ", style="bold cyan")
        line.append(block.title, style="cyan")
    else:
        symbol = "✓" if block.status == "completed" else "•"
        glyph_style = "green" if block.status == "completed" else "yellow"
        line.append(f"{symbol} ", style=glyph_style)
        line.append(
            f"{step_prefix}{block.title}",
            style="dim" if block.kind == "route" else "",
        )

    for chip in metric_chips(block.metrics):
        warning = chip.startswith("⚠")
        line.append(f"  {chip}", style="yellow" if warning else "dim")
    duration = format_duration_ms(block.duration_ms)
    if duration:
        line.append(f"  {duration}", style="dim")
    if block.status == "failed":
        # collapsed 行显示 code 保证失败可见；展开态显示完整 code+message。
        if block.expanded:
            detail = _error_detail_text(block.error_code, block.error_message)
            if detail:
                line.append(f"\n  {detail}", style="red")
        else:
            line.append(f"  {block.error_code or 'failed'}", style="red")
    return line


def render_tool_detail(block: TuiBlock) -> Text | None:
    """L2 详情：参数与结果摘要分区，含完整性警告；不 dump 长正文。"""

    arguments = _mapping_lines("参数", block.arguments)
    results = _mapping_lines("结果摘要", block.result_summary)
    warnings = []
    metrics = block.metrics or {}
    if bool(metrics.get("partial")):
        omitted = metrics.get("omitted_messages") or metrics.get("omitted_hit_messages")
        suffix = f"；省略 {omitted} 条" if isinstance(omitted, int) and not isinstance(omitted, bool) else ""
        warnings.append(f"⚠ 结果已部分完成{suffix}")
    if bool(metrics.get("truncated")):
        warnings.append("⚠ 结果已截断")
    sections = [section for section in (arguments, results) if section is not None]
    if not sections and not warnings:
        return None
    output = Text()
    for index, section in enumerate(sections):
        if index:
            output.append("\n")
        output.append(section)
    for warning in warnings:
        if output.plain:
            output.append("\n")
        output.append(f"  {warning}", style="yellow")
    return output


def render_plan_detail(block: TuiBlock) -> Text | None:
    """Plan 展开内容：编号步骤列表与成功标准。"""

    plan = block.result_summary or {}
    lines: list[str] = []
    steps = plan.get("steps")
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        for index, step in enumerate(steps, start=1):
            goal = step.get("goal") if isinstance(step, Mapping) else step
            if goal not in (None, ""):
                lines.append(f"  {index}. {_bounded_single_line(goal, 240)}")
    criteria = plan.get("success_criteria")
    if criteria not in (None, "", (), []):
        lines.append("")
        lines.append(f"  完成标准: {_bounded_single_line(criteria, 400)}")
    if not lines:
        return None
    return Text("\n".join(lines))


def _error_detail_text(error_code: str | None, error_message: str | None) -> str:
    parts: list[str] = []
    if error_code:
        parts.append(error_code)
    if error_message:
        parts.append(_bounded_single_line(error_message, 300))
    return " · ".join(parts)


def _mapping_lines(header: str, mapping: Mapping[str, object] | None) -> Text | None:
    """把参数/结果 dict 渲染为缩进的 key: value 行；条目与字符数双重限幅。"""

    if not mapping:
        return None
    items = list(mapping.items())
    meaningful = [item for item in items if item[1] not in (None, "", (), [], {})]
    if not meaningful:
        return None
    output = Text(f"  {header}\n", style="bold")
    for key, value in meaningful[:_MAX_DETAIL_ITEMS]:
        output.append(f"  {key}: ")
        output.append(_bounded_value(value, _MAX_DETAIL_FIELD_CHARS))
        output.append("\n")
    if len(meaningful) > _MAX_DETAIL_ITEMS:
        output.append(f"  … 其余 {len(meaningful) - _MAX_DETAIL_ITEMS} 项已省略\n", style="dim")
    return output


def _spinner_frame() -> str:
    index = int(monotonic() * 5) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[index]


def _bounded_single_line(value: object, max_chars: int) -> str:
    rendered = str(value).replace("\n", "\\n")
    return rendered if len(rendered) <= max_chars else f"{rendered[:max_chars - 1]}…"


def _bounded_value(value: object, max_chars: int) -> Text:
    """保留换行的多行值投影；JSON/URL/长中文都按字符预算截断。"""

    if isinstance(value, str):
        rendered = value if len(value) <= max_chars else f"{value[:max_chars]}…"
        return Text(rendered)
    if isinstance(value, Mapping):
        inner = ", ".join(
            f"{key}={_bounded_single_line(item, max(80, max_chars // 4))}"
            for key, item in list(value.items())[:12]
        )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        inner = ", ".join(_bounded_single_line(item, max(80, max_chars // 4)) for item in list(value)[:12])
    else:
        inner = _bounded_single_line(value, max_chars)
    return Text(_bounded_single_line(inner, max_chars))


class ProcessRow(Static, can_focus=True):
    """thinking/tool/route/retrieval/plan/error 共用的可聚焦 row。

    渲染完全来自 TuiBlock 快照；开合请求以 Message 上抛，
    由 controller 经 engine 确认后回写新快照。
    """

    BINDINGS = [
        Binding("enter,space", "toggle_expand", "展开/收起", show=False),
    ]

    class Toggled(Message):
        """用户请求切换某个 block 的展开状态。"""

        def __init__(self, process_row: "ProcessRow", block_id: str, expanded: bool) -> None:
            super().__init__()
            self.process_row = process_row
            self.block_id = block_id
            self.expanded = expanded

    def __init__(self, block: TuiBlock) -> None:
        super().__init__(classes=f"process-row kind-{block.kind} status-{block.status}")
        self._block = block

    @property
    def block(self) -> TuiBlock:
        return self._block

    def update_block(self, block: TuiBlock) -> None:
        """应用 engine 确认后的新快照并重绘。"""

        self._block = block
        self.set_classes(f"process-row kind-{block.kind} status-{block.status}")
        self.refresh()

    def render(self) -> Text:
        line = render_summary_line(self._block)
        if not self._block.expanded:
            return line
        detail = self._detail()
        if detail is None:
            return line
        joined = Text("\n")
        joined.append(line)
        joined.append("\n")
        joined.append(detail)
        return joined

    def action_toggle_expand(self) -> None:
        if not self.expandable:
            return
        self.post_message(self.Toggled(self, self._block.block_id, not self._block.expanded))

    async def _on_click(self, event: events.Click) -> None:
        """鼠标点击与 Enter/Space 语义一致。"""

        event.stop()
        if not self.expandable:
            return
        self.post_message(self.Toggled(self, self._block.block_id, not self._block.expanded))

    @property
    def expandable(self) -> bool:
        if self._block.kind in {"thinking", "route"}:
            # 没有 public summary 内容就不制造假详情。
            return False
        if self._block.kind == "tool":
            return bool(
                self._block.arguments
                or self._block.result_summary
                or any(chip.startswith("⚠") for chip in metric_chips(self._block.metrics))
            )
        if self._block.kind == "plan":
            return render_plan_detail(self._block) is not None
        return False

    def _detail(self) -> Text | None:
        if self._block.kind == "tool":
            return render_tool_detail(self._block)
        if self._block.kind == "plan":
            return render_plan_detail(self._block)
        return None


class AnswerBlock(Vertical):
    """最终回答区域：标题 + 分隔线 + Markdown 正文，永远展开。"""

    DEFAULT_CSS = """
    AnswerBlock {
        padding: 0;
        margin-top: 1;
    }
    AnswerBlock > .answer-title {
        color: $accent;
        text-style: bold;
    }
    """

    def __init__(self, block: TuiBlock) -> None:
        super().__init__(classes="answer-block")
        self._text = block.streaming_text or ""

    def compose(self) -> ComposeResult:
        yield Static("回答", classes="answer-title")
        yield Markdown(self._text, classes="answer-body")

    @property
    def answer_text(self) -> str:
        return self._text

    async def update_text(self, text: str) -> None:
        """整体替换正文（append 与 authoritative replace 共用同一入口）。

        compose 尚未完成时只登记文本；compose 会以最新 _text 构造 Markdown。
        """

        self._text = text
        if not self.children:
            return
        body = self.query_one(".answer-body", Markdown)
        await body.update(text)


class ProcessGroupWidget(Collapsible):
    """本轮结束后过程 blocks 的折叠分组。"""

    DEFAULT_CSS = """
    ProcessGroupWidget {
        margin-top: 1;
        background: $surface;
    }
    """

    def __init__(self, group: ProcessGroupSummary) -> None:
        duration = format_duration_ms(group.total_duration_ms)
        title_parts = [f"执行过程 · {group.step_count} 步"]
        if duration:
            title_parts.append(duration)
        super().__init__(
            *[ProcessRow(block) for block in group.blocks],
            title=" · ".join(title_parts),
            collapsed=not group.default_expanded,
        )
