# Implementation Plan: M5a real DeepSeek smoke stabilization

## Phase 1 — baseline and provider capability

1. Read current M5a implementation, task validation, Stage 1.8 ADR and runtime guidelines.
2. Inspect local provider settings without printing secrets.
3. Inspect installed Agents SDK signatures/source for JSON/structured output support.
4. Prepare `messages_fts` through existing `SQLiteLexicalIndex` only when absent/stale.

## Phase 2 — S1 real smoke

1. Run M5A-S1 through `TrivaeApplication.query()` with the real database and DeepSeek.
2. Capture only secret-safe metrics and shape/contract diagnostics.
3. For each failure: reproduce with the smallest harness, attribute the layer, implement the smallest fix, add a deterministic regression, and rerun S1.
4. Stop only if the required fix would change a confirmed Stage 1.8 architectural semantic.

## Phase 3 — representative cases

After S1 succeeds, run M5A-S2, M5A-S3 and M5A-S4 in order. Do not batch them before S1 success.

## Phase 4 — quality and evidence

1. Run full pytest, ruff and mypy.
2. Run CLI help, Trellis validation and `git diff --check`.
3. Record measured smoke facts, real failures, root causes, fixes, regression protection and remaining risks in `validation.md`.
4. Keep generated reports secret-safe and bounded.

## Rollback points

- Revert only the local prompt/provider-format change if it changes low-level M4 runtime semantics.
- Do not revert or weaken current-run provenance, scope validation, trusted hydration or explicit invalid-citation failure.
