# F-DEPTH-01 — Final Answer 过度概述

## 复现

- 场景：真实 Web UI、全部聊天 Scope、同一 canonical SQLite、同一 OpenCode Go / DeepSeek V4 Flash Provider。
- 最小 Case：`关于 TDD 先写测试还是先分析代码的那段讨论，来龙去脉是什么？`
- 基线 Trace：`trace-794897e44b5046b0b53edde0defe7336`。
- Retrieval：semantic 100/20（partial/truncated）、lexical 10/2、context 41；projection 没有 omission。
- Final：4 个 evidence、17 个 validated citations、finalization valid、正文 549；页面只保留起因、双方立场、结果的短概括。

期望是覆盖证据支持的起因、讨论发展、双方立场、折中/未决项，并为重要事实保留 citation；不是要求固定字数或固定 section 数。

## 根因

这是 C 为主、D 为辅：

1. Retrieval 和 Tool Result 已经包含多组独立讨论证据，AQ6 的 projection omission 为 0，排除 A/B 为主要根因。
2. 旧 `prompt.py` 同时要求 JSON artifact compact、每个 distinct finding 一个 claim、宽泛问题 exactly one grouped claim、concise claims，并要求为了闭合 JSON 缩短 claim/finding。
3. `ModelAnswerClaim.text` 又被 `compile_model_answer_candidate()` 直接映射为 `AnswerContentBlock.text`，随后原样进入 `AnswerArtifact.answer_text` 和 Web `answer.completed`。所以 bookkeeping 的 compact 要求会直接压缩用户正文。
4. Host finalizer 没有丢掉正常正文：修复前后 candidate text、content block text、DOM 逐层相等；E/F 没有证据。

## 修复

- 去掉固定 grouped claim、固定 URL/代表项数量以及“为闭合 JSON 缩短 claim text”的指令。
- 明确 claim text 是用户可读正文；让回答随问题复杂度覆盖独立 finding、参与者、顺序、资源、差异和限制。
- 保留 evidence source handle 上限、current-run provenance、scope enforcement、partial/truncated propagation、trusted hydration 和不倾倒 transcript 的约束。
- 新增 candidate claim 数和文本长度 Trace 指标；只保存形状，不保存模型正文。
- 没有改 temperature、max output tokens、Citation Binding 或 Web renderer。

## 回归

- 修复后 AQ6：`trace-52f1fc16326b40759ea84597087cf71d`，5 claims、5 content blocks、793 正文、29 citations、valid；DOM 五段正文长度与 Trace 一致。
- 修复后 AQ7：`trace-13b02f63aff84b9ea2a8a54e3afa21bb`，6 claims、1598 正文、38 citations、valid；页面按类别归纳并说明限制。
- 修复后 AQ1 成功重跑：`trace-1c73b89e6cb44b0e87e94f47ea95d7d2`，7 claims、1295 正文、39 citations、valid。
- 简单事实回归：`trace-5401abd68fe24b0f8b7d0022f2eb3737`，1 claim、219 正文、2 citations、valid，证明没有 universal verbose。
- 最后一次 Trace 字段布局修复后，AQ6 `trace-d664f68f13824ade8ab209e153ccaa0e` 的 `answer_shape` 为 4 claims/4 content blocks，19 citations，0 projection omission/truncation；简单事实 `trace-461335012f294b14826ffb574041d53b` 为 1 claim/224 字符/2 citations，证明诊断字段没有破坏原有 Trace 正文快照或简洁事实回答。

## 回归测试

- `test_final_synthesis_prompt_adapts_answer_depth_without_compressing_prose`
- `test_model_candidate_preserves_independent_answer_prose_and_citations`
- `test_answer_candidate_observation_keeps_only_shape_metrics`
