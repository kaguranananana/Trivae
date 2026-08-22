"""Retrieval Core 的自动 bounded context expansion。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

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
