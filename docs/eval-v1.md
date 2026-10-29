# Eval v1

> **历史基线记录（2026-10-28）**：本页冻结了 eval@v1 的题集、运行和评分事实，不代表当前默认配置或当前待办。当前评测入口与正式工作库流程以 [Evaluation 文档](evaluation.md) 和 [项目状态](PROJECT_STATUS.md) 为准；下面记载的旧运行条件不应直接复制到新实验。

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

## Historical run conditions (2026-10-28; not a current recipe)

The following limits describe the recorded eval@v1 experiment only: eight turns, six
tool rounds, 128,000-token declared context window for budget calculation, a
32,000-token Run evidence pool, 50% per-call ceiling, 16,384 output tokens and 2,048
completion tokens. Jev routing was disabled. The primary Router could use the
configured model for ambiguous queries. The Agent had seven permitted
retrieval/context/schema tools and no filesystem, GT, Judge, or evaluation-result
tool. These values are not the repository defaults and do not describe every run.

Model identities and environment overrides are described in the
[current configuration guide](configuration.md#配置加载与模型profile). The profile
active in an old run is evidence about that run, not a statement of today's default.
For a new formal experiment, pass the master freeze manifest directly to
`trivae eval run`; the current entry creates an isolated APFS working clone. Do not
first run `eval clone-data` and pass that working copy as the formal master. See
[current Evaluation run instructions](evaluation.md#本地验证入口).

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

The old local review commands depended on the ignored eval@v1 answer bundle and
working databases. They are retained as historical usage context only; use the current
Evaluation and model configuration documents when preparing a new run or review.

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

## 补跑结果（2026-10-28）

首轮 Agent 全套在第 14 题终态错误后保存 14 个 Run，随后在独立冻结数据副本上补跑此前未启动的第 15、16 题；两条均成功，且各自的完整 Trace、配置、运行耗时和用量已保存。现有 16 个 Eval v1 Case 均有唯一 Run/Trace，Agent 成功 14/16（87.5%，分母16）；失败为第 3 题 `AnswerDeltaParseError` 与第 14 题 `APIStatusError`（未记录状态码）。补跑两条最终答案引用校验有效，但每条都记录一次 `TOOL_RESULT_BUDGET_EXHAUSTED` 工具错误，分别发生在 `get_message_context` 与 `lexical_search`。

对 14 个成功 Run，最终均完成 GPT OAuth Judge Review（14/14，100%）。初次恢复调用中的第 12、13 题各遇到一次 `ConnectError` / `AUTH_NETWORK` 或 `PROVIDER_ERROR`，没有 HTTP 状态码；用户要求继续后，两题重试及第 15、16 题评分均成功。最终五维暂定标签分布（每项分母14）为：任务完成 pass 9 / mixed 5；事实正确 mixed 14；证据召回 pass 6 / mixed 8；引用忠实 mixed 14；无依据主张 mixed 9 / fail 5。结果为模型辅助且未人工确认。现有 OAuth 凭证已成功完成全部评分，没有使用付费 API；依据无 HTTP 状态的间歇连接错误，无法得出认证失败结论。

补跑明细、全部运行记录、可用 Token 统计、Judge 响应和失败记录在 ignored `data/evaluation/eval-v1-baseline-20261028/supplement-20261028/`；原首轮 `REPORT.md` 与 `summary.json` 保持不变。
