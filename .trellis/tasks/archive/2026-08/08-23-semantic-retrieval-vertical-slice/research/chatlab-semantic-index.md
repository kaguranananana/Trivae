# ChatLab Semantic Index Research

## Source and date

Read from the `main` branch of [ChatLab/ChatLab](https://github.com/ChatLab/ChatLab) on 2026-08-23 using GitHub API. Relevant source files included `packages/node-runtime/src/semantic-index/chunker.ts`, `chunker-config.ts`, `embedding/profiles.ts`, `embedding/local.ts`, `store.ts`, `schema.ts`, `retrieval/semantic-search.ts`, `retrieval/evidence.ts`, `service.ts`, `config.ts`, and `chat-db/message-range-reader.ts`.

## Observed design

- Chunking is hierarchical: time-gap/size Parent segmentation, then small Child chunks. Child is the dense unit; Parent IDs preserve range boundaries for evidence recovery.
- Parent boundaries use a time gap and a hard token estimate. Child boundaries use effective character count, soft/hard message limits, hard token limits and small overlap.
- Semantic void detection covers media/system placeholders and short fillers. Void messages remain in the source range and raw content boundary but do not contribute to effective embedding body or participant header.
- Embedding text is contextual: source title/kind, time range, participants and sender-prefixed effective message content are assembled under a bounded token budget. Query instruction is added for query embedding, not for documents.
- The vector store is an independent SQLite database using sqlite-vec `vec0`, with metadata rows joined to a dimension-specific vector table. Dense query is partitioned by database identity/model identity and returns cosine distance; retrieval converts it to a bounded score and applies time overlap filtering.
- Service state is explicit: configured/enabled/index status/model/chunker identity/progress/error are persisted. Model or chunker identity changes make the current index stale; build/rebuild and partial coverage are not inferred from a queue alone.
- Evidence recovery reads canonical message ranges and adds bounded surrounding messages. Final user-facing source is the original message range, not chunk/vector identity.
- ChatLab does not add a cross-encoder reranker or fixed hybrid/RRF path in this semantic primitive.

## Trivae mapping

Inherited: Parent/Child architecture, void-message handling, contextual embedding text, separate vector index, explicit status/coverage, dense retrieval followed by canonical range recovery.

Adapted: Trivae uses canonical `MessageProjection`/SQLite store and existing `ContextExpander`/Evidence contracts; it uses Python official HF/sentence-transformers with `Qwen/Qwen3-Embedding-0.6B` rather than ChatLab's Transformers.js ONNX model ID; it exposes `lexical_search` and `semantic_search` as separate Agent tools; and it uses readable structured identity because the project explicitly forbids writing hash/SHA256.

## Parameters not inherited

ChatLab's 30-minute gap, exact character/token limits, batch and UI/API limits are reference observations only. Trivae chooses a tunable v1 baseline, records it in identity, and leaves evaluation calibration open. No quality claim follows from the ChatLab implementation alone.
