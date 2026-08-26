# Failure Cases and Review Taxonomy

## Retrieval Coverage Failure

### BROAD_LEXICAL_CAPPED_AT_100

- 条件：inventory/enumeration 查询真实命中 >100，但 provider/trusted/capability 的统一默认限制只允许 100。
- 结果：候选 evidence 在进入 model projection 前已丢失；扩大 Tool Result token budget无法恢复。
- 验证：150/300 条 synthetic FTS 与真实 archive 100/300/1000 benchmark。

### MISSING_EXPLICIT_RESOURCE

- 条件：明确存在的 joye Agent 入门指南 URL 没有进入最终回答。
- Before：回答称“博客无链接可查”。
- 验证：After Trace 中检索到该 URL，projection 可见，最终回答保留原链接。

### ENUMERATION_INCOMPLETE

- 条件：要求“所有/有哪些”时漏掉仅名称、无 URL 的项目，或在 partial/truncated 状态下冒充完整列表。
- 验证：DeepSeek positive control 与综合资源 Case。

## Claim Grounding Failure

### MENTION_TO_RECOMMENDATION

链接或资源在群里出现，只支持“提及/分享”；没有推荐语或使用评价时，不能升级成“有价值/大家推荐”。

### INTENT_TO_ACTUAL_USE

“准备测”“发起测试”“想试用”不能证明已完成安装、运行或实际使用。

### REVIEW_TO_PERSONAL_USAGE

看过他人产出并评价不能证明本人亲自安装/使用。taste-skill Before 的“二人均实际使用过”属于此类。

### HIT_COUNT_TO_UNIQUE_ENTITY_COUNT

31 条消息命中不等于 31 个唯一 GitHub 项目；同一实体可能多次出现，一条消息也可能包含多个实体。

### PARTIAL_TO_NEGATIVE_ASSERTION

retrieval 或 model projection 为 partial/truncated 时，证据只说明“当前结果未见”，不能断言“群里没有/不存在/没有链接”。

## Boundary

扩大 lexical recall 只能解决候选缺失，不能自动解决 evidence-to-claim entailment。After 若 evidence 已覆盖但模型仍触发上述 Grounding Failure，应：

1. 保留 Trace 与具体 claim/evidence；
2. 标记为下一独立 Failure Case；
3. 不继续增加 candidate、不加入 query 特例、不重构 Evidence 系统；
4. 交由用户决定是否开启下一阶段。

## Review dimensions

每条真实 run 分别评审：Retrieval Recall、Evidence Coverage、Citation Validity、Claim-Evidence Entailment、Enumeration Completeness、Overclaim / Unsupported Inference、User-facing Readability。`citation unresolved=0` 只证明句法引用可解析，不证明证据覆盖或 claim 蕴含成立。

## After run classification（2026-08-26）

- `trace-6ca8d89c59314618b71ad908e77fe108`（综合资源）将 lexical recall 从 Before 的 31 条消息扩大到 93 条，并按仓库/Skill/资源分组；visible answer 仍只给代表性条目，因此 `ENUMERATION_INCOMPLETE` 风险保留。
- `trace-f8436e5c895648f78683597660266ade`（Agent 学习资料）在 lexical projection truncated、semantic expansion truncated 的边界下找回并保留 joye URL，未再作“没有链接”的强否定；`MISSING_EXPLICIT_RESOURCE` 已解决，`PARTIAL_TO_NEGATIVE_ASSERTION` 未触发。
- `trace-11abb471a2384ebabe83b4b93bfbed0a`（taste-skill）明确把阿鑫的测试行为与他人对产出的评价分开，未把 joye 查看/评价升级为个人安装运行；本次未触发 `INTENT_TO_ACTUAL_USE` 或 `REVIEW_TO_PERSONAL_USAGE`。
- `trace-cb18866a6ded4196b0e861fa6cb3709c`（DeepSeek）lexical coverage 完整，但最终正文漏掉 name-only 的 `deepseek helan` 与 dsh-web-ui/整合包；`ENUMERATION_INCOMPLETE` 是当前 positive-control 的剩余问题。

这些结果说明 candidate recall 的修复已生效，但 `citation unresolved=0` 仍不能替代 claim entailment 或实体枚举正确性。后续应以带实体/claim 标注的独立评估触发 Evidence/Claim Grounding 改造，而不是继续扩大 lexical 或加入四题特例。
