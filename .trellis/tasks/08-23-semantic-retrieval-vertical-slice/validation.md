# Semantic Retrieval Vertical Slice Validation

## Branch and base

- Branch: `codex/semantic-retrieval-vertical-slice`
- Base before implementation: `2e01168` (`Merge model provider configuration`)
- Trellis task: `08-23-semantic-retrieval-vertical-slice`

## Deterministic validation

The focused semantic suite uses an injected deterministic provider. It validates the implementation contract and does not make a model-quality claim.

```text
pytest -q tests/test_semantic_retrieval.py
9 passed

pytest -q
225 passed

mypy src
Success: no issues found in 67 source files
```

The focused checks cover:

- Time-aware Parent + Small Child boundaries and semantic-void input exclusion;
- `Qwen/Qwen3-Embedding-0.6B` default identity shape, query-only instruction, dimension and normalization checks;
- secret-free readable index identity without a hash/SHA256 digest;
- independent sqlite-vec rebuild and canonical range recovery;
- explicit `SEMANTIC_INDEX_NOT_READY` and `SEMANTIC_INDEX_STALE` tool errors;
- semantic Trace strategy/index facts and distinct `semantic_search` SDK schema;
- current-run Evidence provenance containing canonical messages, not semantic chunks/vector rows.

## Real Canonical SQLite smoke

The source database `data/trivae.sqlite3` was opened through the read-only canonical repository. It contains 473,236 messages across 7 sessions. The derived semantic database was created under a temporary directory and removed after the run; the canonical file was not modified.

For this smoke, `sentence-transformers`, `torch`, `transformers`, and model weights were not installed in the local environment. The run therefore used an explicit deterministic normalized 1024-dimensional provider named `smoke/deterministic-1024`. It validates stream/chunk/index/range plumbing only; it does not validate Qwen semantic quality, recall, precision, or latency.

Measured full-canonical structural smoke:

| fact | value |
| --- | ---: |
| canonical messages read | 473,236 |
| indexed messages | 473,236 |
| semantic child chunks | 54,285 |
| skipped semantic-void-only chunks | 5,093 |
| build status | `completed` |
| rebuild time | 84,779.01 ms |
| semantic retrieval time | 1,528.01 ms |
| recovered canonical messages | 8 |
| retrieval status | partial (bounded ANN candidate pool) |

The measured time is a structural baseline for the current Python/sqlite-vec path, not a production performance target. The full Qwen provider path remains the next runtime dependency/calibration step.

## Follow-up operational and Qwen provider validation

The follow-up added explicit Application/CLI boundaries:

```text
trivae semantic status --database <canonical>
trivae semantic rebuild --database <canonical>
trivae semantic smoke --database <canonical> --query <text>
trivae eval snapshot --database <canonical> [--output <manifest.json>]
```

The status projection distinguishes `missing`, `building`, `completed`, `partial`, `failed`, and `stale`; stale includes provider/chunker identity mismatch and canonical message-count drift. The smoke output contains locator/score/coverage/latency/index facts and omits expanded message content by default.

The optional semantic extra was installed successfully in the local Python 3.14 environment (`sentence-transformers=5.7.0`, `torch=2.13.0`, `transformers=5.15.1`). A provider-only run loaded `Qwen/Qwen3-Embedding-0.6B` and measured `dimension=1024`, `norm=1.0`, `pooling=last_token`, `normalized=true`, and the configured query instruction.

The first real provider run exposed a failure: Qwen3's bfloat16 Normalize projection produced a norm around `1.002`–`1.003`, so the strict normalized contract failed. The root fix was explicit post-encode float normalization followed by strict validation; no tolerance widening or retrieval fallback was added. Regression coverage is in `tests/test_semantic_retrieval.py`.

On a synthetic 3-message fixture, the real Qwen provider completed a separate derived-index rebuild (`1` child chunk, `3/3` indexed messages) and an ANN query with `1` recovered canonical hit, `3` expanded canonical messages, complete coverage, and no truncation. This is a provider/index plumbing smoke only, not a semantic quality claim.

The real canonical Snapshot manifest was materialized to a temporary path without committing it: `473,236` messages, `14` sources, lexical index present with `473,236` rows, status `available`. The design-seed semantic Case remains unavailable for quality scoring until a controlled Snapshot is paired with human Finding annotations. A full-canonical Qwen rebuild and paired lexical-vs-semantic quality run were intentionally not treated as completed evidence; they require an explicit local compute budget and annotation workflow.

## Evaluation fixtures

- `evaluation/variants/semantic-lexical-baseline.json` is a lexical-only control using `lexical_search`.
- `evaluation/variants/semantic-enabled-candidate.json` exposes `lexical_search` and `semantic_search`, and records model, dimension, pooling, normalization, instruction identity, chunker version and secret-free index identity.
- `evaluation/cases/seed-semantic-paraphrase.json` is a design seed with an unavailable snapshot. It intentionally cannot produce quality scores until a versioned real snapshot and human reference annotation are bound.

## Pending Evaluation / known limits

- Run the official `Qwen/Qwen3-Embedding-0.6B` provider against a controlled real Snapshot and human-annotated Finding set before making any quality or performance claim.
- Calibrate chunk bounds, semantic-void thresholds, ANN pool size, context budget and candidate ranking with paired lexical-only vs semantic-enabled cases.
- The current implementation treats canonical message-count drift as stale and requires an explicit rebuild; an interrupted build with the same canonical count is represented as partial only when the build reaches that terminal state.
- The compatibility `search_messages` name remains for existing direct callers; it has no strategy parameter and reuses the lexical capability. New runtime-facing names are `lexical_search` and `semantic_search`.
- The interactive CLI and unspecified `QueryRequest` path keep the compatibility default `search_messages`; `semantic_search` is available only when an explicit request or Controlled Variant exposes it, pending labeled evaluation.
