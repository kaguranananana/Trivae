"""QueryStreamEvent 到 TUI block state 的纯逻辑投影层。

本模块是接口无关的 reducer：只消费既有 QueryStreamEvent 事实，
输出最小 state 变化；不允许 import Textual 或猜测 Agent 业务阶段。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from trivae.query.streaming import QueryStreamEvent

BlockKind = Literal["route", "thinking", "plan", "tool", "retrieval", "answer", "error"]
BlockStatus = Literal["running", "completed", "failed", "aborted"]

ChangeAction = Literal[
    "round_started",
    "block_created",
    "block_updated",
    "answer_appended",
    "answer_finalized",
    "round_collapsed",
]

_PROCESS_BLOCK_KINDS: frozenset[str] = frozenset({"route", "thinking", "plan", "tool", "retrieval"})
# widget/app 层使用的公开只读视图。
PROCESS_BLOCK_KINDS = frozenset(_PROCESS_BLOCK_KINDS)

TOOL_DISPLAY_NAMES = {
    "search_messages": "搜索消息",
    "lexical_search": "关键词检索",
    "semantic_search": "语义检索",
    "get_message_context": "获取消息上下文",
    "find_members": "查找成员",
    "get_schema": "查看数据结构",
    "execute_sql": "结构化查询",
}

_METRIC_CHIP_FORMATS = (
    ("candidate_count", "{value} hits"),
    ("returned_messages", "{value} msgs"),
    ("expanded_count", "+{value} ctx"),
    ("total_hits", "total {value}"),
)


def tool_display_name(tool_name: str | None) -> str:
    """工具 display name；未知工具名原样展示，不伪造更友好的名称。"""

    if tool_name is None:
        return "未知工具"
    return TOOL_DISPLAY_NAMES.get(tool_name, tool_name)


def metric_chips(metrics: Mapping[str, object]) -> tuple[str, ...]:
    """从合并后的 result facts 生成 collapsed 行的紧凑 metric chips。"""

    chips: list[str] = []
    for key, template in _METRIC_CHIP_FORMATS:
        value = metrics.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            chips.append(template.format(value=value))
    if bool(metrics.get("partial")):
        chips.append("⚠ partial")
    if bool(metrics.get("truncated")):
        chips.append("⚠ truncated")
    return tuple(chips)


@dataclass(frozen=True)
class TuiBlock:
    """单个可见 block 的完整 UI state 快照。"""

    block_id: str
    kind: BlockKind
    status: BlockStatus
    title: str
    expanded: bool = False
    manually_expanded: bool = False
    # running block 用于 live elapsed 的单调时钟起点。
    started_monotonic: float | None = None
    duration_ms: float | None = None
    step_number: int | None = None
    # collapsed 行第三段的可量化事实（retrieval 合并与 partial/truncated 标记）。
    metrics: Mapping[str, object] = field(default_factory=dict)
    arguments: Mapping[str, object] | None = None
    result_summary: Mapping[str, object] | None = None
    # result_detail 是 UI-safe 有界正文，与 collapsed 行统计完全分离。
    result_detail: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    # answer 与 public-summary thinking 共用；hidden reasoning 永不进入此字段。
    streaming_text: str | None = None


@dataclass(frozen=True)
class ProcessGroupSummary:
    """本轮结束后过程 blocks 的折叠分组快照。"""

    step_count: int
    total_duration_ms: float | None
    default_expanded: bool
    blocks: tuple[TuiBlock, ...]


@dataclass(frozen=True)
class TuiChange:
    """一次 apply 产生的最小 state 变化；widget 层据此做增量更新。"""

    action: ChangeAction
    round_id: int
    block: TuiBlock | None = None
    appended_text: str | None = None
    group: ProcessGroupSummary | None = None


@dataclass
class TuiRound:
    """一轮问答的有序 block state 与汇总事实。"""

    round_id: int
    query_text: str
    blocks: list[TuiBlock] = field(default_factory=list)
    usage: dict[str, int | float] = field(default_factory=dict)
    terminal: bool = False
    # 查询以 failed/aborted 终结时，折叠组应默认展开方便用户检查。
    failure_terminal: bool = False
    group: ProcessGroupSummary | None = None

    def find_block(self, block_id: str) -> TuiBlock | None:
        return next((block for block in self.blocks if block.block_id == block_id), None)


class TuiProjectionEngine:
    """QueryStreamEvent → TuiChange 的确定性 reducer。

    所有 UI 事实都来自事件本身；engine 不推断 provider 状态，
    也不引入新的事件总线。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._next_round_id = 0
        self._next_step_number = 0
        self._next_thinking_number = 0
        self._next_error_number = 0
        self._active: TuiRound | None = None
        self._finished: dict[int, TuiRound] = {}

    @property
    def active_round_id(self) -> int | None:
        return None if self._active is None else self._active.round_id

    def finished_round_ids(self) -> tuple[int, ...]:
        """已完成（含折叠后）round 的只读 ID 序列。"""

        return tuple(self._finished)

    def export_transcript(self) -> str:
        """把会话中所有轮次的 UI 事实投影为纯文本，供复制/存档。

        只使用已存在的 block 快照，不重新查询任何数据。
        """

        rounds = [*self._finished.values()]
        if self._active is not None:
            rounds.append(self._active)
        symbols = {"completed": "✓", "failed": "✗", "aborted": "✗", "running": "•"}
        lines: list[str] = []
        for round_state in sorted(rounds, key=lambda item: item.round_id):
            lines.append(f"You > {round_state.query_text}")
            process_blocks = (
                round_state.group.blocks
                if round_state.group is not None
                else [block for block in round_state.blocks if block.kind in _PROCESS_BLOCK_KINDS]
            )
            outer_blocks = [block for block in round_state.blocks if block.kind not in _PROCESS_BLOCK_KINDS]
            for block in (*process_blocks, *outer_blocks):
                step_prefix = f"{block.step_number}. " if block.step_number is not None and block.kind != "route" else ""
                duration = f" · {format_seconds(block.duration_ms)}" if block.duration_ms is not None else ""
                lines.append(f"{symbols[block.status]} {step_prefix}{block.title}{duration}")
                for key, value in (block.arguments or {}).items():
                    if value not in (None, "", (), [], {}):
                        lines.append(f"    {key}: {_compact_value(value)}")
                for key, value in (block.result_summary or {}).items():
                    if value in (None, "", (), [], {}):
                        continue
                    lines.append(f"    {key}: {_compact_value(value)}")
                for key in ("partial", "truncated"):
                    if bool(block.metrics.get(key)):
                        lines.append(f"    ⚠ {key}")
                if block.error_code:
                    message = f": {block.error_message}" if block.error_message else ""
                    lines.append(f"    错误: {block.error_code}{message}")
                text = (block.streaming_text or "").strip()
                if text:
                    for line in text.splitlines():
                        lines.append(f"  {line}" if line else "")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def begin_round(self, query_text: str) -> tuple[int, TuiChange]:
        """提交输入时开启一轮新的问答。"""

        self._next_round_id += 1
        round_id = self._next_round_id
        self._next_step_number = 0
        self._next_thinking_number = 0
        self._active = TuiRound(round_id=round_id, query_text=query_text)
        return round_id, TuiChange(action="round_started", round_id=round_id)

    def apply(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """消费一个流事件并返回零或多个 state 变化；轮外事件被显式忽略。"""

        if self._active is None or self._active.terminal:
            return ()
        handler_name = {
            "route.completed": self._apply_route,
            "plan.completed": self._apply_plan_completed,
            "plan.failed": self._apply_plan_failed,
            "thinking.started": self._apply_thinking_started,
            "thinking.delta": self._apply_thinking_delta,
            "thinking.completed": self._apply_thinking_completed,
            "tool.started": self._apply_tool_started,
            "tool.completed": self._apply_tool_terminal,
            "tool.failed": self._apply_tool_terminal,
            "retrieval.started": self._apply_retrieval_started,
            "retrieval.completed": self._apply_retrieval_completed,
            "retrieval.failed": self._apply_retrieval_failed,
            "answer.delta": self._apply_answer_delta,
            "answer.completed": self._apply_answer_completed,
            "usage.updated": self._apply_usage_updated,
            "query.completed": self._apply_query_completed,
            "query.failed": self._apply_query_failed,
            "query.aborted": self._apply_query_aborted,
            "query.started": lambda event: (),
        }.get(event.type)
        if handler_name is None:
            return ()
        return handler_name(event)

    def set_manual_expanded(self, round_id: int, block_id: str, expanded: bool) -> TuiBlock | None:
        """记录用户的开合动作；后续自动策略不得覆盖手动选择。

        对 running 轮与已折叠轮（含 group 内快照）都生效。
        """

        target = self._round_container(round_id)
        if target is None:
            return None
        updated = self._update_block_everywhere(target, block_id, lambda b: replace(b, expanded=expanded, manually_expanded=True))
        return updated

    def _round_container(self, round_id: int) -> TuiRound | None:
        if self._active is not None and self._active.round_id == round_id:
            return self._active
        return self._finished.get(round_id)

    def _update_block_everywhere(
        self,
        target: TuiRound,
        block_id: str,
        mutate: Callable[[TuiBlock], TuiBlock],
    ) -> TuiBlock | None:
        """在轮内的主列表与折叠分组里更新同一个 block；返回新快照。"""

        for index, block in enumerate(target.blocks):
            if block.block_id == block_id:
                mutated = mutate(block)
                target.blocks[index] = mutated
                return mutated
        if target.group is not None:
            frozen_blocks = target.group.blocks
            for index, block in enumerate(frozen_blocks):
                if block.block_id == block_id:
                    mutated = mutate(block)
                    replaced_group = replace(target.group, blocks=(*frozen_blocks[:index], mutated, *frozen_blocks[index + 1 :]))
                    target.group = replaced_group
                    return mutated
        return None

    def finalize_interrupted(
        self,
        round_id: int,
        *,
        title: str = "已中断",
        error_code: str | None = "CTRL_C",
        message: str | None = None,
    ) -> tuple[TuiChange, ...]:
        """控制器层取消（Ctrl+C / worker cancel）的确定性收尾。"""

        if not self._round_is_active(round_id):
            return ()
        closed = self._close_running_process_blocks()
        changes = self._emit_error_row(
            title=title,
            error_code=error_code,
            error_message=message or "本轮执行已被用户中断。",
        )
        self._mark_terminal(failure=True)
        return (*closed, *changes)

    def finalize_failed(
        self,
        round_id: int,
        *,
        title: str = "查询失败",
        error_code: str | None = None,
        message: str | None = None,
    ) -> tuple[TuiChange, ...]:
        """控制器层捕获到分类异常时的确定性收尾。"""

        if not self._round_is_active(round_id):
            return ()
        closed = self._close_running_process_blocks()
        changes = self._emit_error_row(
            title=title,
            error_code=error_code,
            error_message=message,
        )
        self._mark_terminal(failure=True)
        return (*closed, *changes)

    def drain_pending_collapse(self) -> TuiChange | None:
        """terminal 轮次待消费的折叠变化；无 pending 时返回 None。"""

        if self._active is None or not self._active.terminal or self._active.group is not None:
            return None
        return self.collapse_finished_round(self._active.round_id)

    def round_has_error(self, round_id: int) -> bool:
        """报告该轮是否已有 error row（query.failed 事件路径）。"""

        if self._active is None or self._active.round_id != round_id:
            return False
        return any(block.kind == "error" for block in self._active.blocks)

    def collapse_finished_round(self, round_id: int) -> TuiChange | None:
        """把已完成轮次的过程 blocks 冻结为单个分组；answer/error 保持在外。"""

        target = self._active if self._active is not None and self._active.round_id == round_id else None
        if target is None or target.group is not None:
            return None
        process_blocks = tuple(
            replace(block, expanded=_frozen_expanded(block)) for block in target.blocks if block.kind in _PROCESS_BLOCK_KINDS
        )
        has_failure = any(block.status in {"failed", "aborted"} for block in process_blocks) or target.failure_terminal
        group = ProcessGroupSummary(
            step_count=len(process_blocks),
            total_duration_ms=_sum_duration(process_blocks),
            default_expanded=has_failure or not target.blocks,
            blocks=process_blocks,
        )
        target.group = group
        target.blocks = [block for block in target.blocks if block.kind not in _PROCESS_BLOCK_KINDS]
        self._finished[round_id] = target
        self._active = None
        return TuiChange(action="round_collapsed", round_id=round_id, group=group)

    def blocks_for_debug(self, round_id: int) -> tuple[TuiBlock, ...]:
        """round 的只读 block 快照；供测试与调试，不暴露内部 list。"""

        if self._active is not None and self._active.round_id == round_id:
            return tuple(self._active.blocks)
        finished = self._finished.get(round_id)
        if finished is not None:
            return tuple(finished.blocks)
        return ()

    # ---------- event handlers ----------

    def _apply_route(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """Router 的真实决定投影为低调的单行 meta row。"""

        route = {
            "planned_execution": "planned",
            "standard_execution": "standard",
        }.get(event.route or "", event.route or "unknown")
        return self._emit_created(
            kind="route",
            status="completed",
            title=f"路由 · {route}",
        )

    def _apply_plan_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        plan = event.plan or {}
        steps = plan.get("steps")
        count = len(steps) if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)) else 0
        suffix = f" · {count} 步" if count else ""
        return self._emit_created(
            kind="plan",
            status="completed",
            title=f"分析计划{suffix}",
            result_summary=plan,
        )

    def _apply_plan_failed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        return self._emit_error_row(title="计划失败", error_code=event.error_code, error_message=event.error_message)

    def _apply_thinking_started(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """为每个真实模型回合创建独立 Thinking 段，即使没有公开摘要文本。"""

        assert self._active is not None
        running = self._running_thinking_block()
        if running is not None:
            return ()
        self._next_thinking_number += 1
        return self._emit_created(
            block_id=f"thinking:{self._next_thinking_number}",
            kind="thinking",
            status="running",
            title="正在思考",
            expanded=True,
            started_monotonic=self._clock(),
        )

    def _apply_thinking_delta(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """只有 provider/runtime 明确标记 public_summary 的摘要才允许展示。

        无标记的 reasoning 是私密 CoT，绝不进入 UI state。
        """

        assert self._active is not None
        if event.thinking_visibility != "public_summary":
            return ()
        existing = self._running_thinking_block()
        if existing is None:
            created_changes = self._apply_thinking_started(event)
            existing = self._running_thinking_block()
            assert existing is not None
        else:
            created_changes = ()
        merged = replace(
            existing,
            streaming_text=(existing.streaming_text or "") + (event.content or ""),
        )
        self._replace_block(merged)
        updated = TuiChange(action="block_updated", round_id=self._active.round_id, block=merged)
        return (*created_changes, updated)

    def _apply_thinking_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        existing = self._running_thinking_block()
        if existing is None:
            return ()
        updated = replace(
            existing,
            status="completed",
            title="已思考",
            duration_ms=self._elapsed_ms(existing.started_monotonic),
            # 手动选择保留其真实开合值；未交互的完成段默认收起。
            expanded=existing.expanded if existing.manually_expanded else False,
        )
        self._replace_block(updated)
        return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated),)

    def _apply_tool_started(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """以 tool_call_id 建立 identity；同 tool 多次调用互不影响。"""

        assert self._active is not None
        block_id = f"tool:{event.tool_call_id}"
        existing = self._active.find_block(block_id)
        if existing is not None:
            # terminal/detail 可能先于 normalized start 到达；start 只补参数，不回退终态。
            updated = replace(
                existing,
                title=tool_display_name(event.tool_name),
                arguments=event.arguments if event.arguments is not None else existing.arguments,
            )
            self._replace_block(updated)
            return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated),)
        self._next_step_number += 1
        return self._emit_created(
            block_id=block_id,
            kind="tool",
            status="running",
            title=tool_display_name(event.tool_name),
            started_monotonic=self._clock(),
            expanded=True,
            arguments=event.arguments,
            step_number=self._next_step_number,
        )

    def _apply_tool_terminal(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        block_id = f"tool:{event.tool_call_id}"
        existing = self._active.find_block(block_id)
        if existing is None:
            # 缺 start 的完成事实仍应诚实出现，但不制造伪关联。
            self._next_step_number += 1
            failed = event.type == "tool.failed"
            return self._emit_created(
                block_id=block_id,
                kind="tool",
                status="failed" if failed else "completed",
                title=tool_display_name(event.tool_name),
                expanded=failed,
                duration_ms=event.duration_ms,
                metrics=dict(event.result_summary or {}),
                result_summary=dict(event.result_summary or {}),
                result_detail=event.result_detail,
                error_code=event.error_code,
                error_message=event.error_message,
                step_number=self._next_step_number,
            )
        failed = event.type == "tool.failed"
        expanded = True if failed else existing.expanded if existing.manually_expanded else False
        merged_summary = {**(existing.result_summary or {}), **(event.result_summary or {})}
        updated = replace(
            existing,
            status="aborted" if failed and existing.status == "aborted" else "failed" if failed else "completed",
            duration_ms=event.duration_ms if event.duration_ms is not None else existing.duration_ms,
            expanded=expanded,
            metrics={**existing.metrics, **(event.result_summary or {})},
            result_summary=merged_summary or None,
            error_code=event.error_code,
            error_message=event.error_message,
            result_detail=event.result_detail or existing.result_detail,
        )
        self._replace_block(updated)
        return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated),)

    def _apply_retrieval_started(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """retrieval 开始不单独建行；运行 spinner 由宿主 tool row 表达。"""

        return ()

    def _apply_retrieval_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """deterministic 聚合：只并入 `parent_operation_id` 对应的 tool row；无宿主则独立成行。"""

        assert self._active is not None
        summary = dict(event.result_summary or {})
        host = self._active.find_block(f"tool:{event.tool_call_id}") if event.tool_call_id is not None else None
        if host is not None:
            merged_metrics = {**host.metrics, **summary}
            updated_host = replace(host, metrics=merged_metrics, result_summary={**(host.result_summary or {}), **summary})
            self._replace_block(updated_host)
            return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated_host),)
        return self._emit_created(
            kind="retrieval",
            status="completed",
            title="检索",
            duration_ms=event.duration_ms,
            metrics=summary,
            result_summary=summary,
        )

    def _apply_retrieval_failed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        return self._emit_error_row(
            title="检索失败", error_code=event.error_code, error_message=event.error_message
        )

    def _apply_answer_delta(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        existing = self._active.find_block("answer")
        if existing is None:
            created = TuiBlock(
                block_id="answer",
                kind="answer",
                status="running",
                title="回答",
                expanded=True,
                streaming_text=event.content,
            )
            self._active.blocks.append(created)
            return (
                TuiChange(action="block_created", round_id=self._active.round_id, block=created),
                TuiChange(action="answer_appended", round_id=self._active.round_id, block=created),
            )
        merged = replace(existing, streaming_text=(existing.streaming_text or "") + (event.content or ""))
        self._replace_block(merged)
        return (
            TuiChange(
                action="answer_appended",
                round_id=self._active.round_id,
                block=merged,
                appended_text=event.content,
            ),
        )

    def _apply_answer_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """authoritative answer 整体替换 preview，防 streaming/finalizer 漂移。"""

        assert self._active is not None
        existing = self._active.find_block("answer")
        text = event.content or ""
        if existing is None:
            finalized = TuiBlock(
                block_id="answer",
                kind="answer",
                status="completed",
                title="回答",
                expanded=True,
                streaming_text=text,
            )
            self._active.blocks.append(finalized)
            return (TuiChange(action="answer_finalized", round_id=self._active.round_id, block=finalized),)
        finalized = replace(existing, status="completed", streaming_text=text, expanded=True)
        self._replace_block(finalized)
        return (TuiChange(action="answer_finalized", round_id=self._active.round_id, block=finalized),)

    def _apply_usage_updated(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        if event.usage:
            self._active.usage.update(event.usage)
        return ()

    def _apply_query_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        closed = self._close_running_process_blocks()
        self._active.terminal = True
        return closed

    def _apply_query_failed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        closed = self._close_running_process_blocks()
        changes = self._emit_error_row(
            title="查询失败",
            error_code=event.error_code,
            error_message=event.error_message or "查询未完成；请检查 Trace 诊断。",
        )
        self._mark_terminal(failure=True)
        return (*closed, *changes)

    def _apply_query_aborted(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        closed = self._close_running_process_blocks()
        changes = self._emit_error_row(
            title="已中断",
            error_code=event.error_code,
            error_message=event.error_message or "本轮执行已被中断。",
        )
        self._mark_terminal(failure=True)
        return (*closed, *changes)

    # ---------- internals ----------

    def _running_thinking_block(self) -> TuiBlock | None:
        """只返回当前开放段；已完成段永不被后续 delta 复用。"""

        assert self._active is not None
        return next(
            (block for block in reversed(self._active.blocks) if block.kind == "thinking" and block.status == "running"),
            None,
        )

    def _close_running_process_blocks(self) -> tuple[TuiChange, ...]:
        """终止边界把未完成过程标为 aborted，保证界面不残留 spinner。"""

        assert self._active is not None
        changes: list[TuiChange] = []
        for block in tuple(self._active.blocks):
            if block.kind not in _PROCESS_BLOCK_KINDS or block.status != "running":
                continue
            updated = replace(
                block,
                status="aborted",
                title="已思考" if block.kind == "thinking" else block.title,
                duration_ms=self._elapsed_ms(block.started_monotonic),
                expanded=block.expanded if block.manually_expanded else False,
            )
            self._replace_block(updated)
            changes.append(TuiChange(action="block_updated", round_id=self._active.round_id, block=updated))
        return tuple(changes)

    def _mark_terminal(self, *, failure: bool = False) -> None:
        assert self._active is not None
        self._active.terminal = True
        if failure:
            self._active.failure_terminal = True

    def _round_is_active(self, round_id: int) -> bool:
        return self._active is not None and self._active.round_id == round_id and not self._active.terminal

    def _emit_error_row(
        self,
        *,
        title: str,
        error_code: str | None,
        error_message: str | None,
    ) -> tuple[TuiChange, ...]:
        """错误行始终唯一 ID 且自动展开。"""

        self._next_error_number += 1
        created = TuiBlock(
            block_id=f"error:{self._next_error_number}",
            kind="error",
            status="failed",
            title=title,
            expanded=True,
            error_code=error_code,
            error_message=error_message,
        )
        assert self._active is not None
        self._active.blocks.append(created)
        return (TuiChange(action="block_created", round_id=self._active.round_id, block=created),)

    def _emit_created(
        self,
        *,
        kind: BlockKind,
        status: BlockStatus,
        title: str,
        block_id: str | None = None,
        **kwargs: object,
    ) -> tuple[TuiChange, ...]:
        assert self._active is not None
        resolved_id = block_id if block_id is not None else kind
        if self._active.find_block(resolved_id) is not None:
            return ()
        created = TuiBlock(block_id=resolved_id, kind=kind, status=status, title=title, **kwargs)  # type: ignore[arg-type]
        self._active.blocks.append(created)
        return (TuiChange(action="block_created", round_id=self._active.round_id, block=created),)

    def _replace_block(self, updated: TuiBlock) -> None:
        assert self._active is not None
        self._active.blocks = [
            updated if block.block_id == updated.block_id else block for block in self._active.blocks
        ]

    def _elapsed_ms(self, started: float | None) -> float | None:
        if started is None:
            return None
        return max(0.0, (self._clock() - started) * 1000.0)


def _sum_duration(blocks: Sequence[TuiBlock]) -> float | None:
    values = [block.duration_ms for block in blocks if block.duration_ms is not None]
    if not values:
        return None
    return sum(values)


def _frozen_expanded(block: TuiBlock) -> bool:
    """折叠冻结时的展开策略：手动选择优先；失败块自动展开。"""

    if block.manually_expanded:
        return block.expanded
    return block.status == "failed"


def format_seconds(duration_ms: float | None) -> str:
    if duration_ms is None:
        return ""
    seconds = duration_ms / 1000.0
    return f"{seconds:.1f}s" if seconds < 10 else f"{round(seconds)}s"


def _compact_value(value: object) -> str:
    rendered = str(value).replace("\n", "\\n")
    return rendered if len(rendered) <= 200 else f"{rendered[:199]}…"
