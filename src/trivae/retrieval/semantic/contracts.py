"""Semantic Retrieval 的跨层契约。

本模块只保存普通 Python 值和明确的错误类型，不加载模型、不打开数据库。
这样 Chunker、Embedding Provider、Vector Index、Capability 和 Evaluation 可以
使用同一份可追踪身份，而不会互相依赖具体基础设施。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Mapping, Protocol, Sequence

from trivae.retrieval.structured import Coverage, MessageProjection, RetrievalMetadata, ScopeFilters


class SemanticError(Exception):
    """Semantic Retrieval 能够向上层明确投影的错误基类。"""

    error_code = "SEMANTIC_ERROR"


class SemanticQueryError(SemanticError, ValueError):
    """Semantic query 或 index identity 字段不合法。"""

    error_code = "SEMANTIC_INVALID_QUERY"


class SemanticEmbeddingError(SemanticError):
    """Embedding provider 加载、调用或输出 shape 不满足 contract。"""

    error_code = "SEMANTIC_EMBEDDING_FAILED"


class SemanticIndexStorageError(SemanticError):
    """Semantic derived vector store 不可读写。"""

    error_code = "SEMANTIC_INDEX_STORAGE"


class SemanticIndexUnavailable(SemanticError):
    """Semantic index 尚未建立、没有可用向量或正在建立。"""

    error_code = "SEMANTIC_INDEX_NOT_READY"


class SemanticIndexStale(SemanticError):
    """Semantic index identity 与当前 provider/chunker/canonical facts 不一致。"""

    error_code = "SEMANTIC_INDEX_STALE"


class SemanticContextRecoveryError(SemanticError):
    """Semantic hit 无法从 canonical range 恢复成消息 projection。"""

    error_code = "SEMANTIC_CONTEXT_RECOVERY"


EmbeddingPooling = Literal["last_token", "mean", "cls"]
SemanticIndexStatus = Literal["building", "completed", "partial", "failed"]
SemanticIndexAvailability = Literal["missing", "building", "completed", "partial", "failed", "stale"]


def _non_empty_text(value: object, name: str) -> str:
    """统一拒绝空 identity 字段，避免 identity 发生隐式漂移。"""

    if not isinstance(value, str) or not value.strip():
        raise SemanticQueryError(f"{name} must be a non-empty string")
    return value.strip()


def _json_safe(value: object, name: str, depth: int = 0) -> None:
    """只允许 identity 进入可持久化的 bounded JSON 普通值。"""

    if depth > 8:
        raise SemanticQueryError(f"{name} exceeds identity nesting bound")
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str) or not key:
                raise SemanticQueryError(f"{name} contains an invalid field name")
            _json_safe(nested, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, (tuple, list)):
        for index, nested in enumerate(value):
            _json_safe(nested, f"{name}[{index}]", depth + 1)
        return
    raise SemanticQueryError(f"{name} contains unsupported value {type(value).__name__}")


def _reject_secret_key(key: str, path: str) -> None:
    """身份禁止出现凭据字段；这是 contract 要求，不是通用输入清洗。"""

    normalized = key.lower().replace("-", "_")
    secret_fragments = (
        "api_key",
        "access_token",
        "authorization",
        "client_secret",
        "secret",
        "password",
        "private_key",
        "credential",
    )
    if any(fragment in normalized for fragment in secret_fragments):
        raise SemanticQueryError(f"{path} must not contain secrets")


@dataclass(frozen=True)
class EmbeddingModelIdentity:
    """Embedding model 的可追踪、无密钥身份。"""

    provider: str
    model: str
    dimension: int
    pooling: EmbeddingPooling
    normalized: bool
    query_instruction: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _non_empty_text(self.provider, "embedding provider"))
        object.__setattr__(self, "model", _non_empty_text(self.model, "embedding model"))
        object.__setattr__(self, "query_instruction", _non_empty_text(self.query_instruction, "query instruction"))
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int) or self.dimension <= 0:
            raise SemanticQueryError("embedding dimension must be a positive integer")
        if self.pooling not in ("last_token", "mean", "cls"):
            raise SemanticQueryError("embedding pooling is invalid")
        if not isinstance(self.normalized, bool):
            raise SemanticQueryError("embedding normalized must be a boolean")

    def to_dict(self) -> dict[str, object]:
        """返回不含 provider secret 的普通 identity projection。"""

        return {
            "provider": self.provider,
            "model": self.model,
            "dimension": self.dimension,
            "pooling": self.pooling,
            "normalized": self.normalized,
            "query_instruction": self.query_instruction,
        }


@dataclass(frozen=True)
class SemanticIndexIdentity:
    """决定一个 derived semantic index 是否可复用的完整身份。"""

    database_identity: str
    embedding: EmbeddingModelIdentity
    chunker_version: str
    chunker_config: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "database_identity", _non_empty_text(self.database_identity, "database identity"))
        object.__setattr__(self, "chunker_version", _non_empty_text(self.chunker_version, "chunker version"))
        if not isinstance(self.embedding, EmbeddingModelIdentity):
            raise SemanticQueryError("embedding identity is invalid")
        if not isinstance(self.chunker_config, Mapping) or not self.chunker_config:
            raise SemanticQueryError("chunker config must be a non-empty mapping")
        for key, value in self.chunker_config.items():
            if not isinstance(key, str) or not key:
                raise SemanticQueryError("chunker config contains an invalid key")
            _reject_secret_key(key, "chunker config")
            _json_safe(value, f"chunker config.{key}")

    def to_dict(self) -> dict[str, object]:
        """固定字段顺序生成可存储、可比较的 identity。"""

        return {
            "database_identity": self.database_identity,
            "embedding": self.embedding.to_dict(),
            "chunker_version": self.chunker_version,
            "chunker_config": {key: self.chunker_config[key] for key in sorted(self.chunker_config)},
        }

    @property
    def serialized(self) -> str:
        """使用 canonical JSON 作为 identity；不使用 hash，符合仓库工程约束。"""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, value: object) -> SemanticIndexIdentity:
        """从 derived metadata 恢复 identity，并复用同一领域校验。"""

        if not isinstance(value, Mapping):
            raise SemanticQueryError("stored semantic identity must be an object")
        embedding = value.get("embedding")
        if not isinstance(embedding, Mapping):
            raise SemanticQueryError("stored semantic identity embedding is invalid")
        database_identity = value.get("database_identity")
        chunker_version = value.get("chunker_version")
        chunker_config = value.get("chunker_config")
        provider = embedding.get("provider")
        model = embedding.get("model")
        dimension = embedding.get("dimension")
        pooling = embedding.get("pooling")
        normalized = embedding.get("normalized")
        query_instruction = embedding.get("query_instruction")
        if not isinstance(database_identity, str) or not isinstance(chunker_version, str):
            raise SemanticQueryError("stored semantic identity text fields are invalid")
        if not isinstance(chunker_config, Mapping):
            raise SemanticQueryError("stored semantic identity chunker config is invalid")
        if not isinstance(provider, str) or not isinstance(model, str) or not isinstance(query_instruction, str):
            raise SemanticQueryError("stored semantic identity embedding text fields are invalid")
        if not isinstance(dimension, int) or isinstance(dimension, bool):
            raise SemanticQueryError("stored semantic identity embedding dimension is invalid")
        if pooling not in ("last_token", "mean", "cls"):
            raise SemanticQueryError("stored semantic identity embedding pooling is invalid")
        if not isinstance(normalized, bool):
            raise SemanticQueryError("stored semantic identity embedding normalized is invalid")
        return cls(
            database_identity=database_identity,
            embedding=EmbeddingModelIdentity(
                provider=provider,
                model=model,
                dimension=dimension,
                pooling=pooling,
                normalized=normalized,
                query_instruction=query_instruction,
            ),
            chunker_version=chunker_version,
            chunker_config=chunker_config,
        )


@dataclass(frozen=True)
class SemanticMessage:
    """Chunker 使用的最小 canonical projection，不携带 SQLite row。"""

    internal_message_id: str
    session_id: str
    session_display: str
    sender_name: str
    sender_user_id: str | None
    timestamp: int
    message_type: str
    normalized_content: str
    system: bool
    recalled: bool

    @classmethod
    def from_projection(cls, message: MessageProjection) -> SemanticMessage:
        """从既有 Retrieval projection 转换，确保 Chunker 不接触 raw payload。"""

        return cls(
            internal_message_id=message.internal_message_id,
            session_id=message.session_id,
            session_display=message.session_display,
            sender_name=message.sender_name or message.sender_user_id or "unknown",
            sender_user_id=message.sender_user_id,
            timestamp=message.timestamp,
            message_type=message.message_type,
            normalized_content=message.normalized_content,
            system=message.system,
            recalled=message.recalled,
        )


@dataclass(frozen=True)
class SemanticChunk:
    """一个 Small Child 的范围与 embedding input；正文仍只作为 build-time 派生值。"""

    chunk_id: str
    parent_id: str
    session_id: str
    parent_start_message_id: str
    parent_end_message_id: str
    start_message_id: str
    end_message_id: str
    start_timestamp: int
    end_timestamp: int
    message_count: int
    effective_chars: int
    embedding_input: str


@dataclass(frozen=True)
class SemanticChunkResult:
    """一次 parent/child 切分的确定性摘要。"""

    chunker_version: str
    chunker_config: Mapping[str, object]
    chunks: tuple[SemanticChunk, ...]
    skipped_void_chunks: int
    parent_count: int


@dataclass(frozen=True)
class SemanticIndexState:
    """Derived index 的持久化状态，不把 queue 状态当作事实来源。"""

    identity: SemanticIndexIdentity
    status: SemanticIndexStatus
    canonical_message_count: int
    indexed_message_count: int
    chunk_count: int
    last_error: str | None
    updated_at: int

    def to_dict(self) -> dict[str, object]:
        """投影持久化 state，供 status CLI/Trace 使用，不暴露向量正文。"""

        return {
            "identity": self.identity.to_dict(),
            "status": self.status,
            "canonical_message_count": self.canonical_message_count,
            "indexed_message_count": self.indexed_message_count,
            "chunk_count": self.chunk_count,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SemanticIndexStatusReport:
    """把 missing/stale 与底层 build 状态统一投影为可运维结果。"""

    status: SemanticIndexAvailability
    configured_identity: SemanticIndexIdentity
    persisted_identity: SemanticIndexIdentity | None
    canonical_message_count: int
    indexed_message_count: int | None
    chunk_count: int | None
    last_error: str | None
    updated_at: int | None

    @classmethod
    def from_state(
        cls,
        configured_identity: SemanticIndexIdentity,
        state: SemanticIndexState | None,
        canonical_message_count: int,
    ) -> SemanticIndexStatusReport:
        """由 Application 同时比较 provider identity 与 canonical watermark。"""

        if state is None:
            return cls(
                status="missing",
                configured_identity=configured_identity,
                persisted_identity=None,
                canonical_message_count=canonical_message_count,
                indexed_message_count=None,
                chunk_count=None,
                last_error=None,
                updated_at=None,
            )
        status: SemanticIndexAvailability = state.status
        if state.identity.serialized != configured_identity.serialized:
            status = "stale"
        elif state.canonical_message_count != canonical_message_count:
            status = "stale"
        return cls(
            status=status,
            configured_identity=configured_identity,
            persisted_identity=state.identity,
            canonical_message_count=canonical_message_count,
            indexed_message_count=state.indexed_message_count,
            chunk_count=state.chunk_count,
            last_error=state.last_error,
            updated_at=state.updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        """返回 secret-free status；不包含消息正文或向量数据。"""

        return {
            "status": self.status,
            "configured_identity": self.configured_identity.to_dict(),
            "persisted_identity": None
            if self.persisted_identity is None
            else self.persisted_identity.to_dict(),
            "canonical_message_count": self.canonical_message_count,
            "indexed_message_count": self.indexed_message_count,
            "chunk_count": self.chunk_count,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class SemanticBuildStats:
    """一次 build/rebuild 的可验证结果。"""

    status: SemanticIndexStatus
    canonical_message_count: int
    indexed_message_count: int
    eligible_message_count: int
    semantic_void_message_count: int
    parent_count: int
    chunk_count: int
    skipped_void_chunks: int
    embedding_count: int
    embedding_batch_size: int
    embedding_batch_count: int
    model_load_elapsed_ms: float
    embedding_elapsed_ms: float
    index_write_elapsed_ms: float
    elapsed_ms: float
    index_size_bytes: int
    identity: SemanticIndexIdentity

    def to_dict(self) -> dict[str, object]:
        """返回 rebuild 结果的 bounded JSON projection。"""

        return {
            "status": self.status,
            "canonical_message_count": self.canonical_message_count,
            "indexed_message_count": self.indexed_message_count,
            "eligible_message_count": self.eligible_message_count,
            "semantic_void_message_count": self.semantic_void_message_count,
            "parent_count": self.parent_count,
            "chunk_count": self.chunk_count,
            "skipped_void_chunks": self.skipped_void_chunks,
            "embedding_count": self.embedding_count,
            "embedding_batch_size": self.embedding_batch_size,
            "embedding_batch_count": self.embedding_batch_count,
            "model_load_elapsed_ms": self.model_load_elapsed_ms,
            "embedding_elapsed_ms": self.embedding_elapsed_ms,
            "index_write_elapsed_ms": self.index_write_elapsed_ms,
            "elapsed_ms": self.elapsed_ms,
            "messages_per_second": (
                0.0 if self.elapsed_ms <= 0 else self.indexed_message_count / (self.elapsed_ms / 1000)
            ),
            "chunks_per_second": (
                0.0 if self.elapsed_ms <= 0 else self.embedding_count / (self.elapsed_ms / 1000)
            ),
            "index_size_bytes": self.index_size_bytes,
            "identity": self.identity.to_dict(),
        }


@dataclass(frozen=True)
class SemanticIndexIntegrityReport:
    """Derived index 内部一致性和 bounded canonical recovery 检查结果。"""

    status: Literal["valid", "invalid"]
    identity: SemanticIndexIdentity
    dimension: int
    parent_count: int
    metadata_chunk_count: int
    vector_count: int
    missing_vector_count: int
    orphan_vector_count: int
    sampled_vector_count: int
    max_sample_norm_deviation: float
    sampled_range_count: int = 0
    recovered_range_count: int = 0
    invalid_range_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """输出不含聊天正文和原始向量的完整性事实。"""

        return {
            "status": self.status,
            "identity": self.identity.to_dict(),
            "dimension": self.dimension,
            "parent_count": self.parent_count,
            "metadata_chunk_count": self.metadata_chunk_count,
            "vector_count": self.vector_count,
            "missing_vector_count": self.missing_vector_count,
            "orphan_vector_count": self.orphan_vector_count,
            "sampled_vector_count": self.sampled_vector_count,
            "max_sample_norm_deviation": self.max_sample_norm_deviation,
            "sampled_range_count": self.sampled_range_count,
            "recovered_range_count": self.recovered_range_count,
            "invalid_range_count": self.invalid_range_count,
        }


@dataclass(frozen=True)
class SemanticChunkRange:
    """完整性检查使用的无正文 canonical range locator。"""

    chunk_id: str
    session_id: str
    start_message_id: str
    end_message_id: str
    message_count: int


@dataclass(frozen=True)
class SemanticQuery(ScopeFilters):
    """有界语义查询；scope 字段沿用 Lexical/Structured 的 canonical 语义。"""

    query: str = ""
    limit: int | None = 10
    context_before: int = 2
    context_after: int = 2
    dense_top_k: int = 40

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.query, str) or not self.query.strip():
            raise SemanticQueryError("semantic query must be non-empty")
        object.__setattr__(self, "query", self.query.strip())
        if self.limit is None or isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise SemanticQueryError("semantic limit must be a positive bounded integer")
        for name, value in (
            ("context_before", self.context_before),
            ("context_after", self.context_after),
            ("dense_top_k", self.dense_top_k),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SemanticQueryError(f"{name} must be a non-negative integer")
        if self.dense_top_k == 0:
            raise SemanticQueryError("dense_top_k must be positive")

    def to_dict(self) -> dict[str, object]:
        """返回 query/filter identity，供 Tool Result、Trace 和 Evaluation 使用。"""

        return {
            **self.scope_dict(),
            "query": self.query,
            "limit": self.limit,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "dense_top_k": self.dense_top_k,
        }


@dataclass(frozen=True)
class SemanticHit:
    """Dense candidate 与 canonical message range 分离表达。"""

    chunk_id: str
    parent_id: str
    session_id: str
    parent_start_message_id: str
    parent_end_message_id: str
    start_message_id: str
    end_message_id: str
    score: float
    score_type: str
    dense_rank: int
    index_identity: str


@dataclass(frozen=True)
class SemanticRetrievalResult:
    """Semantic candidate、canonical recovery 与 completeness 分开表达。"""

    query: SemanticQuery
    filters: Mapping[str, object]
    strategy: Literal["semantic"]
    hits: tuple[SemanticHit, ...]
    expanded_messages: tuple[MessageProjection, ...]
    total_hits: int
    returned_messages: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata


@dataclass(frozen=True)
class SemanticIndexCandidate:
    """Vector store 返回的原始候选；canonical message 仍由 Retrieval 负责恢复。"""

    chunk_id: str
    parent_id: str
    session_id: str
    parent_start_message_id: str
    parent_end_message_id: str
    start_message_id: str
    end_message_id: str
    start_timestamp: int
    end_timestamp: int
    message_count: int
    effective_chars: int
    distance: float
    dense_rank: int


class EmbeddingProvider(Protocol):
    """Embedding provider 的最小独立边界。"""

    @property
    def identity(self) -> EmbeddingModelIdentity:
        """返回不含 secret 的模型身份。"""

    @property
    def document_batch_size(self) -> int:
        """返回 build 时单批 document 数量上限。"""

    def preload(self) -> None:
        """显式完成模型加载，便于把加载耗时和 embedding 耗时分开记录。"""

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """按 document 语义生成向量，不添加 query instruction。"""

    def embed_query(self, text: str) -> tuple[float, ...]:
        """按 query 语义生成向量，并应用 provider 自己的 instruction。"""


class SemanticIndexStore(Protocol):
    """Builder/Retrieval 依赖的 derived store 端口。"""

    def start_rebuild(self, identity: SemanticIndexIdentity, canonical_message_count: int) -> None:
        """清理旧 derived rows 并进入 building 状态。"""

    def insert_chunks(self, chunks: Sequence[tuple[SemanticChunk, Sequence[float]]]) -> None:
        """原子写入 chunk metadata 与向量。"""

    def update_progress(self, indexed_message_count: int) -> None:
        """保存已完成 canonical message 范围。"""

    def finish(self, status: SemanticIndexStatus, error: str | None = None) -> None:
        """保存 build 终态。"""

    def state(self) -> SemanticIndexState | None:
        """读取当前 derived index 状态；缺失状态必须保持可区分。"""

    def size_bytes(self) -> int:
        """返回当前 derived database 主文件大小。"""

    def dense_search(
        self,
        identity: SemanticIndexIdentity,
        query_vector: Sequence[float],
        limit: int,
        *,
        session_ids: Sequence[str] | None = None,
        start_timestamp: int | None = None,
        end_timestamp: int | None = None,
    ) -> tuple[SemanticIndexCandidate, ...]:
        """只返回向量候选与范围元数据，不把它们伪装成 canonical message。"""
