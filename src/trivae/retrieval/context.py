"""Retrieval Core 的自动 bounded context expansion。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from trivae.retrieval.structured import MessageHit, MessageProjection, RetrievalError, message_sort_key


class ContextReadRepository(Protocol):
    """Context Expansion 只需要同 session 的窗口读取能力。"""

    def read_message_context(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """读取 anchor 周围的 canonical projection。"""

    def read_message_range(
        self,
        session_id: str,
        start_message_id: str,
        end_message_id: str,
        limit: int,
    ) -> tuple[MessageProjection, ...]:
        """读取同 session 的 bounded canonical range。"""


@dataclass(frozen=True)
class ContextRange:
    """语义 child 的 canonical range，永远不作为 citation source 本身暴露。"""

    session_id: str
    start_message_id: str
    end_message_id: str
    message_limit: int


@dataclass(frozen=True)
class ContextExpansionResult:
    """记录窗口合并后的结果与 bounded 状态。"""

    messages: tuple[MessageProjection, ...]
    partial: bool
    truncated: bool
    candidate_count: int


class ContextExpander:
    """合并 lexical hits 的同 session 局部窗口，并保护真实 hit。"""

    def __init__(self, repository: ContextReadRepository) -> None:
        self.repository = repository

    def expand(
        self,
        hits: tuple[MessageHit, ...],
        before: int,
        after: int,
        limit: int,
    ) -> ContextExpansionResult:
        """合并、去重、排序并 bounded trim；不把 context 当成新的检索 hit。"""

        if not hits:
            return ContextExpansionResult(messages=(), partial=False, truncated=False, candidate_count=0)

        messages_by_id: dict[str, MessageProjection] = {
            hit.message.internal_message_id: hit.message for hit in hits
        }
        hit_ids = set(messages_by_id)

        for hit in hits:
            if before == 0 and after == 0:
                continue
            window = self.repository.read_message_context(
                session_id=hit.message.session_id,
                internal_message_id=hit.message.internal_message_id,
                before=before,
                after=after,
            )
            for message in window:
                # session 是上下文边界；违反它表示 repository 主链路有 bug，必须显式暴露。
                if message.session_id != hit.message.session_id:
                    raise RetrievalError(
                        f"Context repository crossed session boundary for {hit.message.internal_message_id}"
                    )
                messages_by_id[message.internal_message_id] = message

        ordered = tuple(sorted(messages_by_id.values(), key=message_sort_key))
        hit_messages = tuple(message for message in ordered if message.internal_message_id in hit_ids)

        # 命中本身超过 bound 时，只保留确定性排序的前 bound 个真实 hit，并显式标记 partial。
        if len(hit_messages) > limit:
            selected = hit_messages[:limit]
            return ContextExpansionResult(
                messages=selected,
                partial=True,
                truncated=True,
                candidate_count=len(ordered),
            )

        if len(ordered) <= limit:
            return ContextExpansionResult(
                messages=ordered,
                partial=False,
                truncated=False,
                candidate_count=len(ordered),
            )

        # 先放入全部真实 hit，再从 context 中填充剩余空间，避免简单切片丢掉后面的命中。
        non_hit_messages = tuple(message for message in ordered if message.internal_message_id not in hit_ids)
        available_context = limit - len(hit_messages)
        selected = tuple(sorted((*hit_messages, *non_hit_messages[:available_context]), key=message_sort_key))
        return ContextExpansionResult(
            messages=selected,
            partial=False,
            truncated=True,
            candidate_count=len(ordered),
        )

    def expand_ranges(
        self,
        ranges: Sequence[ContextRange],
        before: int,
        after: int,
        limit: int,
    ) -> ContextExpansionResult:
        """恢复 semantic child ranges，再复用同一 bounded context 合并规则。"""

        if not ranges:
            return ContextExpansionResult(messages=(), partial=False, truncated=False, candidate_count=0)
        if before < 0 or after < 0 or limit <= 0:
            raise ValueError("context range expansion bounds must be non-negative and limit must be positive")

        messages_by_id: dict[str, MessageProjection] = {}
        for item in ranges:
            core = self.repository.read_message_range(
                session_id=item.session_id,
                start_message_id=item.start_message_id,
                end_message_id=item.end_message_id,
                limit=item.message_limit,
            )
            if not core:
                raise RetrievalError(
                    f"Semantic range returned no canonical messages: "
                    f"{item.session_id}/{item.start_message_id}:{item.end_message_id}"
                )
            if any(message.session_id != item.session_id for message in core):
                raise RetrievalError(f"Semantic range crossed session boundary: {item.session_id}")
            for message in core:
                messages_by_id[message.internal_message_id] = message

            # 只扩展 child 两端，避免对 child 内每条消息重复读取 context window。
            first = core[0]
            last = core[-1]
            if before:
                for message in self.repository.read_message_context(
                    item.session_id, first.internal_message_id, before, 0
                ):
                    if message.session_id != item.session_id:
                        raise RetrievalError(f"Semantic context crossed session boundary: {item.session_id}")
                    messages_by_id[message.internal_message_id] = message
            if after:
                for message in self.repository.read_message_context(
                    item.session_id, last.internal_message_id, 0, after
                ):
                    if message.session_id != item.session_id:
                        raise RetrievalError(f"Semantic context crossed session boundary: {item.session_id}")
                    messages_by_id[message.internal_message_id] = message

        ordered = tuple(sorted(messages_by_id.values(), key=message_sort_key))
        if len(ordered) <= limit:
            return ContextExpansionResult(
                messages=ordered,
                partial=False,
                truncated=False,
                candidate_count=len(ordered),
            )

        # 优先保留每个 range 的核心消息，context 超出预算时显式标记截断。
        core_ids: set[str] = set()
        for item in ranges:
            core = self.repository.read_message_range(
                item.session_id,
                item.start_message_id,
                item.end_message_id,
                item.message_limit,
            )
            core_ids.update(message.internal_message_id for message in core)
        core_messages = tuple(message for message in ordered if message.internal_message_id in core_ids)
        if len(core_messages) >= limit:
            selected = core_messages[:limit]
        else:
            context_messages = tuple(message for message in ordered if message.internal_message_id not in core_ids)
            selected = tuple(sorted((*core_messages, *context_messages[: limit - len(core_messages)]), key=message_sort_key))
        return ContextExpansionResult(
            messages=selected,
            partial=len(core_messages) > limit,
            truncated=True,
            candidate_count=len(ordered),
        )
