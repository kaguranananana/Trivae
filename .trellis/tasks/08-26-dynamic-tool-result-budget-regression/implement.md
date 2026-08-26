# Dynamic Tool Result Budget / Quality Regression Implementation Plan

## Phase 1 — task setup and contract inventory

- [x] Confirm previous retrieval-budget branch is already merged into current `main` and the worktree is clean。
- [x] Create `codex/dynamic-tool-result-budget-regression` from the current `main` tip。
- [x] Read backend/runtime, error, logging, quality, cross-layer, code-reuse and project workflow specs。
- [x] Record the exact previous prompt/trace inventory for later A/B comparison without treating historical retrieval results as new dynamic results。

## Phase 2 — typed policy and configuration

- [x] Add shared default constants for dynamic percentage and absolute cap without changing retrieval constants。
- [x] Implement typed budget config, per-run policy, reservation, completion accounting, source/resolution metadata and explicit exhaustion errors。
- [x] Extend `ModelSettings` and env parsing; test defaults, valid dynamic values, invalid values and safe serialization。

## Phase 3 — runtime and Tool adapter integration

- [x] Create one fresh policy in each `RuntimeContext`/Agent run。
- [x] Pass a reserved effective budget through lexical, semantic, context, schema and SQL Tool adapters into the existing projection boundary。
- [x] Attach immutable per-call budget snapshots to `RuntimeToolCall` while retaining current projection fields and canonical records。
- [x] Consolidate duplicated Tool-result append bookkeeping only where it preserves each adapter's existing capability/error behavior。

## Phase 4 — Trace and evaluation facts

- [x] Serialize per-call budget snapshots in `tool.completed` Trace events and run-level summaries。
- [x] Preserve aggregate projection metrics and add omitted-context/run-pool facts without storing full hidden/model data。
- [x] Expose budget facts in operational evaluation measurements; keep quality labels independent。

## Phase 5 — regression tests and deterministic benchmark

- [x] Add policy formula, fallback, multi-call, reservation, exhaustion and fixed compatibility tests。
- [x] Add projection/adapter/Trace round-trip tests for truncation, canonical completeness and source handles。
- [x] Add deterministic Agent/HTTP synthetic benchmark at 100/300/1000 and fixed vs dynamic 128k→64k; record measured output in `benchmark.md` and `validation.md`。

## Phase 6 — real A/B and quality gate

- [x] Detect provider credential availability without printing secrets。
- [x] If available, run the four exact historical prompts with at least three fixed and three dynamic runs per case; preserve Trace IDs and compare quality/cost separately。
- [x] If unavailable, record the exact blocked condition and do not invent A/B results。
- [x] Run pytest, ruff, mypy, compileall, CLI help, Trellis validation and diff check; fix implementation root causes first。
- [ ] Write validation/interview evidence, commit implementation, and report final branch/commit without merging or force-pushing。

## Files expected to change

- `src/trivae/config/limits.py`
- `src/trivae/config/settings.py`
- `src/trivae/query/runtime/budget.py` (new)
- `src/trivae/query/runtime/contracts.py`
- `src/trivae/query/runtime/openai_adapter.py`
- `src/trivae/query/runtime/openai_tools.py`
- `src/trivae/observability/collector.py`
- `src/trivae/observability/contracts.py` and/or `projection.py` only if the existing public metrics contract needs the new aggregate fields。
- `src/trivae/evaluation/checks.py` only for operational budget facts。
- focused tests for settings, policy, runtime tools, evidence and observability。
- task `validation.md`, plus a project spec/ADR update only if implementation changes a durable public contract。

## Guardrails

- Generated code comments are Simplified Chinese; key accounting/projection logic is explained line by line。
- Do not change retrieval limits or rewrite the existing projection trimming algorithm。
- Do not add model-name context guesses, retry/fallback branches, silent error handling, hash/SHA256 code, or prompt-specific conditions。
- Use `apply_patch` for file edits and keep the change set reviewable。
