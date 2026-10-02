"""Retrieval Core 的自动 bounded context expansion。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, Sequence

from trivae.config.limits import MAX_AUTOMATIC_CONTEXT_SOURCE_HITS, MAX_STRUCTURED_RESULT_ITEMS
from trivae.retrieval.structured import (
    Coverage,
    MessageHit,
    MessageProjection,
    RetrievalError,
    RetrievalMetadata,
    ScopeFilters,
    message_sort_key,
)

# context expansion 的最终消息窗口保持独立的 structured transport bound；
# 它不是 lexical candidate pool、semantic Top-K 或 embedding 参数。
MAX_CONTEXT_EXPANSION_MESSAGES = MAX_STRUCTURED_RESULT_ITEMS


class ContextReadRepository(Protocol):
    """Context Expansion 只需要同 session 的窗口读取能力。"""

    def read_message_by_id(self, internal_message_id: str) -> MessageProjection | None:
        """按稳定 internal message ID 恢复一个 canonical projection。"""

    def read_message_context(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
    ) -> tuple[MessageProjection, ...]:
        """读取 anchor 周围的 canonical projection。"""

    def read_message_context_scoped(
        self,
        session_id: str,
        internal_message_id: str,
        before: int,
        after: int,
        scope: ScopeFilters,
    ) -> tuple[MessageProjection, ...]:
        """在 trusted scope 内读取 anchor 周围的 canonical projection。"""

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
    # 只记录 range/hit 核心消息；其余返回消息是可在 model projection 中省略的 context。
    primary_message_ids: tuple[str, ...] = ()
    # 记录自动读取邻居的 direct-hit 数量，便于 Trace 解释 expansion 成本与边界。
    context_source_hits: int = 0
    context_source_budget: int = MAX_AUTOMATIC_CONTEXT_SOURCE_HITS


@dataclass(frozen=True)
class MessageContextResult:
    """显式上下文 Tool 的 bounded 结果，不把上下文伪装成一次搜索命中。"""

    strategy: str
    message_id: str
    session_id: str
    messages: tuple[MessageProjection, ...]
    requested_before: int
    requested_after: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata

    def __post_init__(self) -> None:
        """固定 context strategy，避免调用方把其他 Retrieval 结果冒充上下文。"""

        if self.strategy != "context":
            raise ValueError("message context strategy must be context")
        if not self.message_id or not self.session_id:
            raise ValueError("message context identity must be non-empty")
        if self.requested_before < 0 or self.requested_after < 0:
            raise ValueError("message context bounds must be non-negative")

    def to_dict(self) -> dict[str, object]:
        """把 context 结果投影成 Tool Envelope 可安全序列化的普通值。"""

        return {
            "strategy": self.strategy,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "messages": [asdict(message) for message in self.messages],
            "requested_before": self.requested_before,
            "requested_after": self.requested_after,
            "returned_messages": len(self.messages),
            "coverage": {
                "status": self.coverage.status,
                "basis": self.coverage.basis,
            },
            "partial": self.partial,
            "truncated": self.truncated,
            "metadata": {
                "filters": dict(self.metadata.filters),
                "ordering": self.metadata.ordering,
                "latency_ms": self.metadata.latency_ms,
                "details": dict(self.metadata.details),
            },
        }


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
        *,
        scope: ScopeFilters | None = None,
    ) -> ContextExpansionResult:
        """合并、去重、排序并 bounded trim；不把 context 当成新的检索 hit。"""

        if not hits:
            return ContextExpansionResult(messages=(), partial=False, truncated=False, candidate_count=0)

        messages_by_id: dict[str, MessageProjection] = {
            hit.message.internal_message_id: hit.message for hit in hits
        }
        hit_ids = set(messages_by_id)

        # direct hit 已填满容量时，邻居不会进入结果，因此完全跳过无收益读取。
        source_hits = (
            ()
            if (before == 0 and after == 0) or len(hits) >= limit
            else hits[:MAX_AUTOMATIC_CONTEXT_SOURCE_HITS]
        )
        for hit in source_hits:
            if before == 0 and after == 0:
                continue
            if scope is None:
                # 既有 Search 路径继续使用原始 context reader，保持已验证的调用契约。
                window = self.repository.read_message_context(
                    session_id=hit.message.session_id,
                    internal_message_id=hit.message.internal_message_id,
                    before=before,
                    after=after,
                )
            else:
                # 显式 deepening 必须使用带 scope 的 reader，不能先读取越权消息再靠上层丢弃。
                scoped_reader = getattr(self.repository, "read_message_context_scoped", None)
                if not callable(scoped_reader):
                    raise RetrievalError("Context repository does not provide scoped context reads")
                window = scoped_reader(
                    session_id=hit.message.session_id,
                    internal_message_id=hit.message.internal_message_id,
                    before=before,
                    after=after,
                    scope=scope,
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
                primary_message_ids=tuple(message.internal_message_id for message in selected),
                context_source_hits=len(source_hits),
            )

        if len(ordered) <= limit:
            return ContextExpansionResult(
                messages=ordered,
                partial=False,
                # direct hit 已占满容量时，requested neighbor 被明确省略，保留 truncation 事实。
                truncated=bool((before or after) and not source_hits),
                candidate_count=len(ordered),
                primary_message_ids=tuple(message.internal_message_id for message in hit_messages),
                context_source_hits=len(source_hits),
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
            primary_message_ids=tuple(message.internal_message_id for message in hit_messages),
            context_source_hits=len(source_hits),
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
        if len(ranges) > MAX_AUTOMATIC_CONTEXT_SOURCE_HITS:
            raise RetrievalError(
                f"semantic context source hits must not exceed {MAX_AUTOMATIC_CONTEXT_SOURCE_HITS}"
            )

        messages_by_id: dict[str, MessageProjection] = {}
        # range core 与 before/after context 必须分开标记，供 Host 做 hit-preserving trim。
        core_ids: set[str] = set()
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
            core_ids.update(message.internal_message_id for message in core)
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
                primary_message_ids=tuple(message.internal_message_id for message in ordered if message.internal_message_id in core_ids),
                context_source_hits=len(ranges),
            )

        # 优先保留每个 range 的核心消息，context 超出预算时显式标记截断。
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
            primary_message_ids=tuple(message.internal_message_id for message in selected if message.internal_message_id in core_ids),
            context_source_hits=len(ranges),
        )
