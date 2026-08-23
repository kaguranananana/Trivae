# Semantic Retrieval Vertical Slice Design

## Boundary and data flow

```text
SQLite Canonical Store
  -> SQLiteCanonicalReadRepository.iter_semantic_messages()
  -> SemanticChunker (time-aware parents + small children)
  -> EmbeddingProvider (Qwen3 local baseline)
  -> SQLiteSemanticIndexStore (separate sqlite-vec file)
  -> SemanticRetrieval (ANN + filters + coverage)
  -> ContextExpander/range recovery via canonical read repository
  -> SemanticSearchCapability
  -> SemanticSearchTool / Runtime SDK adapter
  -> existing ToolResultRecord -> Finalizer -> AnswerArtifact/Citation
  -> existing TraceCollector / EvaluationRunner
```

Canonical messages remain the only source of truth. The semantic database stores vector rows and bounded range metadata only; it is disposable and must be rebuilt from canonical messages.

## Contracts

### Index identity

`SemanticIndexIdentity` is a frozen, secret-free projection containing:

```text
database_identity
embedding_provider
embedding_model
embedding_dimension
pooling
normalized
query_instruction
chunker_version
chunker_config (canonical field-ordered mapping)
```

The serialized identity is stored in the derived database and compared exactly before retrieval. Because project instructions prohibit hashes/SHA256, the identity is not represented by a cryptographic digest. API keys, Authorization headers, model cache paths and raw provider configuration are excluded.

### Chunking

`SemanticChunker` receives ordered `MessageProjection` values from one session at a time. It closes a Parent on session boundary (defensive), time gap, or bounded parent size. Each Parent produces small Child ranges with deterministic IDs and limited message overlap. `SemanticVoid` classification only removes text from derived embedding input; the original message IDs remain in the child/parent range and are recovered from canonical storage.

The baseline config is intentionally tunable and not copied as a ChatLab constant. It is part of identity. Header construction is bounded and gives正文优先级：source/session, UTC time range and first-seen participant names are included before effective `sender: content` lines; long headers cannot consume the whole embedding budget.

### Embedding provider

`EmbeddingProvider` exposes model identity and separate `embed_documents()` / `embed_query()` methods. The default `SentenceTransformerEmbeddingProvider` lazily loads `Qwen/Qwen3-Embedding-0.6B`, requests normalized output, declares 1024 dimensions and last-token pooling, and prefixes only queries with the retrieval instruction. A provider error or dimension/normalization contract violation is raised as an embedding-owned error. Tests inject a deterministic provider, so importing Trivae does not require model packages or download weights.

For the normalized baseline, the provider performs deterministic Python-float post-encode normalization before the strict unit-norm check; this preserves the identity contract when Qwen's bfloat16 Normalize projection leaves a small numeric drift.

### Vector store and status

`SQLiteSemanticIndexStore` uses a separate database file and sqlite-vec `vec0` table per dimension. Metadata and vector insertion share a transaction. A state row records identity, canonical message count, processed message count, chunk count, status (`building`, `completed`, `partial`, `failed`) and last error type. Rebuild clears old derived rows first and leaves a typed failed/partial state if embedding or insertion fails. Retrieval never treats a missing or mismatched state as lexical success.

Canonical message-count drift after a completed build is reported as stale and requires an explicit rebuild; the implementation never silently claims completeness for newly imported data. An interrupted build that reaches `status=partial` may return bounded old candidates with explicit known gaps only when vector rows exist; an unavailable/empty index returns a typed capability error.

### Semantic retrieval and context recovery

`SemanticQuery` carries the existing scope filters plus semantic top-k and context bounds. sqlite-vec performs dense candidate retrieval; filters are applied in the vector query/metadata join, with a bounded enlarged pool for time/sender filtering. No Python full-vector scan is used. A `SemanticHit` records chunk ID, parent/range IDs, cosine distance-derived score, score type, dense rank and index identity. The result separately exposes hits and recovered canonical messages.

Range recovery uses a small extension to the existing canonical read adapter, not a second context system. It reads child ranges plus bounded before/after context and rehydrates `MessageProjection`. Sender/message-type filters are validated against canonical recovered messages; scope/session/time predicates stay enforced by the repository/capability boundary.

## ChatLab inheritance and deliberate deviations

Inherited because it matches Trivae's confirmed architecture:

- time-aware Parent + small Child as the primary semantic unit;
- semantic-void filtering at embedding-input construction while preserving canonical ranges;
- contextual source/time/participant header with bounded body;
- independent vector store and metadata/status for rebuild/stale/partial coverage;
- dense retrieval followed by bounded parent/message-range recovery;
- query instruction only on query embeddings and explicit score/range provenance.

Deliberate deviations:

- Python `sentence-transformers`/official HF model instead of ChatLab's Transformers.js ONNX runtime, because the user selected the Python baseline `Qwen/Qwen3-Embedding-0.6B`.
- sqlite-vec is used through the Python package and standard sqlite3 rather than ChatLab's better-sqlite3 binding; this preserves local-first single-file ANN without adding a server. If the package cannot be installed on a target platform, the failure is explicit and the task does not silently switch to a Python full scan.
- Identity is canonical structured data, not SHA256/config hash, because repository AGENTS.md forbids writing hashes/SHA256. This still makes every required model/pooling/normalization/instruction/chunker field traceable and comparable.
- Current Trivae evidence returns canonical message sources; semantic chunks are acquisition provenance only, matching Stage 1.8 rather than exposing vector rows as citations.

## Explicit non-goals

- fixed lexical+semantic hybrid, RRF, reranking, query rewrite, multi-query or message-level index;
- external vector service, PostgreSQL migration or distributed worker;
- new Evidence Agent/Judge or a second Runtime/QueryOrchestrator;
- secret-bearing identity or Trace payload.

## Default Agent tool exposure

`semantic_search` 已注册并可由显式 Controlled Variant 或 `QueryRequest.available_capabilities`
启用，但交互式 CLI 与未声明 variant 的生产请求继续使用 `QueryRequest` 的兼容默认
`("search_messages",)`。在带标签的配对 Evaluation 证明稳定收益前，不把 lexical 与
semantic 两条检索工具同时设为生产默认。

## Verification and rollback shape

Focused fake-provider tests prove deterministic contracts without model download. An index build can be discarded by deleting/rebuilding the derived semantic database; canonical data is never modified. Runtime/evidence tests use the existing fake model/tool patterns. Real-data smoke runs against a temporary copy or a separate derived path and records measured counts/latency only when actually observed.
