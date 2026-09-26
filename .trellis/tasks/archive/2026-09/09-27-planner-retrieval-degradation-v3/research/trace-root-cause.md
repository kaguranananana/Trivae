# Trace root-cause review

## Scope and evidence source

This review reconstructs the frozen v2 runs from `data/trivae.sqlite3`, compares returned message IDs against the canonical `messages` table, and checks the existing evaluation artifacts. It distinguishes the observed mechanism in these runs from a causal claim about every Planned run. User adjudication remains the source of the v2 treatment labels.

## Dependent Case: `pu-dependent-mattpocock`

The two v2 runs share the same query and Snapshot. Standard is `eval-run:pu-dependent-mattpocock:v1:planner-utility-standard-20260926-v2:63ee8a29eb7a455abe6573a0b952ba21` / `trace-8b94fbe5e2054edb9291d0a680bbbef4`; Planned is `eval-run:pu-dependent-mattpocock:v1:planner-utility-planned-20260926-v2:75abf06ead914998bdc023894be0a2e7` / `trace-00c81ce34fad4a03b960864ebc5762e7`.

| Stage | Standard | Planned |
| --- | --- | --- |
| User request | Find the `mattpocock` skills-repository share and usage, then follow the discussion for later feedback and distinguish firsthand evidence. | Same request. |
| Route / Planner | Forced Standard; no Planner. | Forced Planned. At sequence 6 the plan title and first step retain `mattpocock` and the repository; later steps ask for same-discussion feedback, firsthand-use statements, and an explicit limitation. |
| First retrieval | Sequence 7 searches `mattpocock`, limit 100, context 2/2: 8/8 hits, 38 expanded messages, complete. | Sequence 9 uses the same keyword and bounds: 8/8 hits, 38 expanded messages, complete. |
| First follow-up divergence | Sequence 11 searches `matt`, limit 100, context 1/1: 23/23 hits, 58 expanded messages, complete. | Sequence 13 searches the category word `skills`, limit 100, context 0/0: 244 total hits, 100 returned, `partial=true`, `truncated=true`. |
| Tool-result projection | The `matt` result is delivered with `projection_truncated=false`, zero omitted messages. | The 100 returned `skills` messages are delivered with `projection_truncated=false`, zero omitted messages. Retrieval itself had already hit the candidate bound. |
| Follow-up context / evidence | The complete `matt` result and its local expansion supply messages later selected as Evidence, including `qq:677019167:7667405489013552983` (“最近用 matt 的 skill，感觉基本是是理想型”) and `qq:677019167:7667405489013552978` (“他这个仓库的整个开发流程真的都可以用一下”). | The two explicit context calls follow anchors from the initial recommendation/share results. The firsthand feedback IDs above are absent from the returned `skills` candidate set and are not selected as Evidence. `evidence.prepare.completed` carries `tool_result_partial`, `retrieval_partial`, and `retrieval_truncated`. |
| Final answer | Reports recommendation / `/teach` usage and includes firsthand positive experience. | Reports the repo and caveats, but omits the firsthand feedback and over-relies on an initial “try it” / usage-intent message. |

### Earliest substantive divergence

```text
Planner output: keeps mattpocock + repo + later feedback/firsthand-use criteria
        ↓
Runtime first call: exact `mattpocock` in both routes; complete 8-hit result
        ↓
Runtime follow-up: Standard `matt`; Planned `skills`
        ↓
Retrieval: `matt` returns 23 complete hits; `skills` returns 100 of 244 and is partial/truncated
        ↓
Evidence: firsthand feedback is selected in Standard; unavailable in Planned's returned candidates
        ↓
Answer: Standard includes it; Planned omits it
```

The first observed loss is Runtime query formulation at the second retrieval call. The decisive later `skills` result is not lost to Evidence selection or model-result projection: those stages cannot select a message absent from the returned candidate set. The primary mechanism in this trace is a follow-up query that drops the distinctive entity anchor and crosses the lexical result limit.

### Layer classification

- **Confirmed in this run — Runtime query formulation:** after both routes receive the same complete entity-anchor result, the Planned Runtime uses the generic category term `skills`; Standard keeps the distinctive `matt` anchor.
- **Confirmed contributing condition — Retrieval bound:** `skills` has 244 hits and returns the first 100, so the relevant firsthand messages are outside that returned set. The 100-result bound behaves as configured.
- **Correct behavior / non-cause — coverage and projection:** Retrieval marks `partial` and `truncated`; Evidence preserves those limitations. The Runtime tool-result projection omits no returned messages and reports no projection truncation.
- **Non-cause — Planner entity loss:** the captured plan still names `mattpocock`, requires same-discussion follow-up, asks for firsthand-use evidence, and requires limitations. It does not itself replace the name with `skills`.
- **Symptom — Evidence and answer omission:** selected sources and final answer omit the firsthand messages because the broad follow-up did not return them.
- **Unknown — provider-side prompt replay:** the plan result and actual tool calls are traceable, and source code appends soft plan guidance to the Runtime instructions. The stored `model_visible_context` projection truncates the system message at 512 characters; the exact full provider prompt and Planner request body are not preserved in this Trace. Therefore the trace proves the Runtime's emitted tool arguments, but cannot prove which exact prompt bytes the provider consumed or that the soft guidance alone caused the query choice.
- **Causal limit:** one paired v2 observation establishes a concrete failure mechanism, not a stable treatment-wide causal estimate. The separate v3 repeats are needed to assess whether the generic Runtime instruction changes behavior reliably.

The Case's known first-party target IDs are not corpus-exhaustive ground truth. Their absence alone is not scored as a complete-answer failure; the user adjudication instead notes that Standard surfaced stronger firsthand evidence and Planned did not.

## Context Case: `dev-context-archify`

All four v2 runs use the same query, Snapshot, and direct lexical search. The recorded mappings are:

| Repeat | Treatment | Run ID | Trace ID |
| --- | --- | --- | --- |
| r1 | Standard | `eval-run:dev-context-archify:v1:planner-utility-standard-20260926-v2:95e441a537d64614bdc1f1e49dfe8b75` | `trace-4ad6c048824846c1a2c34cb2c5e0934c` |
| r1 | Planned | `eval-run:dev-context-archify:v1:planner-utility-planned-20260926-v2:7a1a4d9c35d24e5b95944f7c69a3f4c5` | `trace-b5c099f9cb6c4618a2d6f9b06c10054d` |
| r2 | Standard | `eval-run:dev-context-archify:v1:planner-utility-standard-20260926-v2:47d55525531045e7a920a3022214380c` | `trace-16cd0ed79a4847d798be032f2b2e22a5` |
| r2 | Planned | `eval-run:dev-context-archify:v1:planner-utility-planned-20260926-v2:9b819a7f8c4c45729ed2b3bd30d44fdb` | `trace-88b6767dce094884a6d5df6916480e64` |

### Per-run reconstruction

- **Standard r1:** `lexical_search("archify", limit=100, context=2/2)` returns all 5 direct hits and 21 expanded messages, complete. Runtime then calls `get_message_context` on three anchors, including the initial repository-share / experience invitation `qq:1039179741:7665652181386089161`. Evidence contains the nearby replies `...7665653481878183461` (“可以”), `...7665653481878183456` (“好东西”), `...7665654465962176057` (“好用”), and `...7665654465962176047` (“安装了以后咋用”). The final answer includes them.
- **Planned r1:** the first lexical call is the same keyword and is also complete (5 hits, 29 expanded messages with context 3/3). Its later `get_message_context` calls anchor on the 9.5k/star update, plugin announcement, and outside-platform pointer, rather than the earlier invitation thread. The returned Evidence misses those replies; the final answer says no member reported actual experience. Planner guidance asks to check usage context, so omission is at Runtime anchor selection, not absent Planner intent or direct-hit Retrieval.
- **Standard r2:** the first lexical result remains complete (5 hits, 21 expanded messages). Semantic retrieval fails with `SEMANTIC_EMBEDDING_FAILED`; Runtime then expands two different direct hits, not the initial invitation thread. The selected Evidence and answer miss the reply messages.
- **Planned r2:** the first lexical result is likewise complete (5 hits, 21 expanded messages); semantic retrieval fails with the same `SEMANTIC_EMBEDDING_FAILED`. Runtime does not call `get_message_context`; the selected Evidence and answer miss the replies.

### Relationship to the dependent Case

The **specific first failure mechanisms differ**. The dependent Case changes the lexical query from a distinctive entity anchor to a generic category, causing a 100/244 partial result. Archify keeps the exact `archify` query and retrieves every direct hit; its instability comes later, from which direct-hit source the Runtime expands with `get_message_context` (plus a shared semantic-provider failure in r2). The r1/r2 swing also means one positive Standard trace cannot establish stable context-recovery behavior.

Both expose a broader Runtime weakness: follow-up evidence goals are soft, and the Runtime does not reliably preserve the most relevant entity/thread anchor when choosing its next query or context source. This is a shared responsibility area, not proof of one identical retrieval defect. The v3 change will be a small, generic Runtime instruction about keeping a precise entity and selecting context anchors that match the requested follow-up relation; it will not alter context radius, candidate limits, or add automatic retries/continuation. Archify remains a separate, unstable validation Case.

## ChatLab comparison

The local ChatLab reference has soft `buildPlanGuidance` that explicitly permits answering more directly instead of following a plan mechanically. Its `search-messages.ts` performs provider keyword search, optionally expands context with `getSearchMessageContext`, and trims to the result limit while preserving direct hits. `deep-search-messages.ts` is a distinct LIKE search path. These tools do not define an automatic query-continuation or entity-anchor policy.

Trivae already has the corresponding bounded context-expansion responsibility in `LexicalRetrieval` and additionally emits explicit partial/truncated coverage through the capability, Runtime envelope, Evidence limitations, and Trace. The observed dependent failure is upstream of this correct retrieval contract; the observed archify instability is in the Runtime's choice of context anchors, not a missing second agent or a need to copy a new retrieval tool. Therefore the fix stays in the shared Runtime prompt and does not add a Planner executor, another Agent, a continuation loop, or a parallel Tool contract.

## Minimal implementation boundary

Update the shared Runtime instructions to:

1. retain a named, high-discrimination entity in follow-up lexical retrieval instead of replacing it with a generic category term alone;
2. when the requested next evidence is a reply, later reaction, or usage feedback, prefer context from the direct hit that establishes the share/invitation/usage thread over an unrelated later mention of the same entity;
3. allow broader searches when the user's request is category-level or when the entity-anchored result is materially insufficient, while keeping returned partial/truncated limits explicit.

Do not change Planner parsing/rendering, lexical result limits, context expansion radii, Evidence selection, citation validation, zero-result proof, or provider retry behavior. The rule applies to Standard and Planned because both share the same Runtime. Regression tests will lock the general prompt contract; existing retrieval/coverage and zero-result tests will verify those unrelated contracts remain intact.
