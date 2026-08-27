"""Python local Embedding provider for the v1 semantic retrieval baseline."""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Sequence
from typing import Any

from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    EmbeddingPooling,
    SemanticEmbeddingError,
)

DEFAULT_EMBEDDING_PROVIDER = "sentence-transformers"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_DIMENSION = 1024
DEFAULT_EMBEDDING_POOLING: EmbeddingPooling = "last_token"
DEFAULT_EMBEDDING_NORMALIZED = True
DEFAULT_QUERY_INSTRUCTION = (
    "Given a chat history search query, retrieve relevant conversation messages that answer the query"
)
_DEFAULT_MPS_CACHE_RELEASE_INTERVAL = 16


class SentenceTransformerEmbeddingProvider:
    """惰性加载官方 sentence-transformers 模型，并严格校验向量 contract。"""

    def __init__(
        self,
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_EMBEDDING_DIMENSION,
        pooling: EmbeddingPooling = DEFAULT_EMBEDDING_POOLING,
        normalized: bool = DEFAULT_EMBEDDING_NORMALIZED,
        query_instruction: str = DEFAULT_QUERY_INSTRUCTION,
        batch_size: int = 8,
        mps_cache_release_interval: int = _DEFAULT_MPS_CACHE_RELEASE_INTERVAL,
        model_loader: Callable[[str], Any] | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("embedding model must be non-empty")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
            raise ValueError("embedding batch_size must be positive")
        if (
            isinstance(mps_cache_release_interval, bool)
            or not isinstance(mps_cache_release_interval, int)
            or mps_cache_release_interval <= 0
        ):
            raise ValueError("MPS cache release interval must be positive")
        self._identity = EmbeddingModelIdentity(
            provider=DEFAULT_EMBEDDING_PROVIDER,
            model=model,
            dimension=dimension,
            pooling=pooling,
            normalized=normalized,
            query_instruction=query_instruction,
        )
        self._batch_size = batch_size
        self._mps_cache_release_interval = mps_cache_release_interval
        self._document_batch_count = 0
        self._model_loader = model_loader
        self._model: Any | None = None

    @property
    def identity(self) -> EmbeddingModelIdentity:
        """返回 provider 可追踪身份；不会触发模型加载或网络访问。"""

        return self._identity

    @property
    def document_batch_size(self) -> int:
        """返回 build 侧使用的 bounded batch size。"""

        return self._batch_size

    def preload(self) -> None:
        """显式预加载模型，供启动检查或真实 smoke 使用。"""

        self._load_model()

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """对 document 原文编码；document 不添加 query instruction。"""

        normalized_texts = self._normalize_texts(texts, "documents")
        if not normalized_texts:
            return ()
        encoded = self._encode(normalized_texts)
        vectors = self._validate_vectors(encoded, len(normalized_texts))
        self._document_batch_count += 1
        if self._document_batch_count % self._mps_cache_release_interval == 0:
            self._release_mps_cache()
        return vectors

    def embed_query(self, text: str) -> tuple[float, ...]:
        """只给 query 添加 Qwen3 retrieval instruction，并返回单个向量。"""

        normalized_texts = self._normalize_texts((text,), "query")
        instructed = f"Instruct: {self.identity.query_instruction}\nQuery: {normalized_texts[0]}"
        encoded = self._encode((instructed,))
        vectors = self._validate_vectors(encoded, 1)
        # Query traffic 没有长 rebuild 的 batch rhythm；每次完成后释放空闲 MPS cache。
        self._release_mps_cache()
        return vectors[0]

    def _release_mps_cache(self) -> None:
        """在真实 MPS cache 增长 Failure Case 下释放未占用 allocation，不改变模型权重。"""

        model = self._model
        if model is None or getattr(getattr(model, "device", None), "type", None) != "mps":
            return
        try:
            torch_module = importlib.import_module("torch")
            torch_module.mps.empty_cache()
        except Exception as exc:
            raise SemanticEmbeddingError(
                f"failed to release MPS embedding cache: {type(exc).__name__}: {exc}"
            ) from exc

    def _load_model(self) -> Any:
        """延迟导入可选重量依赖，确保应用创建不下载或初始化模型。"""

        if self._model is not None:
            return self._model
        try:
            if self._model_loader is not None:
                model = self._model_loader(self.identity.model)
            else:
                module = importlib.import_module("sentence_transformers")
                constructor = getattr(module, "SentenceTransformer")
                # Qwen3 模型仓库提供 last-token pooling 的 sentence-transformers 配置。
                # 这里保留官方模型配置，identity 明确记录 pooling，避免手写第二套 pooling 语义。
                model = constructor(self.identity.model, trust_remote_code=True)
        except Exception as exc:
            raise SemanticEmbeddingError(
                f"failed to load embedding model {self.identity.model}: {type(exc).__name__}: {exc}"
            ) from exc
        self._model = model
        return model

    def _encode(self, texts: Sequence[str]) -> object:
        """调用 sentence-transformers 的标准 encode API，不在 provider 内做降级分支。"""

        model = self._load_model()
        encode = getattr(model, "encode", None)
        if not callable(encode):
            raise SemanticEmbeddingError("embedding model does not expose encode()")
        try:
            return encode(
                list(texts),
                batch_size=self._batch_size,
                normalize_embeddings=self.identity.normalized,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            raise SemanticEmbeddingError(
                f"embedding encode failed: {type(exc).__name__}: {exc}"
            ) from exc

    @staticmethod
    def _normalize_texts(texts: Sequence[str], name: str) -> tuple[str, ...]:
        """拒绝空文本，避免向量数量与 canonical child 数量发生隐式错位。"""

        normalized = tuple(text.strip() if isinstance(text, str) else "" for text in texts)
        if any(not text for text in normalized):
            raise SemanticEmbeddingError(f"embedding {name} contains empty text")
        return normalized

    def _validate_vectors(self, encoded: object, expected_count: int) -> tuple[tuple[float, ...], ...]:
        """逐向量校验 count、dimension、finite 和 normalized contract。"""

        to_list = getattr(encoded, "tolist", None)
        value = to_list() if callable(to_list) else encoded
        if expected_count == 1 and isinstance(value, Sequence) and value and isinstance(value[0], (int, float)):
            rows: list[object] = [value]
        elif isinstance(value, Sequence):
            rows = list(value)
        else:
            raise SemanticEmbeddingError("embedding output is not a sequence")
        if len(rows) != expected_count:
            raise SemanticEmbeddingError(
                f"embedding output count mismatch: expected {expected_count}, got {len(rows)}"
            )

        vectors: list[tuple[float, ...]] = []
        for row in rows:
            row_to_list = getattr(row, "tolist", None)
            row_value = row_to_list() if callable(row_to_list) else row
            if not isinstance(row_value, Sequence) or isinstance(row_value, (str, bytes)):
                raise SemanticEmbeddingError("embedding row is not a numeric sequence")
            try:
                vector = tuple(float(item) for item in row_value)
            except (TypeError, ValueError) as exc:
                raise SemanticEmbeddingError("embedding row contains a non-numeric value") from exc
            if len(vector) != self.identity.dimension:
                raise SemanticEmbeddingError(
                    f"embedding dimension mismatch: expected {self.identity.dimension}, got {len(vector)}"
                )
            if any(not math.isfinite(item) for item in vector):
                raise SemanticEmbeddingError("embedding row contains a non-finite value")
            if self.identity.normalized:
                # Qwen3 的 Normalize 模块可能在 bfloat16 输出下留下约 1e-3 的范数误差；
                # 在转换为 Python float 后再次做一次确定性 float64 归一化，确保写入 vec0 的
                # 实际向量满足 identity，而不是用放宽阈值掩盖“normalized”语义漂移。
                norm = math.sqrt(sum(item * item for item in vector))
                if norm <= 0.0 or not math.isfinite(norm):
                    raise SemanticEmbeddingError("embedding row has an invalid normalization norm")
                vector = tuple(item / norm for item in vector)
                normalized_norm = math.sqrt(sum(item * item for item in vector))
                if abs(normalized_norm - 1.0) > 1e-6:
                    raise SemanticEmbeddingError(
                        f"embedding row could not be normalized: norm={normalized_norm:.6f}"
                    )
            vectors.append(vector)
        return tuple(vectors)
