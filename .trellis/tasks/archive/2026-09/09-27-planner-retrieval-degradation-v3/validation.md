# Planner Retrieval Degradation v3 validation

## Before

The frozen current-v2 adjudication remains 6 Cases and 8 paired observations: `planned_beneficial=0`, `standard_preferable=2`, `indifferent=4`, `uncertain=0`. The 15-Case cross-version history remains `0 / 4 / 11 / 0`; it is not a current-v2 result. The separate human adjudication was committed as `c712f79`.

Immediately before v3, the cumulative local Provider ledger contained 74 invocations: Planner 11, Runtime 61, existing Router LLM 0, Jev 2. The implementation commit was `4a4675ef99fee00fc367ba7a98115a4fc5c51a82`; v3 configurations and suites were pinned in `70593fd59e324b657dd9605c7d23aa10e5d273c7`.

## Root cause

### First divergence and confirmed run-level cause

In both frozen v2 `pu-dependent-mattpocock` traces, Standard and Planned first searched the distinctive entity `mattpocock` and received the same complete 8-hit result. The Planner output also retained the repository and the firsthand-feedback requirement. The first substantive divergence was the shared Runtime's next lexical query: Standard used `matt` and received 23/23 complete hits; Planned used the generic category term `skills` and received 100 of 244 hits with `partial=true` and `truncated=true`. The direct firsthand-feedback messages were therefore absent from the Planned candidate set before Evidence preparation. Evidence projection did not drop returned candidates, and the partial boundary was reported accurately.

This confirms a Runtime query-formulation failure for those traces. The 100-result candidate cap exposed its effect but is not itself defective. Planner intent, output projection, Evidence selection, and zero-result proof were not the first failure. The GT target is not corpus-exhaustive, and the required-context marker is a review checkpoint; its absence alone does not establish a wholly incorrect answer.

### Archify and root-cause boundaries

The four v2 `dev-context-archify` traces use a different mechanism. Every direct `archify` lexical search returned all five hits completely. The outcome then depended on which direct hit the Runtime chose for context expansion: Standard recovered the `好用` reply in r1, Planned did not; neither route recovered it in r2, where semantic retrieval also failed. The instability starts at Runtime context-anchor selection, not at broad-query truncation. The Cases share a broader Runtime responsibility to carry a follow-up evidence goal into the next retrieval decision, but they do not share one identical retrieval defect.

Contributing factors are the Runtime's soft guidance, the candidate boundary reached after a broadened query in the dependent trace, and anchor selection variability in archify. Non-causes include a missing Planner intent in the dependent v2 plan, an incorrect retrieval limit contract, dropped tool projection, and a broken zero-result proof contract. Unknowns include how consistently a model follows a soft prompt across workloads and whether either Case's marked evidence set is corpus-exhaustive.

The ChatLab comparison found soft `buildPlanGuidance`, provider search with bounded context expansion, and a separate LIKE-based deep-search path, but no automatic entity-continuation policy. Trivae already owns bounded context expansion and truthful partial/truncated propagation. The evidence therefore supports a small Runtime instruction change; it does not support a second Agent, a new retrieval protocol, automatic continuation, or a wider context radius.

## Fix

The shared Runtime prompt now instructs both routes to retain a named entity as a follow-up lexical anchor, select a context anchor that matches the requested reply/feedback relationship, and broaden the candidate set only for a category-level request or a distinct uncovered evidence need. A deterministic provider-free regression checks that prompt contract. The change is generic and contains no Case ID or query-string branch. Planner schema/rendering, retrieval limits, context budgets, Evidence/Citation logic, and zero-result proof were unchanged. This preserves the ChatLab/Trivae boundary and the existing soft-plan role.

The regression establishes the instruction contract, not guaranteed Provider behavior. The paired v3 run is the behavior check.

## v3 identity and execution

- Code version: `4a4675ef99fee00fc367ba7a98115a4fc5c51a82`.
- Execution pin: `70593fd59e324b657dd9605c7d23aa10e5d273c7`.
- Snapshot: `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 473236}`.
- Provider/model: DeepSeek `deepseek-flash`; Planned and Standard share the same captured environment.
- Variant diff: the only configuration change is `execution_override.forced_route` (`standard_execution` → `planned_execution`).
- Suite: dependent and archify each have two counterbalanced pairs; aggregation and `dev-zero-empty-3` each have one counterbalanced pair. No Jev route, automatic retry, or Holdout case was run.
- The environment gate passed on the execution pin, including canonical Snapshot, lexical index, semantic index identity, and Git commit.

All 12 raw records matched 12 Evaluation runs, 12 Evaluation results, and 12 canonical Trace records by run and trace identity. All runs completed and all results were persisted. Evaluation database result status remains `not_reviewed`: the pairwise notes below are an assistant review in this report, not a user adjudication or a mutation of the frozen v2 adjudication. Every trace shown here is canonical and terminal.

| Pair | Case | Standard trace | Planned trace | Automated result | Assistant pairwise direction |
| --- | --- | --- | --- | --- | --- |
| focus r1 | `pu-dependent-mattpocock` | `trace-425a6e314a704b808c17ab6ec2e22175` | `trace-d13d75e11fa04e9c8bf97a8f5068f367` | Both evidence recall 1/2, context recovery 0/1, false-zero check 1/1; both miss the same marked context ID. | Standard preferable: it includes specific firsthand positive feedback and the opposing `/teach` criticism; Planned reports the criticism but misses the clearer firsthand evidence. |
| focus r2 | `pu-dependent-mattpocock` | `trace-ce3fb6a489754317b5a1d289e84b1917` | `trace-c852007e89914aa0afb1a57de7d71f0d` | Both evidence recall 1/2, context recovery 0/1, false-zero check 1/1; both miss the same marked context ID. | Standard preferable: it again gives concrete firsthand use reports and mixed feedback; Planned is less complete on the firsthand positive context. |
| focus r1 | `dev-context-archify` | `trace-c37f237139954df68fa1b6ac9380897c` | `trace-22d40bd155cb44a788da640b6d904275` | Standard evidence recall 1/2, context recovery 0/1; Planned 2/2 and 1/1; false-zero check 1/1 both. | Planned beneficial: it recovers the “好用” reply and installation/use exchange; Standard says no member reported using it. |
| focus r2 | `dev-context-archify` | `trace-de55c4921b0945ebad22496907673fbf` | `trace-3a2e4774259c4707a5dd1c5f9f8181bb` | Standard evidence recall 1/2, context recovery 0/1; Planned 2/2 and 1/1; false-zero check 1/1 both. | Planned beneficial again: it captures the same positive use context; Standard again misses it. |
| controls r1 | `pu-aggregate-utc-types` | `trace-0e62b864102546e080db9bbefab63f35` | `trace-e404341e7ceb44abaf2d2899bd7902f8` | Both expected-fact coverage 2/2; each reports text 814 and reply 17. | Same quality. |
| controls r1 | `dev-zero-empty-3` | `trace-43dd5d409bb04832811ef8daf047c2d6` | `trace-c5d439aba7fb4f4291f7871a1c8bf59d` | Both verified-zero 1/1 and return the complete empty UTC window. | Same quality. |

All 12 runs had `execution_completed=1/1` and `valid_answer=1/1`. The six evaluation `context_missing` artifacts are preserved: the exact marked source `qq:677019167:7664449865363143925` is absent from all four dependent answers, and `qq:1039179741:7665654465962176057` is absent from both Standard archify answers. The dependent Case's annotation is partial and not corpus-exhaustive, so these failures are evidence-completeness misses rather than a stand-alone verdict on every answer claim.

### Manual review result

Reviewer source: Codex assistant, using the final answer artifacts and paired Trace evidence. This review is explicitly not user/human adjudication. The v2 adjudication artifact remains unchanged.

The repeated direction is mixed by Case: the assistant review finds `standard_preferable` for dependent in both repeats and `planned_beneficial` for archify in both repeats. Both controls are same-quality. Therefore v3 did produce a repeat-consistent case-level Planned-beneficial signal on archify (2/2 observations), while Planned still failed to demonstrate benefit on dependent. This is a candidate signal for a later Router Classification Development set, not a treatment-wide Planner utility claim.

Across the requested quality axes:

- **Answer correctness / task completion:** all 12 runs completed with a valid answer. On dependent, Standard is more complete about firsthand positive and negative feedback; on archify, Planned answers the usage-feedback question while Standard misses the recovered reply context. Both controls return the expected result.
- **Evidence completeness:** dependent evidence recall is 1/2 for both routes in both repeats. Archify is Standard 1/2 vs Planned 2/2 in each repeat. Aggregation returns both expected facts; the zero-result Case has no positive evidence target.
- **Context recovery:** dependent is 0/1 for both routes in both repeats. Archify is Standard 0/1 vs Planned 1/1 in both repeats.
- **Groundedness / citation:** no dedicated automatic groundedness score was configured. The assistant review compared answer claims and source references to their recorded Tool/Evidence output. The Standard archify “no user feedback” conclusion is an omission of available canonical context, not evidence that the feedback was absent from the corpus. Control answers' numeric/zero claims match their structured Tool results.
- **Zero-result correctness:** all four focus runs and both aggregation runs have `false_zero_result=1/1`; both `dev-zero-empty-3` arms have `verified_zero_result=1/1` with complete empty-window coverage.
- **Reliability:** 12/12 evaluation runs reached completed status and produced valid answers. The Planner, semantic retrieval, and context-tool failures below remain visible in Trace and are counted where applicable; completed status does not erase those invocation-level failures.

### Recorded failure behavior

- `trace-22d40bd155cb44a788da640b6d904275` has one `SEMANTIC_EMBEDDING_FAILED` semantic-search failure. Planned continued with lexical/context evidence and recovered the required archify context.
- `trace-de55c4921b0945ebad22496907673fbf` has two `MESSAGE_NOT_FOUND` context calls after the model supplied local `m1-*` aliases as `message_id`. Later calls used `source_id`, resolved to canonical message IDs, and completed; Standard still selected context that missed the “好用” reply. These are visible tool failures, not automatic retries.
- `trace-c5d439aba7fb4f4291f7871a1c8bf59d` has one `PLANNER_INVALID_OUTPUT` with `finish_reason=length` and `failure_detail_code=provider_length` at 2048 output tokens. The Planner lifecycle explicitly records `planner.skipped(reason=planner_failure)`; Runtime then completes the empty-window proof and produces the correct no-result answer. This is one failed Planner invocation and remains in the ledger.
- No Runtime model-turn transport failures were recorded. No automatic retry occurred. Control failure artifacts are empty.

## Operational trade-offs and Provider ledger

The v3 request-start ledger contains 44 of the 102 allowed invocations: 6 Planner + 38 Runtime, with 0 existing Router LLM and 0 Jev. All 44 invocations have token usage recorded; failed Planner output is counted. The per-case counts are dependent 9, archify 9, aggregation 4, and zero 3. The pre-v3 cumulative ledger was 74, making 118 cumulative local invocations after this experiment: Planner 17, Runtime 99, existing Router LLM 0, Jev 2.

| Treatment | Provider invocations | Mean run latency (median; range) | Runtime tool calls | Tool rounds | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Planned (n=6) | 25 (6 Planner + 19 Runtime) | 16.33 s (16.68 s; 12.41–18.50 s) | 20 | 13 | 211,959 | 17,576 | 229,535 |
| Standard (n=6) | 19 (0 Planner + 19 Runtime) | 10.58 s (10.43 s; 3.00–17.99 s) | 20 | 13 | 205,714 | 10,763 | 216,477 |

These are separate operational measures, not a quality score. The observed Planned mean latency is higher in this small sample and includes Planner work; it is not a general performance estimate. DeepSeek returned no monetary cost in the usage records, so v3 cost is unavailable and was not inferred. The full ignored local ledger is `data/evaluation/planner-router-utility/2026-09-27/v3/ledger-final-v3.json`.

## Hypotheses tested and remaining uncertainty

- The dependent v3 results falsify the expectation that adding a generic entity/context anchor instruction is by itself enough: Planned never issued Standard's `matt skill` follow-up search in these two repeats and retained the same required-context miss.
- The archify v3 pair direction is stable across its two repeats, unlike the v2 Standard/Planned pattern. It supports this Case as a treatment-derived Router Classification candidate.
- The 100-hit limit did not cause projection loss; it accurately reported partial retrieval. Raising it or adding continuation was not tested and is not justified by this result.
- Aggregation and verified-zero controls did not regress. The zero-result positive-proof path was not changed.
- The sample is four Cases with two repeats only on the two focus Cases. Dependent GT is partial, and one semantic lookup plus one Planner response failed. Prompt adherence and repeat stability on broader workloads remain uncertain.
- No Holdout was accessed, no generalization claim is made, and no production Jev conclusion follows. Jev remains `shadow`; there was no v3 Jev call.

## Next step

Keep both routes and production Jev unchanged. Carry the two archify Planned-beneficial observations, together with dependent as a Standard-preferable contrast, as candidate Development supervision for a later Router Classification study after treatment/policy freeze. Do not use task complexity alone as a Planned label, and do not promote these small Development observations to production routing.

## Quality checks

The v3 environment gate, Snapshot identity, and forced-route Variant diff passed on execution pin `70593fd`. Raw/Evaluation/result/Trace counts were 12/12/12/12 with exact run and trace identity matches. The final v3 ledger reconstructed 44 invocations, below the 102 cap.

- `.venv/bin/pytest -q`: 631 passed.
- `.venv/bin/ruff check src tests`: passed. A broader `.venv/bin/ruff check .` reports 62 existing findings confined to `.codex/`, `.trellis/`, and an archived task; it found no issue under `src/` or `tests/`. Those unrelated files were not changed.
- `.venv/bin/mypy src`: passed, 115 source files.
- `git diff --check`: passed.
- `trivae eval cases validate`: all four suite Cases passed, including `dev-zero-empty-3@v2`.
- `task.py validate`: passed for this Trellis task.
