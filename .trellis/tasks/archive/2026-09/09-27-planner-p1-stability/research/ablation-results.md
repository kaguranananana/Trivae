# Planner completion 归因消融（正式三路前）

## 观察身份

第一轮 `experiment/`：8 个暴露 Development Case × 3 repeats × 4 variants，96 次 interleaved Provider calls；P0/P1 冻结 prompt，P1-B 为压缩 prompt + `low`，P2-v1 为同一压缩 prompt + `none`。原始记录、request、usage、raw response 和 prompt 均在 `runs.jsonl`；盲包只涵盖 P0/P1/P2-v1。Provider 是 DeepSeek `deepseek-flash`，JSON mode，`max_tokens=2048`，Runtime Tool Loop=0，自动 retry=0。

| Variant | Valid | provider_length | Input / output tokens | Mean latency |
| --- | ---: | ---: | ---: | ---: |
| P0 low | 19/24 | 5 | 10,494 / 31,093 | 6.22 s |
| P1 low | 21/24 | 3 | 29,982 / 33,974 | 7.20 s |
| P1-B compact low | 19/24 | 5 | 25,422 / 35,569 | 7.25 s |
| P2-v1 compact none | 24/24 | 0 | 24,822 / 4,035 | 1.42 s |

第一轮所有 13 次 `provider_length` 都达到 2048 output tokens，且 Provider 报 reasoning token 1821–2048；10 次 reasoning token 恰好 2048 且可见 content 为空。P1 的 3 次分别为 2013、2048、2048 reasoning tokens；其一只有 89 字符未闭合 JSON。这确认了**近端失败机制**：thinking 消耗 completion 上限，导致最终 JSON 无法完整产生。不是可见 Plan 的 Step/字段文字普遍膨胀。P0 同样出现 5 次，说明旧实验的 3/24 vs 5/24 差异在该样本规模下不稳定。P1-B 缩短 prompt 约 19% input tokens 仍 5/24 截断；“压缩本身解决可靠性”被本轮否定。不能据此声称更长输入必然导致更多 reasoning；模型随机性与有效温度仍存在。

## 后续隔离探针（仅诊断，不充当正式 gate）

| Probe / 原始目录 | Valid | 2048 length | Input / output tokens | Mean latency | 质量观察 |
| --- | ---: | ---: | ---: | ---: | --- |
| 原 P1 prompt + none / `ablation-p1-nonthinking/` | 24/24 | 0 | 29,382 / 4,022 | 1.36 s | zero-result 3/3 增加假设非空检索；cite-archify 3/3 并列 lexical/semantic。 |
| 原 P1 prompt + 3072 low / `ablation-p1-budget-3072/` | 24/24 | 0 | 29,982 / 32,911 | 6.96 s | 多数 P1 质量保留，但最高实际 output 仅 2020；无法证明 3072 上限带来成功。 |
| 压缩 v2 + none / `ablation-compact-v2-none/` | 24/24 | 0 | 26,862 / 3,841 | 1.31 s | simple direct lookup 改善，但 zero-result 2/3 仍加 context，rank 3/3 合并 schema/SQL。 |
| 压缩 v3 + none / `ablation-compact-v3-none/` | 24/24 | 0 | 27,798 / 3,909 | 1.33 s | zero-result 3/3 单步完整窗口；aggregation/rank 3/3 schema→SQL；entity/context 主路径保留。 |

`none` 请求未返回 `reasoning_tokens` 字段，上表不把缺失解释为测得的零。`temperature=0` 在 thinking mode 按 Provider 文档无效，而在非思考模式生效，因此非思考与有效 sampling 参数无法完全分离；但失败调用的 reasoning-token 明细已经足以确认 2048 耗尽的位置。3072 探针没有任何调用实际超过旧上限，其 24/24 不能作为加预算有效的因果证据。

P2-v1/v2 的质量回退使“关闭 thinking 即可 promotion”被排除。v3 增加的规则来自多个类别的重复输出：只规划用户明确需要的证据关系，不为假设结果额外安排 Tool；单步只建议一个 Tool；schema 与 SQL 分开；实体先 lexical，semantic 只能在锚定证据不足时补充。没有项目或人名字面量，也没有修改 parser、Router 或 Tool availability。v3 的 24/24 是探索性结果，正式交错五重复与盲审尚需完成。

## 未确定

- 旧 P1 输入比 P0 长是否增加 reasoning 长度或截断概率；目前只证实 P1-B 缩短输入未稳定降低失败。
- Provider 随机性、cache/时间漂移与规则位置对输出的独立贡献；3–5 repeats 只缩小不确定性，不能证明 generalization。
- 人类盲审是否同意 assistant 对 v3 质量的 provisional 判断。
