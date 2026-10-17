"""Canonical message streaming 到 semantic derived index 的 rebuild 编排。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import chain
from time import perf_counter

from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunker,
    is_semantic_void,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingProvider,
    SemanticBuildStats,
    SemanticChunk,
    SemanticEmbeddingError,
    SemanticIndexIdentity,
    SemanticIndexStale,
    SemanticIndexStatus,
    SemanticIndexStorageError,
    SemanticIndexStore,
    SemanticMessage,
)
from trivae.retrieval.structured import CanonicalReadRepository, MessageQuery, ScopeFilters

_LONG_INPUT_ISOLATION_CHARS = 2048


@dataclass
class _PendingParent:
    """尚未全部写入的 Parent 进度；只保存计数，不缓存 canonical 正文。"""

    message_count: int
    remaining_chunk_count: int
    forwarded: bool


@dataclass(frozen=True)
class _PendingBuildStats:
    """一次有界 pending flush 的 embedding/write 与进度事实。"""

    processed_message_count: int
    processed_forwarded_message_count: int
    embedding_count: int
    reused_chunk_count: int
    embedding_batch_count: int
    embedding_elapsed_ms: float
    index_write_elapsed_ms: float


class SemanticIndexBuilder:
    """按 bounded parent 处理 canonical stream，并显式记录 rebuild 终态。"""

    def __init__(
        self,
        repository: CanonicalReadRepository,
        store: SemanticIndexStore,
        provider: EmbeddingProvider,
        *,
        database_identity: str,
        chunker: SemanticChunker | None = None,
        read_batch_size: int = 256,
    ) -> None:
        if isinstance(read_batch_size, bool) or not isinstance(read_batch_size, int) or read_batch_size <= 0:
            raise ValueError("semantic read_batch_size must be positive")
        self.repository = repository
        self.store = store
        self.provider = provider
        self.database_identity = database_identity
        self.chunker = chunker or SemanticChunker(DEFAULT_SEMANTIC_CHUNK_CONFIG, SEMANTIC_CHUNKER_VERSION)
        self.read_batch_size = read_batch_size
        # 增量路径只在首次真正缺少向量时加载模型，空变更不触发加载。
        self._incremental_model_loaded = False
        self._incremental_model_load_ms = 0.0

    @property
    def identity(self) -> SemanticIndexIdentity:
        """由 database、embedding 和完整 chunker config 组成可比较 identity。"""

        return SemanticIndexIdentity(
            database_identity=self.database_identity,
            embedding=self.provider.identity,
            chunker_version=self.chunker.version,
            chunker_config=self.chunker.config.to_dict(),
        )

    def update(self) -> SemanticBuildStats:
        """按持久变更位置重放安全段，并原子发布与全量同语义的新索引。"""

        started = perf_counter()
        state = self.store.state()
        revision = self.repository.canonical_revision()
        identity = self.identity
        canonical_count = self.repository.count_messages(MessageQuery(limit=1))
        same_identity = state is not None and state.identity.serialized == identity.serialized
        same_snapshot = same_identity and state is not None and state.canonical_revision == revision
        if same_snapshot and state is not None and state.status == "completed":
            # 提交成功但队列未确认时，直接报告既有发布事实，不解析转发树或加载模型。
            if state.canonical_message_count != canonical_count:
                raise SemanticIndexStale("canonical count changed without its revision")
            return self._unchanged_stats(started)
        if not same_identity or not self.store.supports_incremental():
            # 首建、模型/config 变更、旧输入凭据迁移和未完成全量构建保留原有入口。
            return self.rebuild(resume=bool(
                same_snapshot and state is not None and state.status != "completed" and self.store.has_replay_inputs()
            ))
        assert state is not None
        # 变更日志缺失不能靠猜测重用旧向量；由 repository 明确拒绝不受追踪的水位。
        ranges = self.repository.semantic_change_ranges(state.canonical_revision, self.chunker.config.parent_gap_seconds)
        forwarded_count = self.repository.count_forwarded_messages()
        self._incremental_model_loaded = False
        self._incremental_model_load_ms = 0.0
        processed = processed_forwarded = eligible = void = eligible_forwarded = void_forwarded = 0
        parent_count = affected_chunks = skipped = embeddings = batches = 0
        embedding_ms = write_ms = 0.0
        pending_chunks: list[SemanticChunk] = []
        pending_parents: deque[_PendingParent] = deque()
        # 旧向量先进入事务内临时复用池；任何异常或强停均回滚所有正式 rows。
        with self.store.incremental_transaction(
            identity, canonical_count, base_revision=state.canonical_revision,
            canonical_revision=revision, forwarded_message_count=forwarded_count,
        ):
            write_started = perf_counter()
            removed = self.store.prepare_incremental_ranges(ranges)
            write_ms += (perf_counter() - write_started) * 1000
            for session_id, first, last in ranges:
                # 范围端点由时间连通段定义且 inclusive；公共 scope 保持半开时间语义。
                scope = ScopeFilters(
                    session_ids=(session_id,), start_timestamp=first,
                    end_timestamp=None if last is None else last + 1,
                )
                # 每个范围单独关闭 Parent；段外时间 gap 保证不会与相邻范围拼接。
                parent: list[SemanticMessage] = []
                projections = chain(
                    self.repository.iter_semantic_messages(self.read_batch_size, scope=scope),
                    self.repository.iter_forwarded_messages(self.read_batch_size, scope=scope),
                )
                for projection in projections:
                    message = SemanticMessage.from_projection(projection)
                    is_void = is_semantic_void(message)
                    if message.forward is None:
                        eligible += int(not is_void)
                        void += int(is_void)
                    else:
                        eligible_forwarded += int(not is_void)
                        void_forwarded += int(is_void)
                    if parent and self.chunker.starts_new_parent(parent[-1], message, parent):
                        result = self.chunker.chunk_parent(parent)
                        parent_count += 1
                        affected_chunks += len(result.chunks)
                        skipped += result.skipped_void_chunks
                        pending_chunks.extend(result.chunks)
                        pending_parents.append(_PendingParent(len(parent), len(result.chunks), parent[0].forward is not None))
                        flushed = self._flush_pending(
                            pending_chunks, pending_parents, flush_all=False, resume=False, incremental=True,
                        )
                        processed += flushed.processed_message_count
                        processed_forwarded += flushed.processed_forwarded_message_count
                        embeddings += flushed.embedding_count
                        batches += flushed.embedding_batch_count
                        embedding_ms += flushed.embedding_elapsed_ms
                        write_ms += flushed.index_write_elapsed_ms
                        parent = []
                    parent.append(message)
                if parent:
                    result = self.chunker.chunk_parent(parent)
                    parent_count += 1
                    affected_chunks += len(result.chunks)
                    skipped += result.skipped_void_chunks
                    pending_chunks.extend(result.chunks)
                    pending_parents.append(_PendingParent(len(parent), len(result.chunks), parent[0].forward is not None))
                # 多个彼此隔离的变更段也共享有界批次，不能把每段尾 Parent 一直累积到全轮结束。
                flushed = self._flush_pending(
                    pending_chunks, pending_parents, flush_all=False, resume=False, incremental=True,
                )
                processed += flushed.processed_message_count
                processed_forwarded += flushed.processed_forwarded_message_count
                embeddings += flushed.embedding_count
                batches += flushed.embedding_batch_count
                embedding_ms += flushed.embedding_elapsed_ms
                write_ms += flushed.index_write_elapsed_ms
            flushed = self._flush_pending(
                pending_chunks, pending_parents, flush_all=True, resume=False, incremental=True,
            )
            processed += flushed.processed_message_count
            processed_forwarded += flushed.processed_forwarded_message_count
            embeddings += flushed.embedding_count
            batches += flushed.embedding_batch_count
            embedding_ms += flushed.embedding_elapsed_ms
            write_ms += flushed.index_write_elapsed_ms
            # 计数与完成状态和 vec0 rows 同事务提交，未处理的段沿用旧版已完成覆盖。
            if self.repository.canonical_revision() != revision:
                raise SemanticIndexStale("canonical messages changed during semantic incremental update")
            # 把最终落盘提交也计入写入耗时，避免仅记录事务内 SQL 而漏掉发布成本。
            publish_started = perf_counter()
            self.store.update_progress(canonical_count, indexed_forwarded_message_count=forwarded_count)
            self.store.finish("completed")
        write_ms += (perf_counter() - publish_started) * 1000
        published = self.store.state()
        assert published is not None
        return SemanticBuildStats(
            status="completed", canonical_message_count=canonical_count, indexed_message_count=canonical_count,
            eligible_message_count=eligible, semantic_void_message_count=void,
            parent_count=parent_count, chunk_count=published.chunk_count, skipped_void_chunks=skipped,
            embedding_count=embeddings, embedding_batch_size=self.provider.document_batch_size,
            embedding_batch_count=batches, model_load_elapsed_ms=self._incremental_model_load_ms,
            embedding_elapsed_ms=embedding_ms, index_write_elapsed_ms=write_ms,
            elapsed_ms=(perf_counter() - started) * 1000, index_size_bytes=self.store.size_bytes(), identity=identity,
            forwarded_message_count=forwarded_count, indexed_forwarded_message_count=forwarded_count,
            eligible_forwarded_message_count=eligible_forwarded, semantic_void_forwarded_message_count=void_forwarded,
            reused_chunk_count=published.chunk_count - embeddings, build_mode="incremental",
            affected_message_count=processed + processed_forwarded, affected_chunk_count=affected_chunks,
            removed_chunk_count=removed,
        )

    def _unchanged_stats(self, started: float) -> SemanticBuildStats:
        """空更新报告直接使用已提交覆盖水位，不扫描消息正文。"""

        state = self.store.state()
        assert state is not None
        return SemanticBuildStats(
            status="completed", canonical_message_count=state.canonical_message_count,
            indexed_message_count=state.indexed_message_count, eligible_message_count=0,
            semantic_void_message_count=0, parent_count=0, chunk_count=state.chunk_count,
            skipped_void_chunks=0, embedding_count=0, embedding_batch_size=self.provider.document_batch_size,
            embedding_batch_count=0, model_load_elapsed_ms=0, embedding_elapsed_ms=0, index_write_elapsed_ms=0,
            elapsed_ms=(perf_counter() - started) * 1000, index_size_bytes=self.store.size_bytes(), identity=self.identity,
            forwarded_message_count=state.forwarded_message_count,
            indexed_forwarded_message_count=state.indexed_forwarded_message_count,
            reused_chunk_count=state.chunk_count, build_mode="unchanged",
        )

    def rebuild(self, *, resume: bool = False) -> SemanticBuildStats:
        """显式重建或续建；续建只复用同一源快照与 identity 的完整持久块。"""

        started = perf_counter()
        identity = self.identity
        # 先捕获 revision，构建期间有写入时不能把混合快照宣布为完成。
        canonical_revision = self.repository.canonical_revision()
        canonical_count = self.repository.count_messages(MessageQuery(limit=1))
        forwarded_count = self.repository.count_forwarded_messages()
        saved_chunk_count = 0
        if resume:
            # 校验失败发生在 build try 之前，不能改写被拒绝索引的原始状态。
            saved_chunk_count = self.store.begin_resume(
                identity,
                canonical_count,
                canonical_revision=canonical_revision,
                forwarded_message_count=forwarded_count,
            )
        else:
            # 未显式续建时维持原来的全量重建行为。
            self.store.start_rebuild(
                identity,
                canonical_count,
                canonical_revision=canonical_revision,
                forwarded_message_count=forwarded_count,
            )
        processed = 0
        processed_forwarded = 0
        eligible_messages = 0
        semantic_void_messages = 0
        eligible_forwarded_messages = 0
        semantic_void_forwarded_messages = 0
        parent_count = 0
        chunk_count = 0
        skipped_void_chunks = 0
        embedding_batch_count = 0
        embedding_count = 0
        reused_chunk_count = 0
        embedding_elapsed_ms = 0.0
        index_write_elapsed_ms = 0.0
        model_load_elapsed_ms = 0.0
        parent: list[SemanticMessage] = []
        pending_chunks: list[SemanticChunk] = []
        pending_parents: deque[_PendingParent] = deque()
        try:
            # 模型加载在 building 状态内显式发生，失败时 derived state 会保留 provider-owned 终态。
            model_load_started = perf_counter()
            self.provider.preload()
            model_load_elapsed_ms = (perf_counter() - model_load_started) * 1000
            # 保持 canonical stream 不变，再处理独立 occurrence stream；两者共享唯一向量索引。
            projections = chain(
                self.repository.iter_semantic_messages(self.read_batch_size),
                self.repository.iter_forwarded_messages(self.read_batch_size),
            )
            for projection in projections:
                message = SemanticMessage.from_projection(projection)
                # 子消息计数独立保存，不能让群消息覆盖进度超过 canonical 总数。
                if message.forward is not None:
                    if is_semantic_void(message):
                        semantic_void_forwarded_messages += 1
                    else:
                        eligible_forwarded_messages += 1
                else:
                    if is_semantic_void(message):
                        semantic_void_messages += 1
                    else:
                        eligible_messages += 1
                if parent and self.chunker.starts_new_parent(parent[-1], message, parent):
                    parent_result = self.chunker.chunk_parent(parent)
                    parent_count += 1
                    chunk_count += len(parent_result.chunks)
                    skipped_void_chunks += parent_result.skipped_void_chunks
                    # 相邻 Parent 共用同一个有界队列，避免大量不足 batch_size 的模型调用。
                    pending_chunks.extend(parent_result.chunks)
                    pending_parents.append(
                        _PendingParent(
                            message_count=len(parent),
                            remaining_chunk_count=len(parent_result.chunks),
                            forwarded=parent[0].forward is not None,
                        )
                    )
                    pending_stats = self._flush_pending(
                        pending_chunks,
                        pending_parents,
                        flush_all=False,
                        resume=resume,
                    )
                    processed += pending_stats.processed_message_count
                    processed_forwarded += pending_stats.processed_forwarded_message_count
                    embedding_batch_count += pending_stats.embedding_batch_count
                    embedding_count += pending_stats.embedding_count
                    reused_chunk_count += pending_stats.reused_chunk_count
                    embedding_elapsed_ms += pending_stats.embedding_elapsed_ms
                    index_write_elapsed_ms += pending_stats.index_write_elapsed_ms
                    if pending_stats.processed_message_count or pending_stats.processed_forwarded_message_count:
                        self.store.update_progress(
                            processed,
                            indexed_forwarded_message_count=processed_forwarded,
                        )
                    parent = []
                parent.append(message)

            if parent:
                parent_result = self.chunker.chunk_parent(parent)
                parent_count += 1
                chunk_count += len(parent_result.chunks)
                skipped_void_chunks += parent_result.skipped_void_chunks
                pending_chunks.extend(parent_result.chunks)
                pending_parents.append(
                    _PendingParent(
                        message_count=len(parent),
                        remaining_chunk_count=len(parent_result.chunks),
                        forwarded=parent[0].forward is not None,
                    )
                )

            # 最后一批允许不足 batch_size；成功写入后再推进 canonical watermark。
            pending_stats = self._flush_pending(
                pending_chunks,
                pending_parents,
                flush_all=True,
                resume=resume,
            )
            processed += pending_stats.processed_message_count
            processed_forwarded += pending_stats.processed_forwarded_message_count
            embedding_batch_count += pending_stats.embedding_batch_count
            embedding_count += pending_stats.embedding_count
            reused_chunk_count += pending_stats.reused_chunk_count
            embedding_elapsed_ms += pending_stats.embedding_elapsed_ms
            index_write_elapsed_ms += pending_stats.index_write_elapsed_ms
            if pending_stats.processed_message_count or pending_stats.processed_forwarded_message_count:
                self.store.update_progress(processed, indexed_forwarded_message_count=processed_forwarded)

            if self.repository.canonical_revision() != canonical_revision:
                raise SemanticIndexStale("canonical messages changed during semantic rebuild; rebuild it again")
            if reused_chunk_count != saved_chunk_count:
                # 重放必须解释全部旧块，不能把无法恢复来源的旧向量混入 completed 索引。
                raise SemanticIndexStorageError(
                    "semantic resume replay did not cover saved chunks: "
                    f"expected {saved_chunk_count}, got {reused_chunk_count}"
                )
            complete = processed == canonical_count and processed_forwarded == forwarded_count
            status: SemanticIndexStatus = "completed" if complete else "partial"
            self.store.finish(status)
        except BaseException as exc:
            # Ctrl+C 也必须结束 building 状态；保留根因文本，再原样重新抛出中断/异常。
            self.store.finish("failed", f"{type(exc).__name__}: {exc}".rstrip(": "))
            raise

        return SemanticBuildStats(
            status=status,
            canonical_message_count=canonical_count,
            indexed_message_count=processed,
            eligible_message_count=eligible_messages,
            semantic_void_message_count=semantic_void_messages,
            parent_count=parent_count,
            chunk_count=chunk_count,
            skipped_void_chunks=skipped_void_chunks,
            embedding_count=embedding_count,
            embedding_batch_size=self.provider.document_batch_size,
            embedding_batch_count=embedding_batch_count,
            model_load_elapsed_ms=model_load_elapsed_ms,
            embedding_elapsed_ms=embedding_elapsed_ms,
            index_write_elapsed_ms=index_write_elapsed_ms,
            elapsed_ms=(perf_counter() - started) * 1000,
            index_size_bytes=self.store.size_bytes(),
            identity=identity,
            forwarded_message_count=forwarded_count,
            indexed_forwarded_message_count=processed_forwarded,
            eligible_forwarded_message_count=eligible_forwarded_messages,
            semantic_void_forwarded_message_count=semantic_void_forwarded_messages,
            reused_chunk_count=reused_chunk_count,
            build_mode="resume" if resume else "full",
        )

    def _flush_pending(
        self,
        chunks: list[SemanticChunk],
        parents: deque[_PendingParent],
        *,
        flush_all: bool,
        resume: bool,
        incremental: bool = False,
    ) -> _PendingBuildStats:
        """按 provider batch 上限写入跨 Parent chunks，并只提交已完整覆盖的 Parent 进度。"""

        processed_message_count, processed_forwarded_message_count = self._consume_completed_parents(parents)
        embedding_batch_count = 0
        embedding_count = 0
        reused_chunk_count = 0
        embedding_elapsed_ms = 0.0
        index_write_elapsed_ms = 0.0
        batch_size = self.provider.document_batch_size
        while chunks:
            long_offset = next(
                (
                    index
                    for index, chunk in enumerate(chunks)
                    if len(chunk.embedding_input) > _LONG_INPUT_ISOLATION_CHARS
                ),
                None,
            )
            if len(chunks) < batch_size and not flush_all and long_offset is None:
                break
            if long_offset == 0:
                # 长输入单独执行，避免其 padding 被放大到整个 batch 的 MPS activation。
                current_size = 1
            elif long_offset is not None:
                # 先按原顺序写完长输入之前的短 chunks，再由下一轮隔离长输入。
                current_size = min(batch_size, long_offset)
            else:
                current_size = min(batch_size, len(chunks))
            batch = tuple(chunks[:current_size])
            # 相同消息流重放出原有 Parent/Child 边界，不依赖可能滞后的 processed 水位。
            reused_ids = self.store.reusable_chunk_ids(batch) if resume else frozenset()
            # 逐字段验证后的旧块不再次调用模型，也不重复写入 metadata/vector。
            reused_vectors = self.store.reusable_vectors(batch) if incremental else {}
            missing = tuple(
                chunk for chunk in batch if chunk.chunk_id not in reused_ids and chunk.chunk_id not in reused_vectors
            )
            vectors: tuple[tuple[float, ...], ...] = ()
            if missing:
                if incremental and not self._incremental_model_loaded:
                    # 全文比较证明需要新向量后才加载 provider，void-only 变更无需加载。
                    load_started = perf_counter()
                    self.provider.preload()
                    self._incremental_model_load_ms = (perf_counter() - load_started) * 1000
                    self._incremental_model_loaded = True
                embedding_started = perf_counter()
                vectors = self.provider.embed_documents(tuple(chunk.embedding_input for chunk in missing))
                embedding_elapsed_ms += (perf_counter() - embedding_started) * 1000
                embedding_batch_count += 1
                embedding_count += len(missing)
                if len(vectors) != len(missing):
                    raise SemanticEmbeddingError(
                        f"embedding output count mismatch: expected {len(missing)}, got {len(vectors)}"
                    )
            # 增量重切后的 metadata 必须写入；输入不变时搬用旧 float32 vector，不调用模型。
            computed = {chunk.chunk_id: vector for chunk, vector in zip(missing, vectors, strict=True)}
            writable = tuple(
                (chunk, reused_vectors[chunk.chunk_id] if chunk.chunk_id in reused_vectors else computed[chunk.chunk_id])
                for chunk in batch if chunk.chunk_id not in reused_ids
            )
            if writable:
                write_started = perf_counter()
                self.store.insert_chunks(writable)
                index_write_elapsed_ms += (perf_counter() - write_started) * 1000
            reused_chunk_count += len(reused_ids) + len(reused_vectors)
            # 只有向量和 metadata 同事务成功后，才从 pending 队列消费对应范围。
            del chunks[:current_size]
            remaining = current_size
            while remaining:
                current_parent = parents[0]
                consumed = min(remaining, current_parent.remaining_chunk_count)
                current_parent.remaining_chunk_count -= consumed
                remaining -= consumed
                completed_native, completed_forwarded = self._consume_completed_parents(parents)
                processed_message_count += completed_native
                processed_forwarded_message_count += completed_forwarded

        if flush_all and (chunks or parents):
            raise SemanticEmbeddingError("semantic pending batches did not drain completely")
        return _PendingBuildStats(
            processed_message_count=processed_message_count,
            processed_forwarded_message_count=processed_forwarded_message_count,
            embedding_count=embedding_count,
            reused_chunk_count=reused_chunk_count,
            embedding_batch_count=embedding_batch_count,
            embedding_elapsed_ms=embedding_elapsed_ms,
            index_write_elapsed_ms=index_write_elapsed_ms,
        )

    @staticmethod
    def _consume_completed_parents(parents: deque[_PendingParent]) -> tuple[int, int]:
        """按原始顺序推进已无待写 chunk 的 Parent，包括 semantic-void-only Parent。"""

        processed = 0
        processed_forwarded = 0
        while parents and parents[0].remaining_chunk_count == 0:
            parent = parents.popleft()
            # 同一批向量可以跨容器合并写入，但进度必须按真实数据层分别推进。
            if parent.forwarded:
                processed_forwarded += parent.message_count
            else:
                processed += parent.message_count
        return processed, processed_forwarded
