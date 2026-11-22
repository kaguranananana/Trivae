# Eval rubric v3

`eval-rubric-v3` upgrades the offline capability judge from the two-axis `eval-rubric-v2`/`v2.1` schema to **three orthogonal 0–4/`unknown` dimensions**, fixes input-layer evidence blind spots, compacts deduplicated evidence threads, introduces **tiered adjudication priority**, and adds **position-swapped blind pairwise comparison** (`eval-pairwise-v1`).

Historical rubrics (`eval-rubric-v1`, `eval-rubric-v2`, `eval-rubric-v2.1`) and their saved Reviews remain immutable and readable via [capability_judge.py](../src/trivae/evaluation/capability_judge.py).

## Why v3 (empirical motivation)

Across 115 real `eval-rubric-v2`/`v2.1` reviews (`eval@v1` baseline/calibration/Prompt A/B and `eval@v2` 24×2 A/B):

1. **Overloaded `answer_reliability`**: 91.5% of all diagnostics (118/129 in `eval@v2`) landed on `answer_reliability`, mixing hard factual/citation errors (`factual_error`, `citation_mismatch`, `attribution_error`) with soft epistemic overgeneralization (`unsupported_assertion`, `temporal_or_scope_error`).
2. **Score compression & cross-axis tension**: `answer_reliability` collapsed almost entirely into scores `2` and `3`, while `(task_satisfaction=4, answer_reliability=2)` occurred in 22% of answers.
3. **Input blind spots & payload bloat**: `prepare_review_input` previously passed raw Unix millisecond timestamps, omitted human/bot sender display names on context neighbors, lacked `source_message_id` and far-reply target resolution beyond ±3 messages, and duplicated overlapping contexts + answer snapshots (~181K median chars/review).
4. **Alert fatigue**: flagging every isolated `moderate` diagnostic pushed 95.6% (43/45) of reviews into `needs_adjudication=true`.

## Scoring dimensions (`eval-rubric-v3`)

Each axis is scored independently from `0` to `4`, or `"unknown"` when critical source evidence is physically absent from the review input (for example, unexecuted SQL aggregates, non-text media without OCR/transcript, or unexpanded forward payloads). `unknown` is excluded from numeric means and is never treated as `0`.

| Dimension | Core question | Primary diagnostic types |
| --- | --- | --- |
| `task_satisfaction` | Did the answer understand and resolve the user's request with practical value? | `omitted_key_information`, `other` |
| `evidence_grounding` | Are concrete facts, names/domains/numbers, speaker attribution, and bound citations faithful to the raw messages? | `factual_error`, `citation_mismatch`, `attribution_error` |
| `epistemic_calibration` | Does the answer accurately calibrate evidence strength, scope, and temporal validity without overgeneralizing single posts/bots/old chats? | `unsupported_assertion`, `temporal_or_scope_error` |

### Key boundary rules in v3

- **Honesty protection**: When chat evidence is genuinely sparse, candidly disclosing limitations and sample boundaries must **not** lower `task_satisfaction`.
- **Anti-split ceiling**: When `evidence_grounding` or `epistemic_calibration` has a core error directly misleading the main conclusion (axis `<= 1` or materially misleading central advice), `task_satisfaction` cannot receive `4` and is capped at `2–3` according to actual user impact.
- **User-facing focus**: Prioritize the user-facing `content_blocks` and their `citation_bindings` rather than internal `evidence_links` phrasing.

## Input enrichment & deduplication

`build_review_payload` (shared by `prepare_review_input` and A/B harness scripts) now provides:

- Readable `timestamp_iso` (converted to the case's `time_context` timezone) alongside canonical `timestamp`.
- Resolved `sender_display` (from group card / nickname / name / `users` table) and `session_name` on both cited and neighbor messages.
- Same-millisecond peer inclusion in ±3 neighbor windows (`(timestamp, internal_message_id)` tie-breaker).
- Far-reply target resolution: when a cited message has `reply_to_source_message_id` pointing outside the ±3 window, the target message is fetched from the frozen database (within case scope) and marked `is_reply_target=true`.
- Compact v3 representation: overlapping neighbor contexts are merged into deduplicated chronological `evidence_threads` per session, and heavy duplicate `snapshot` blobs are stripped from `answer.evidence_links` while keeping `content_blocks` and `citation_bindings` lossless.

## Tiered adjudication priority

For `eval-rubric-v3`, `EvaluationReview.adjudication_priority` classifies human-review urgency:

| Priority | Trigger condition | `needs_adjudication` |
| --- | --- | --- |
| `high` | Any axis is `unknown` or `<= 1`, any `severe` diagnostic, or cross-axis conflict (`task_satisfaction == 4` while `evidence_grounding <= 2` or `epistemic_calibration <= 2`) | `true` |
| `medium` | Any axis is `2` (and not `high`) | `true` |
| `low` | All axes `>= 3`, with isolated `moderate` diagnostic(s) | `false` |
| `none` | All axes `>= 3` and no `moderate`/`severe` diagnostics | `false` |

## Blind pairwise comparison (`eval-pairwise-v1`)

For fine-grained A/B comparisons where 0–4 pointwise integers lack resolution, `prepare_pairwise_input`, `parse_pairwise_judgment`, and `aggregate_position_swapped_pairwise` evaluate anonymized `(answer_a, answer_b)` sharing one canonical `evidence_threads` timeline in **both orders** (`A=baseline, B=candidate` and `A=candidate, B=baseline`). Consistent winners across both orders are kept; flipped outcomes are explicitly recorded as `tie_position_inconsistent`.
