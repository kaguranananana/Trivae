# Validation

## 范围与结论摘要

- branch：`codex/dynamic-tool-result-budget-regression`
- 真实 provider credential 在本地存在；没有把 secret value 写入 Trace 或报告。
- 新增 policy、settings、Runtime、projection、Trace 和 evaluation operational facts 已贯通；retrieval acquisition 与 canonical Evidence 未改写。
- 质量结论是“按 case 分化”，不是预设 dynamic 必然更好：GitHub/Skills 的 evidence coverage 与完成率改善；Agent learning 有一次 dynamic finalization failure；taste-skill 与 DeepSeek 没有稳定质量提升。

## Policy contract

已实现并由 `tests/test_tool_result_budget.py` 覆盖：

| context window | percent | cap | run pool |
| ---: | ---: | ---: | ---: |
| 32000 | 50 | 128000 | 16000 |
| 64000 | 50 | 128000 | 32000 |
| 128000 | 50 | 128000 | 64000 |
| 256000 | 50 | 128000 | 128000 |
| unknown | — | — | 16000 safe fallback |

计算公式为 `min(floor(context_window_tokens * max_tool_result_percent / 100), max_tool_result_tokens)`。dynamic run 的每次调用先预留 `min(per_call_ceiling, remaining)`，projection 完成后归还未使用 reservation，再按 actual estimated tokens 扣减；因此同一 run 的累计 actual projection 不会超过 pool。unknown context 也复用同一共享账本，不能每个 Tool 独立获得一份 16000。

## Cross-layer verification

- `ModelSettings` 严格解析四个新环境变量；非法 mode、非正整数和超界 percent 显式抛出 `SettingsError`。
- `OpenAIAgentsRuntimeAdapter` 每个 run 创建新的 policy；Tool adapters 在 capability invoke 前 reserve，使用现有 `project_tool_result_for_model()` 完成 projection，再写入 canonical record 和 immutable snapshot。
- `RuntimeToolCall` 保留旧的 estimated/truncated/hit fields，并增加 omitted context 与完整 `ToolResultBudgetSnapshot`；fixed 直接 caller 仍保持 16000 compatibility。
- `TraceCollector` 在每个 `runtime.tool.completed` 写入 per-call snapshot，在 terminal runtime event 写入 mode/source/pool/final remaining/call count；`evaluation.checks.operational_measurements()` 只暴露 bounded budget facts，不把截断自动当作质量下降。
- 新回归验证 canonical record 仍完整、direct-hit 与 source handle 同步、projection metadata 明确、多个 Tool 调用共享 pool。

## Deterministic synthetic benchmark

详细测量见 `benchmark.md`。在 Agent/`https` 两类 fixture、100/300/1000 规模下，dynamic-128k 使用 64000 pool；300 条时固定模式分别省略 159/171 个 hit，而 dynamic 保留全部 300 个；1000 条时 dynamic 仍显式省略 429/479 个 hit，证明绝对边界和 omission Trace 同时生效。该 benchmark 只说明 projection/cost，不给答案质量打分。

## Real A/B setup

同一代码版本、同一 provider/model、只切换预算环境变量；每个条件 3 次。四个 prompt 为：

| case | exact prompt |
| --- | --- |
| GitHub/Skills | `最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西` |
| Agent learning | `最近一个月群里推荐过哪些 Agent 学习资料？` |
| taste-skill | `群里对 taste-skill 的评价是什么？有没有人实际用过？` |
| DeepSeek | `最近两周讨论过哪些 DeepSeek 相关项目？` |

dynamic 条件为 `context_window=128000`、`percent=50`、`cap=128000`，即 64000 run pool；fixed 条件保留 16000 per-call baseline。

## Four-case operational A/B

`tokens` 是本次 run 所有 Tool projection estimated tokens 之和；`trunc` 是 Tool call 数；`omit` 是 omitted context/hit message 总数；latency 是 Trace wall-clock duration 中位数。provider latency 会受模型采样、tool strategy 和本地加载影响，不能直接归因给 budget。

| case | fixed completion / median latency | dynamic completion / median latency | fixed tokens / dynamic tokens | fixed trunc / dynamic trunc | fixed omit(context/hit) / dynamic omit(context/hit) | result |
| --- | --- | --- | --- | --- | --- | --- |
| GitHub/Skills | 1/3 / 40169 ms | 3/3 / 70109 ms | 26315 / 27324 | 4 / 0 | 0/4 / 0/0 | dynamic 可见 URL/分组更稳定；完成率 +2/3，但延迟并未改善 |
| Agent learning | 3/3 / 38418 ms | 2/3 / 45671 ms | 26052 / 28928 | 2 / 0 | 152/0 / 0/0 | 成功答案均保留已知 URL；dynamic 一次 finalization schema failure |
| taste-skill | 3/3 / 39505 ms | 3/3 / 25664 ms | 13600 / 12965 | 0 / 0 | 0/0 / 0/0 | 两边都正确区分测试意图与实际使用，无稳定质量差异 |
| DeepSeek | 3/3 / 40077 ms | 3/3 / 52375 ms | 19090 / 10101 | 0 / 0 | 0/0 / 0/0 | control；projection 未越过固定边界，不能把 dynamic 计作质量收益 |

### Per-case attribution

- GitHub/Skills dynamic 三次均为两次 Tool call；首个 call 的 effective budget 为 64000，实际约 16841，第二个 call 看到约 47159，再按实际值结算，最终仍有约 36.6k 余额。fixed 成功样本出现 16k projection 截断/4 个 hit omission；两次 fixed failure 分别是 model candidate 超过 20 个 source 和 Runtime error。
- Agent learning dynamic 第 3 次展示了四个连续 call 的 effective budget `64000 → 53636 → 52922 → 51913`，实际总计 28928，余额仍约 35072；第 2 次 failure 的实际总 projection 37866、余额仍约 26134，根因是 `limitations` 字段类型错误，不是池耗尽。
- taste-skill 两边都没有 projection truncation/omission；dynamic 的 token 与 fixed 接近，质量安全性一致。
- DeepSeek 两边均成功且无 projection truncation；dynamic per-call 实际 projection 中位数低于 16k，属于 control，模型 tool strategy 改变了调用次数/文本量，不能用来证明 dynamic 本身造成质量变化。

### Aggregate deltas and quality review

- 完成率：GitHub/Skills `1/3 → 3/3`；Agent learning `3/3 → 2/3`；taste-skill `3/3 → 3/3`；DeepSeek `3/3 → 3/3`。
- projection omission：GitHub/Skills fixed 有 4 个 hit omission、dynamic 为 0；Agent learning fixed 有 152 个 context omission、dynamic 为 0；另两题两边均为 0。
- 质量人工抽样不是自动指标，也没有把 `citation unresolved=0` 当作 entailment。GitHub/Skills dynamic 的成功答案按 Skills/Agent/工具/学习资源分组并保留具体 URL，优于 fixed 成功样本只列代表性名称的覆盖表现；Agent learning 两边均找回并保留 joye Agent 入门 URL；taste-skill 两边均没有把“想测试”推成“实际使用”；DeepSeek 两边均保留主要项目，但未证明完整 name-only 枚举。
- 结论：dynamic 适合作为显式 context window 的 projection 容量策略，但 real A/B 不能宣称整体答案质量或延迟普遍提升。上线建议先保持默认 fixed，针对已验证 context window 的 provider/model 显式开启 dynamic，并继续收集 per-call omission 与 finalization failure。

## Trace IDs

| case | fixed | dynamic |
| --- | --- | --- |
| GitHub/Skills | `trace-0045abb9ff0f42f3b78800461d4aef19`, `trace-a40d22e40f22449caac2184fa7cf0b92`, `trace-e7455c0e25e1493cb4192c14baa7ff26` | `trace-6caf97a073b54df39e2a0d1a932f68ad`, `trace-cdb91514afc9404aa77947b503e586dd`, `trace-4ffafb8bb5ae40388de5c505d03abea9` |
| Agent learning | `trace-186724afbc8d485ca014d2e2d118d684`, `trace-3cf29759705342a39a15b5e0f7a60dfa`, `trace-0f4c269e4de5453981d934fb4600bd2e` | `trace-ff896ee208b540c780e850418378c89b`, `trace-2a8db4985fd848588589ad83d15cb65e`, `trace-1f92a88a83c040dbbef296dddbad3464` |
| taste-skill | `trace-211a5a011a924700b8e8fb803e80c7dc`, `trace-c0bd6ba8277b4e17a617ed856419762a`, `trace-de7f8ea5bdc44ca6bc5c7597270d78df` | `trace-c696e33357e14e419fcb1d6d618e9ad6`, `trace-cb15fde02f294cc2b528f35a639918e1`, `trace-e3ac750e131243e4bd2bff9a76f45103` |
| DeepSeek | `trace-159e320c83254adc86475a125077473e`, `trace-7ed56072603345eeb9c4c4afa1b17193`, `trace-f953d2164e1f46e9a8f8b13b909ba293` | `trace-11a7f44a9dbd4746a1381ba4ba2ae7c4`, `trace-a24b251ef4f54613a3df3595f6934c0a`, `trace-3dc11d7e2e774ddd87dc669aa9bcab65` |

## Remaining risks

- The real provider model still emits occasional invalid finalization shapes; this task preserves explicit failure rather than adding a repair branch.
- Dynamic cannot recover evidence discarded before projection by retrieval limits, and 64k pool still truncates 1000-item inputs; omissions and canonical counts must be read together.
- No verified provider metadata registry or tokenizer was added. Those are future changes requiring new evidence and should not be inferred from model names.

## Interview Defense Notes

- Problem: fixed 16000 is the existing per-call projection baseline, but it cannot use a verified larger context window; Runtime also lacked one cumulative ledger for a run.
- Decision: settings only accepts an explicit context window; policy calculates `min(floor(context * percent / 100), cap)`, and the Tool adapter reserves before projection and settles by actual estimated tokens.
- Why not: no model-name capacity guess, retrieval hard-cap rewrite, tokenizer dependency, retry, or automatic citation repair; each would confound the experiment or hide the root cause.
- Failure: the first real A/B async-close error was localized to harness lifecycle; three provider/model failures retain finalization schema and runtime attribution instead of being mislabeled as budget failures.
- Evidence: 14 focused regression tests, 333 full-suite tests, the synthetic 100/300/1000 benchmark, the read-only SQLite archive benchmark, and 24 real A/B Trace runs support the current conclusion.
- Scale: 1000-item projection still reaches the explicit 64000 run pool boundary; dynamic exposes more evidence but does not guarantee enumeration completeness or answer correctness, so quality review remains separate from operational facts.
- Evolution trigger: only verified provider metadata, a real tokenizer/billing requirement, or Evaluation evidence that current omission/quality attribution is insufficient should reopen resolver/estimator design.
