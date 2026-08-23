"""Semantic Retrieval vertical slice public components."""

from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.chunking import (
    DEFAULT_SEMANTIC_CHUNK_CONFIG,
    SEMANTIC_CHUNKER_VERSION,
    SemanticChunkConfig,
    SemanticChunker,
)
from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticBuildStats,
    SemanticChunk,
    SemanticChunkRange,
    SemanticIndexCandidate,
    SemanticIndexIdentity,
    SemanticIndexIntegrityReport,
    SemanticIndexState,
    SemanticIndexStatusReport,
    SemanticQuery,
    SemanticRetrievalResult,
)
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.semantic.retrieval import SemanticRetrieval

__all__ = [
    "DEFAULT_SEMANTIC_CHUNK_CONFIG",
    "SEMANTIC_CHUNKER_VERSION",
    "EmbeddingModelIdentity",
    "SentenceTransformerEmbeddingProvider",
    "SemanticBuildStats",
    "SemanticChunk",
    "SemanticChunkRange",
    "SemanticChunkConfig",
    "SemanticChunker",
    "SemanticIndexBuilder",
    "SemanticIndexCandidate",
    "SemanticIndexIdentity",
    "SemanticIndexIntegrityReport",
    "SemanticIndexState",
    "SemanticIndexStatusReport",
    "SemanticQuery",
    "SemanticRetrieval",
    "SemanticRetrievalResult",
    "SQLiteSemanticIndex",
]
