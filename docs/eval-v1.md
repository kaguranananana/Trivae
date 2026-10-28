# Eval v1

`eval@v1` is the separate 16-question real-user evaluation set. Its name does not
assert that any capability is solved or deficient; that judgment requires actual
evaluation. The committed manifest contains only case identities. The questions,
versioned Cases, reference facts, complete chat text, search logs, and review records
remain in the ignored local directory `data/evaluation/eval-v1-20261028/`. The earlier
Capability suites, 30-question candidate, Regression suite and their experiments
retain their identities. The previous name and its fixture/preflight records remain
in the original ignored local directory. The Case IDs, questions and evidence are
unchanged; the Cases are saved as v2 solely because their GT, rubric and suite tags
were renamed. The original Case v1 versions remain with the historical bundle.

The fixed query time is 2026-10-28 12:00 at UTC+08:00. The frozen Canonical database has
864,615 messages; its latest message is 2026-10-27 21:44:51 at UTC+08:00. Its freeze ID
is `freeze-84892e107a4548bc849a60ebed7c9314`; Canonical, lexical and semantic revisions
are 98835. The local freeze manifest records the complete snapshot and index identity.
The evaluated Agent receives the as-of time as separate context; its natural-language
question is unchanged. For relative time, this establishes the reference date; it
does not guarantee a model will use an appropriate search window.

## Ground truth and review

The 16 questions were frozen before this round of retrieval. Two sets of lexical
expressions searched the frozen original messages, with time-ordered searches for
recent topics and adjacent context read back. The former 30-question GT supplied
optional leads for 15 unchanged questions; the revised subscription question was
researched separately. The 16 reference bundles contain 58 case-level source records,
54 distinct messages from seven sessions and 406 saved context records. The private
`REPORT.md` contains each need, reference fact, information type, coverage assessment,
uncertainty and revision. Seven cases were judged sufficiently supported for their
main need and nine only partially supported; this is a limited-search judgment, not a
claim of corpus-wide completeness.

Codex performed the semantic review in the same session as construction, using a
different search pass and rereading original records. This is model-assisted review,
not an independent human confirmation or a guarantee of correctness. The deterministic
auditor checks snapshot, source IDs, time, session, message text, reply and forwarded
metadata, saved context, Case/GT alignment, and the recorded search chronology. It
cannot prove semantic entailment, recall, or whether an old offer is still available.
The saved retrieval scripts and query lists are specific to these 16 questions. New
questions still require Codex to choose search expressions and judge semantic support;
this version does not provide a general one-command GT generator for arbitrary inputs.
Personal experiences, robot answers, speculation and promotional posts remain labeled;
offers and product comparisons cannot be extrapolated to the query date. A reference
with no evidence is valid when both Case and packet are empty; it does not assert the
entire corpus contains no evidence.

The GT is open-ended. Its cited messages are examples, not an exhaustive whitelist;
other sources are acceptable when their raw messages support the answer. Model-assisted
reviews are provisional, with `mixed` and `unknown` kept separate. Runtime failures
are counted independently from answer quality. No human approval gate is required,
and no automatic result is represented as human-confirmed.

Recheck the local bundle against the frozen master:

```bash
PYTHONPATH=src .venv/bin/python scripts/verify_capability_bundle.py \
  --bundle-dir data/evaluation/eval-v1-20261028 \
  --suite evaluation/suites/eval-v1.json \
  --freeze-manifest data/evaluation/frozen-20261028-validated/freeze.json \
  --database data/evaluation/frozen-20261028-validated/trivae.sqlite3 \
  --output data/evaluation/eval-v1-20261028/bundle-verification.json
```

## Running one case or a suite

Formal experiments require a clean committed checkout, a separate working clone and
independent Evaluation database per experiment. The local clone
`data/evaluation/capability-formal-v1-work/` has been used for the fixture-only smoke
test; create a fresh clone with `trivae eval clone-data` for each independent experiment. The fixed runtime settings
are defined in `capability_conditions.py`: eight turns, six tool rounds, 128,000-token
declared context window for budget calculation, 32,000-token run evidence pool,
50% per-call ceiling, 16,384 output tokens and 2,048 completion tokens. Jev routing is
disabled; the production Router/Planner and prompt from the recorded Git commit are
otherwise unchanged. The primary Router may use the configured model for ambiguous
queries. The seven permitted retrieval/context/schema tools are fixed in
the same module. There is no filesystem, GT, Judge, or evaluation-result tool available
to the Agent; the private bundle is separate from the Canonical working database.

Model identities, providers, endpoints, authentication references, and supported model
parameters live in `config/models.yaml`. `.env` contains API keys and local runtime
overrides only. Ordinary queries default to `defaults.query`; `TRIVAE_MODEL_ID` can
select another configured profile. Existing `TRIVAE_MODEL_PROVIDER` and
`TRIVAE_MODEL_*` overrides remain available for older commands. Eval defaults to
`evaluation.agent` and `evaluation.judge`; `--agent-model` and `--judge-model` select
any profile whose provider call is implemented. The DeepSeek profile reads
`DEEPSEEK_API_KEY`; ChatGPT Plan uses the existing local OAuth Auth Store and official
Responses endpoint. Model profiles never contain key or OAuth token values.

The helper rejects mismatched budgets and writes a new private Variant rather than
overwriting one.

```bash
export TRIVAE_MAX_TURNS=8 TRIVAE_MAX_TOOL_ROUNDS=6
export TRIVAE_MAX_OUTPUT_TOKENS=16384 TRIVAE_COMPLETION_MAX_TOKENS=2048
export TRIVAE_TOOL_RESULT_BUDGET_MODE=dynamic TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS=128000
export TRIVAE_PER_CALL_TOOL_RESULT_PERCENT=50 TRIVAE_PER_CALL_TOOL_RESULT_CAP=128000
export TRIVAE_RUN_TOOL_EVIDENCE_PERCENT=25 TRIVAE_RUN_TOOL_EVIDENCE_CAP=256000
export TRIVAE_RUN_TOOL_EVIDENCE_BUDGET=32000 TRIVIAE_ROUTER_JEV_ENABLED=false

.venv/bin/trivae eval clone-data --manifest data/evaluation/frozen-20261028-validated/freeze.json \
  --output-dir data/evaluation/eval-v1-my-model-work

.venv/bin/python -m scripts.prepare_capability_variant \
  --freeze-manifest data/evaluation/eval-v1-my-model-work/freeze.json \
  --agent-model deepseek-flash \
  --variant-id my-model-v1 --output data/evaluation/eval-v1-20261028/my-model.json

.venv/bin/trivae eval run --suite evaluation/suites/eval-v1.json \
  --cases-dir data/evaluation/eval-v1-20261028/cases \
  --case-list data/evaluation/eval-v1-20261028/one-case.json \
  --agent-model deepseek-flash \
  --variant data/evaluation/eval-v1-20261028/my-model.json \
  --database data/evaluation/eval-v1-my-model-work/trivae.sqlite3 \
  --evaluation-database data/evaluation/eval-v1-my-model.sqlite3 \
  --freeze-manifest data/evaluation/eval-v1-my-model-work/freeze.json \
  --record-dir data/evaluation/eval-v1-my-model-record --judge-version none --repeat 1
```

Remove `--case-list` to run all 16; use `--repeat` for repeated runs. The manifest
captures the Case and GT identities, freeze, Git commit, Variant, runtime and router
settings, tool surface, effective provider-specific reasoning and transport, and run IDs. Full answers and citations are retained in the
working database's conversations; the Evaluation database keeps bounded projections
and references. Traces remain in the working database. Usage and latency are recorded
when returned; missing usage and cost remain unknown. Keep each working database,
Evaluation database and experiment record together. `--judge-version none` records
that no Judge ran during execution; it is not an automatic quality score.

## Offline scoring and comparison

After a completed run, an explicit offline Judge rereads the complete saved answer,
resolves its actual message citations from the frozen database, and compares them with
the open-ended references. This includes valid sources absent from the reference pack.
The Judge receives private questions, reference messages and answer content at the
configured provider. It uses a single no-tools completion and does not run Agent
retrieval. API-key profiles use the existing compatible completion path; ChatGPT Plan
uses the existing OAuth Auth Store and official Responses/SSE transport with storage
disabled. No API billing fallback is available. It stores its input, selected profile,
request settings, response, available usage and provisional Review locally; provider
and authorization errors remain explicit. Structured SQL results are not re-executed
by this review and should remain `unknown` when they cannot be established from the
supplied evidence.

```bash
PYTHONPATH=src .venv/bin/python -m scripts.judge_capability \
  --bundle-dir data/evaluation/eval-v1-20261028 \
  --suite evaluation/suites/eval-v1.json \
  --freeze-manifest data/evaluation/eval-v1-my-model-work/freeze.json \
  --database data/evaluation/eval-v1-my-model-work/trivae.sqlite3 \
  --evaluation-database data/evaluation/eval-v1-my-model.sqlite3 \
  --run-id 'the completed Run ID' --judge-model gpt-plus \
  --record-dir data/evaluation/eval-v1-my-model-reviews/review-01

PYTHONPATH=src .venv/bin/python scripts/audit_capability.py report \
  --suite evaluation/suites/eval-v1.json \
  --cases-dir data/evaluation/eval-v1-20261028/cases \
  --database data/evaluation/eval-v1-my-model.sqlite3
```

Repeat the explicit Judge command for each completed Run. `compare_capability_models.py`
checks the recorded code, suite, data, settings and repetitions while allowing model,
provider and endpoint to vary. With `--baseline-reviews DIR --candidate-reviews DIR`,
it additionally requires one saved review per completed Run and the same actual Judge
and configuration. Without those options it reports that Judge conditions were not
checked. Provider-specific protocol or execution-setting differences are reported as
incomparable; in particular, the subscription adapter uses a different tool transport
and does not expose the same server-side output-token control as compatible API
providers. A strict same-condition comparison across those transports is therefore not
yet established. Provider-specific reasoning settings and Planner treatment are also
compared; even identical effort labels cannot guarantee identical model behavior.
Sampling and provider behavior can still vary between repeated runs.

The Judge, condition checks and time forwarding have local fixture coverage. Under the
previous suite identity, a single-case fixture Runtime against the real frozen working
copy verified time delivery, absence of reference facts from Agent input, and Trace
persistence; its deliberately failed Runtime was not a model run. A formal preflight
using the locally configured ChatGPT model also passed for `eval@v1`.

The first live baseline on 2026-10-28 passed the one-case DeepSeek Agent + ChatGPT Plan
OAuth Judge smoke. The full Agent Suite then persisted 14/16 Run and Trace pairs: 12
successful, two failed, and two not attempted. The measured success rate was 12/14
(85.7% of attempts). One failure was a model-answer JSON parse error after an HTTP 200;
the other was a terminal `APIStatusError` with no status code in the safe Trace, so the
Suite stopped. Of 12 completed Runs eligible for Judge, 10 Reviews completed before
the OAuth model-catalog request failed with `AUTH_NETWORK` / `ConnectError`; the remaining
two were not retried. These model-assisted labels are provisional and use a denominator
of 10, not 16. The detailed per-Run status, Trace, Review, usage, duration, and failure
record are in the ignored local `data/evaluation/eval-v1-baseline-20261028/REPORT.md`.
The baseline is partial; no complete 16-case score or ranking is claimed. No paid API
fallback was used. The runner stops a Suite after a terminal Runtime/Provider failure.

LangSmith remains an optional explicit metadata-only export, using the existing
`langsmith-sync` workflow.
