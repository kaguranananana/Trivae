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
    error_code: str | None = None
    error_message: str | None = None
    # answer 专用；thinking 文本按仓库约定不进入 UI state。
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
        self._next_error_number = 0
        self._active: TuiRound | None = None
        self._finished: dict[int, TuiRound] = {}

    @property
    def active_round_id(self) -> int | None:
        return None if self._active is None else self._active.round_id

    def finished_round_ids(self) -> tuple[int, ...]:
        """已完成（含折叠后）round 的只读 ID 序列。"""

        return tuple(self._finished)

    def begin_round(self, query_text: str) -> tuple[int, TuiChange]:
        """提交输入时开启一轮新的问答。"""

        self._next_round_id += 1
        round_id = self._next_round_id
        self._next_step_number = 0
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
        changes = self._emit_error_row(
            title=title,
            error_code=error_code,
            error_message=message or "本轮执行已被用户中断。",
        )
        self._mark_terminal(failure=True)
        return changes

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
        changes = self._emit_error_row(
            title=title,
            error_code=error_code,
            error_message=message,
        )
        self._mark_terminal(failure=True)
        return changes

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

    def _apply_thinking_delta(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """thinking 不渲染 reasoning 文本；只维护一个真实时长 row。"""

        assert self._active is not None
        existing = self._active.find_block("thinking")
        if existing is not None:
            return ()
        return self._emit_created(
            block_id="thinking",
            kind="thinking",
            status="running",
            title="正在思考",
            started_monotonic=self._clock(),
        )

    def _apply_thinking_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        assert self._active is not None
        existing = self._active.find_block("thinking")
        if existing is None:
            return ()
        updated = replace(
            existing,
            status="completed",
            title="已思考",
            duration_ms=self._elapsed_ms(existing.started_monotonic),
        )
        self._replace_block(updated)
        return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated),)

    def _apply_tool_started(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """以 tool_call_id 建立 identity；同 tool 多次调用互不影响。"""

        self._next_step_number += 1
        return self._emit_created(
            block_id=f"tool:{event.tool_call_id}",
            kind="tool",
            status="running",
            title=tool_display_name(event.tool_name),
            started_monotonic=self._clock(),
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
            return self._emit_created(
                block_id=block_id,
                kind="tool",
                status="completed",
                title=tool_display_name(event.tool_name),
                duration_ms=event.duration_ms,
                metrics=dict(event.result_summary or {}),
                result_summary=dict(event.result_summary or {}),
                step_number=self._next_step_number,
            )
        failed = event.type == "tool.failed"
        expanded = True if failed else existing.manually_expanded
        updated = replace(
            existing,
            status="aborted" if failed and existing.status == "aborted" else "failed" if failed else "completed",
            duration_ms=event.duration_ms,
            expanded=expanded,
            error_code=event.error_code,
            error_message=event.error_message,
        )
        self._replace_block(updated)
        return (TuiChange(action="block_updated", round_id=self._active.round_id, block=updated),)

    def _apply_retrieval_started(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """retrieval 开始不单独建行；运行 spinner 由宿主 tool row 表达。"""

        return ()

    def _apply_retrieval_completed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        """deterministic 聚合：结果并入唯一 running tool row，避免重复 UI。"""

        assert self._active is not None
        summary = dict(event.result_summary or {})
        host = self._running_tool_block()
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
        self._active.terminal = True
        return ()

    def _apply_query_failed(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        changes = self._emit_error_row(
            title="查询失败",
            error_code=event.error_code,
            error_message=event.error_message or "查询未完成；请检查 Trace 诊断。",
        )
        self._mark_terminal(failure=True)
        return changes

    def _apply_query_aborted(self, event: QueryStreamEvent) -> tuple[TuiChange, ...]:
        changes = self._emit_error_row(
            title="已中断",
            error_code=event.error_code,
            error_message=event.error_message or "本轮执行已被中断。",
        )
        self._mark_terminal(failure=True)
        return changes

    # ---------- internals ----------

    def _running_tool_block(self) -> TuiBlock | None:
        assert self._active is not None
        return next(
            (block for block in reversed(self._active.blocks) if block.kind == "tool" and block.status == "running"),
            None,
        )

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
