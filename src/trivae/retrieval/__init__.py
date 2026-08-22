"""Retrieval Core 的稳定业务契约与实现入口。"""

from trivae.retrieval.context import ContextExpander, ContextExpansionResult
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import (
    AggregateBucket,
    AggregateData,
    AggregateQuery,
    CanonicalReadRepository,
    Coverage,
    InvalidRetrievalQuery,
    LexicalIndexError,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    MessageQuery,
    RetrievalError,
    RetrievalMetadata,
    RetrievalResult,
    StructuredAggregateResult,
    StructuredMessageResult,
    StructuredRetrieval,
)

__all__ = [
    "AggregateBucket",
    "AggregateData",
    "AggregateQuery",
    "CanonicalReadRepository",
    "ContextExpander",
    "ContextExpansionResult",
    "Coverage",
    "InvalidRetrievalQuery",
    "LexicalIndexError",
    "LexicalQuery",
    "LexicalRetrieval",
    "MessageHit",
    "MessageProjection",
    "MessageQuery",
    "RetrievalError",
    "RetrievalMetadata",
    "RetrievalResult",
    "StructuredAggregateResult",
    "StructuredMessageResult",
    "StructuredRetrieval",
]
