# 1M Context Dynamic Budget Experiment Report

## Experiment identity

- Branch：`codex/dynamic-tool-result-budget-regression`
- 起始 HEAD：`e5d406c`（本轮开始时的 journal commit）
- Provider/model：`opencode-go / deepseek-v4-flash`
- Dynamic context source：`verified_model_registry`
- Verified context：`1,000,000`
- 实验 prompt：4 个真实原始问题，每个 variant 3 次重复。
- Variant A：`fixed-16k`。
- Variant B：`dynamic-run-128k`，per-call 128k、run pool 128k。
- Variant C：`dynamic-run-256k`，per-call 128k、run pool 256k。

真实 prompt 原文：

1. `最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西`
2. `最近一个月群里推荐过哪些 Agent 学习资料？`
3. `群里对 taste-skill 的评价是什么？有没有人实际用过？`
4. `最近两周讨论过哪些 DeepSeek 相关项目？`

每个结果只记录 provider/model、Trace ID、tool round、projection estimate、omission/truncation、usage、终态和 finalization diagnostics；不复制回答正文。

## Synthetic/archive findings

完整数字见 [benchmark.md](benchmark.md)。当前可确认的 operational finding：

- synthetic 300-hit：fixed 只显示 141/129 条并遗漏 159/171 个 hit；两个 1M dynamic variant 都显示全部 300 条且 omission 为 0。
- synthetic 1000-hit：两个 dynamic variant 都达到约 122k visible estimate 并触发单次 128k cap；fixed 仍约 15.9k，遗漏 859/871 个 hit。
- archive 1000-hit：Agent dynamic 两个 variant 都显示 689 条且约 123.8k；`https` 两个 variant 都显示 939 条且约 127.8k，同时仍有 61 个 omission，说明 per-call cap 仍真实生效。
- 单个 Tool call 的 fixture 下，128k 与 256k 的 visible projection 几乎相同；run pool 的差异要通过多 Tool call 累计消耗才能显现。
- projection 本身不是质量指标；archive 的 retrieval latency 已单列，避免把数据库读取成本混入预算结论。

## Real provider results

首次尝试发现实验 harness 把 `fixed-16k` 标签直接传给 settings mode，36 个 cell 均被正确拒绝为 `SettingsError`；该批次不计入 A/B。修正后重新运行。

第二次真实尝试的首个 provider query 超过 5 分钟仍没有终态，手动停止以避免无限等待；没有把它写成业务失败或成功。

随后启动带 30 秒单 cell timebox 的第三次运行，目标仍是完整输出 36 行。最终结果应以本文件下方的定稿表为准；`timeout` 只表示 harness 未在 30 秒内观察到 query terminal，不代表 finalization status。

<!-- REAL_RESULTS_START -->

### Real result status: completed with provider availability limits

第三次运行已完成 36/36 个 cell。每个 cell 使用独立 worker 和 30 秒 harness timebox；worker 超时后被终止，因此这些 cell 的 Trace 已创建但没有产品 terminal event。该 timebox 只描述实验观察窗口，不是 Runtime 的业务 fallback。

| variant | cells | completed valid | runtime failed | harness timeout/open |
|---|---:|---:|---:|---:|
| fixed-16k | 12 | 0 | 0 | 12 |
| dynamic-run-128k | 12 | 2 | 0 | 10 |
| dynamic-run-256k | 12 | 1 | 1 | 10 |

在 3 个 completed valid 样本中，context 均为 `1,000,000`、source 均为 `verified_model_registry`、per-call effective budget 均为 128k、omitted/truncated 均为 0。128k run pool 的两个样本分别为 20.438s/23.631s、projection 7,881 tokens；256k run pool 的一个两次 Tool call 样本为 27.842s、projection 合计 15,763 tokens，余额从 256,000 降至 240,237。另有一个 256k cell 明确返回 Runtime failed（不是 finalization degraded），Trace 为 `trace-3fada0b6536d494dbe20c07eac84af5a`。

completed/failed 的结果摘要（不包含回答正文）：

| variant | case/repetition | Trace ID | termination | finalization | projection | tool calls | latency |
|---|---|---|---|---|---:|---:|---:|
| dynamic-run-128k | deepseek_projects/1 | `trace-3af08a6c7547406280974e732e30fd39` | completed | valid | 7,881 | 1 | 20.438s |
| dynamic-run-128k | deepseek_projects/2 | `trace-f871a0df81d5470fb00260cad37a6a59` | completed | valid | 7,881 | 1 | 23.631s |
| dynamic-run-256k | agent_learning_materials/1 | `trace-3fada0b6536d494dbe20c07eac84af5a` | failed | — | 16,841 | 1 | 9.753s |
| dynamic-run-256k | deepseek_projects/2 | `trace-6482c6615658465a9512238cafa95abf` | completed | valid | 15,763 | 2 | 27.842s |

完整 36 个 Trace ID 和观察结果如下；`open / worker killed at 30s` 表示没有拿到 terminal，不能推导答案质量或 provider 成本：

| variant | case | rep | result | Trace ID | finalization | projection | trunc. | omitted ctx/hit | latency | context source / run pool | calls/evidence |
|---|---|---:|---|---|---|---:|---:|---|---:|---|---|
| fixed-16k | github_skills_resources | 1 | timeout | `trace-2dbe528f15124964b2084c69b03ff3c4` | — | — | — | — | — | — | — |
| fixed-16k | github_skills_resources | 2 | timeout | `trace-66f64751805a4e34850c2a337ec2782a` | — | — | — | — | — | — | — |
| fixed-16k | github_skills_resources | 3 | timeout | `trace-1d50a3e1c93a4a9c9f2ea901d54f358f` | — | — | — | — | — | — | — |
| fixed-16k | agent_learning_materials | 1 | timeout | `trace-11c3616efbf049a38b2e6b414bafd14e` | — | — | — | — | — | — | — |
| fixed-16k | agent_learning_materials | 2 | timeout | `trace-866f76611eb440ba9c9c24a10b30dbd3` | — | — | — | — | — | — | — |
| fixed-16k | agent_learning_materials | 3 | timeout | `trace-5b12ac22cba942e0a0d681b703a2962d` | — | — | — | — | — | — | — |
| fixed-16k | taste_skill | 1 | timeout | `trace-c3b5d29ce4a14edc8b26ac1dfc34f6a9` | — | — | — | — | — | — | — |
| fixed-16k | taste_skill | 2 | timeout | `trace-0db99bd2aeb94b2996be75c00d93904d` | — | — | — | — | — | — | — |
| fixed-16k | taste_skill | 3 | timeout | `trace-949fcc4d75ff4f7a92504e2d682a65fb` | — | — | — | — | — | — | — |
| fixed-16k | deepseek_projects | 1 | timeout | `trace-7e054f3c4802438db258e6a9f97597ae` | — | — | — | — | — | — | — |
| fixed-16k | deepseek_projects | 2 | timeout | `trace-6707e61191d54b82b765e592c9c9bc29` | — | — | — | — | — | — | — |
| fixed-16k | deepseek_projects | 3 | timeout | `trace-0a11972e7f9a4d2f8a9417e6f2b6d111` | — | — | — | — | — | — | — |
| dynamic-run-128k | github_skills_resources | 1 | timeout | `trace-1b198acb678d44b198556be1937d0252` | — | — | — | — | — | — | — |
| dynamic-run-128k | github_skills_resources | 2 | timeout | `trace-80c820e9089e40dc87ce776b992f1b4d` | — | — | — | — | — | — | — |
| dynamic-run-128k | github_skills_resources | 3 | timeout | `trace-9a869008351841108961cf66d8046d03` | — | — | — | — | — | — | — |
| dynamic-run-128k | agent_learning_materials | 1 | timeout | `trace-c1a9aa1f159e402c87041cb3030d3cd7` | — | — | — | — | — | — | — |
| dynamic-run-128k | agent_learning_materials | 2 | timeout | `trace-ab965f70c32c4c3cb6aedca5598e768b` | — | — | — | — | — | — | — |
| dynamic-run-128k | agent_learning_materials | 3 | timeout | `trace-41d82e0b17cd408393520ddd2c05e2e2` | — | — | — | — | — | — | — |
| dynamic-run-128k | taste_skill | 1 | timeout | `trace-e4a86ac939b94d29898d398067409f01` | — | — | — | — | — | — | — |
| dynamic-run-128k | taste_skill | 2 | timeout | `trace-699fde42bea345b6941aceaef68bb593` | — | — | — | — | — | — | — |
| dynamic-run-128k | taste_skill | 3 | timeout | `trace-67cfdc1054654ebcb69db26acf4a4879` | — | — | — | — | — | — | — |
| dynamic-run-128k | deepseek_projects | 1 | completed | `trace-3af08a6c7547406280974e732e30fd39` | valid | 7,881 | 0 | 0 / 0 | 20.438s | verified_model_registry / 128,000 | 1 / 1 |
| dynamic-run-128k | deepseek_projects | 2 | completed | `trace-f871a0df81d5470fb00260cad37a6a59` | valid | 7,881 | 0 | 0 / 0 | 23.631s | verified_model_registry / 128,000 | 1 / 1 |
| dynamic-run-128k | deepseek_projects | 3 | timeout | `trace-ba4075d9497a4affaca92e07882d6fc6` | — | — | — | — | — | — | — |
| dynamic-run-256k | github_skills_resources | 1 | timeout | `trace-2301c7399b1e4cce95a7be81d0cecd42` | — | — | — | — | — | — | — |
| dynamic-run-256k | github_skills_resources | 2 | timeout | `trace-dc88176122a54d3a9e5b925c31ca3956` | — | — | — | — | — | — | — |
| dynamic-run-256k | github_skills_resources | 3 | timeout | `trace-e7f9796e65864160b70f48abd6eeb59b` | — | — | — | — | — | — | — |
| dynamic-run-256k | agent_learning_materials | 1 | failed | `trace-3fada0b6536d494dbe20c07eac84af5a` | — | 16,841 | 0 | 0 / 0 | 9.753s | — | 1 / 1 |
| dynamic-run-256k | agent_learning_materials | 2 | timeout | `trace-6eefef3fce80480aacaa7fd36d550e69` | — | — | — | — | — | — | — |
| dynamic-run-256k | agent_learning_materials | 3 | timeout | `trace-1b33cabe19894354a428bb0baa5d3ecd` | — | — | — | — | — | — | — |
| dynamic-run-256k | taste_skill | 1 | timeout | `trace-647295d3fed247b9bcb9447803e8c4aa` | — | — | — | — | — | — | — |
| dynamic-run-256k | taste_skill | 2 | timeout | `trace-e54d1f59da6b483ea33f5fe0cfc88f5a` | — | — | — | — | — | — | — |
| dynamic-run-256k | taste_skill | 3 | timeout | `trace-75aa37c9397b4b47ba9efed2f5c507c2` | — | — | — | — | — | — | — |
| dynamic-run-256k | deepseek_projects | 1 | timeout | `trace-b5f4b6923a0f4ab1bdb2a0104452de73` | — | — | — | — | — | — | — |
| dynamic-run-256k | deepseek_projects | 2 | completed | `trace-6482c6615658465a9512238cafa95abf` | valid | 15,763 | 0 | 0 / 0 | 27.842s | verified_model_registry / 256,000 | 2 / 2 |
| dynamic-run-256k | deepseek_projects | 3 | timeout | `trace-266c11e50aea4e9d9de327913a5a2fb6` | — | — | — | — | — | — | — |

这批真实数据只证明了已验证 registry 和独立预算字段确实进入 provider Runtime，并展示了少量成功/失败终态；由于 32/36 个 cell 超过 harness timebox，不能据此宣称任一 variant 的答案质量、成本或稳定性优胜。

<!-- REAL_RESULTS_END -->

## Cost/latency interpretation

- Host 能稳定测量的是 projection estimate、projection latency、retrieval latency 和 provider 返回的 usage（若 provider 提供）。
- provider usage 缺失时保持 unavailable，不由 visible estimate 反推真实计费 token。
- 当前 synthetic/archive 只测单 Tool call，因此只能证明 128k per-call ceiling、omission 与 truncation 行为；不能单凭此宣布 256k run pool 更优。

## Recommendation

1. 保持 `dynamic` 为默认；`fixed` 仅用于 regression/debug/rollback/evaluation。
2. 保持 1M 模型 per-call ceiling 为 128k，并在 Trace 记录 context source 和两套 budget 字段。
3. known context 的默认 run pool 采用显式公式 `min(floor(context×25%), 256k)`，1M 对应 250k；128k/256k 继续作为可审计实验 override。
4. 本次真实 provider 已形成 3 个 completed valid 样本，但覆盖不足且有 32 个 timebox timeout；仍不宣称 256k 已带来质量收益，先以 synthetic/archive 验证的 128k per-call 行为上线，并保留 run-level override 观察多 Tool call。
