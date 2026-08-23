"""Canonical message streaming 到 semantic derived index 的 rebuild 编排。"""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunker,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingProvider,
    SemanticBuildStats,
    SemanticEmbeddingError,
    SemanticIndexIdentity,
    SemanticIndexStatus,
    SemanticIndexStore,
    SemanticMessage,
)
from trivae.retrieval.structured import CanonicalReadRepository, MessageQuery


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

    @property
    def identity(self) -> SemanticIndexIdentity:
        """由 database、embedding 和完整 chunker config 组成可比较 identity。"""

        return SemanticIndexIdentity(
            database_identity=self.database_identity,
            embedding=self.provider.identity,
            chunker_version=self.chunker.version,
            chunker_config=self.chunker.config.to_dict(),
        )

    def rebuild(self) -> SemanticBuildStats:
        """重建整个 derived index；任何 provider/store 错误都会留下 failed 状态并继续抛出。"""

        started = perf_counter()
        identity = self.identity
        canonical_count = self.repository.count_messages(MessageQuery(limit=1))
        self.store.start_rebuild(identity, canonical_count)
        processed = 0
        chunk_count = 0
        skipped_void_chunks = 0
        parent: list[SemanticMessage] = []
        try:
            for projection in self.repository.iter_semantic_messages(self.read_batch_size):
                message = SemanticMessage.from_projection(projection)
                if parent and self.chunker.starts_new_parent(parent[-1], message, parent):
                    chunks, skipped = self._index_parent(parent)
                    chunk_count += chunks
                    skipped_void_chunks += skipped
                    processed += len(parent)
                    self.store.update_progress(processed)
                    parent = []
                parent.append(message)

            if parent:
                chunks, skipped = self._index_parent(parent)
                chunk_count += chunks
                skipped_void_chunks += skipped
                processed += len(parent)
                self.store.update_progress(processed)

            status: SemanticIndexStatus = "completed" if processed == canonical_count else "partial"
            self.store.finish(status)
        except Exception as exc:
            # 失败状态只写入异常类型，避免把 provider message/raw input 写入 derived metadata。
            self.store.finish("failed", f"{type(exc).__name__}")
            raise

        return SemanticBuildStats(
            status=status,
            canonical_message_count=canonical_count,
            indexed_message_count=processed,
            chunk_count=chunk_count,
            skipped_void_chunks=skipped_void_chunks,
            elapsed_ms=(perf_counter() - started) * 1000,
            identity=identity,
        )

    def _index_parent(self, parent: Sequence[SemanticMessage]) -> tuple[int, int]:
        """对单个 bounded parent 切 child、批量 embed，再原子写入 vector store。"""

        result = self.chunker.chunk_parent(parent)
        chunks = result.chunks
        for offset in range(0, len(chunks), self.provider.document_batch_size):
            batch = chunks[offset : offset + self.provider.document_batch_size]
            vectors = self.provider.embed_documents(tuple(chunk.embedding_input for chunk in batch))
            if len(vectors) != len(batch):
                raise SemanticEmbeddingError(
                    f"embedding output count mismatch: expected {len(batch)}, got {len(vectors)}"
                )
            self.store.insert_chunks(tuple(zip(batch, vectors, strict=True)))
        return len(chunks), result.skipped_void_chunks
