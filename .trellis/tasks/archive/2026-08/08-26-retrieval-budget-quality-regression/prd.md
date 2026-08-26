# Retrieval Budget / Tool Result Budget 调整与真实回答质量回归

## Goal

把当前由统一 `DEFAULT_RESULT_LIMIT=100` 间接绑定的 lexical candidate、semantic result、context expansion 与 Tool Result/model projection 预算拆成含义清晰、分别受 Host 验证的有界预算，并用真实 QQ archive 的四条原始问题验证 broad recall 与最终回答质量。

本任务不是把统一常量机械改成 `1000`，也不以 `completed` 或 `citation unresolved=0` 代替事实正确性验收。

## In Scope

- 审计 Provider schema、Capability、ExecutionScope、retrieval、context expansion、Evidence transport、model projection、Trace、Evaluation 中的所有相关限制。
- lexical 默认 candidate budget 提升至适合 inventory/enumeration 的规模，并保留可信 hard cap。
- semantic 默认与 hard cap 保持小规模，且不改变 `dense_top_k` 的内部候选语义。
- context expansion 保证 direct hit 优先，且不会对大量 direct hit 逐条做无收益扩展。
- canonical Tool Result 保留完整、受类型约束的检索记录；进入模型的 projection 继续受独立 16k token budget 限制。
- projection 超预算时显式记录 omitted/truncated/partial 等价信息，不静默丢失。
- Provider schema 与 Capability 双层 enforcement 均保留。
- Prompt contract 区分提及、推荐、自荐、使用意图、实际使用、查看产出与个人使用。
- Evaluation 默认维度与失败标签覆盖需求指定的七个质量维度和七类 Failure Label。
- 先新增/更新 regression tests，再做最小实现。
- 在真实 SQLite archive 上记录 100/300/1000 candidate 的分层性能数据。
- 用可恢复的原始 wording 重跑四条真实问题，产出 Before/After 与人工质量判断。
- 更新 Trellis 文档与 `interview-defense.md`，创建独立分支并提交，不合并到 `main`。

## Out of Scope

- RRF、reranker、HyDE、multi-query expansion、query translation、synonym expansion。
- 新 Vector DB、新模型、模型 registry、自动 citation repair。
- silent retry、silent fallback、降级或隐藏错误。
- 大规模 Runtime/Evidence 重构，或完整复刻 ChatLab `retrieve_chat_evidence`。
- 新 Multi-Agent。
- 把检索改成一次无界返回全库。
- 在没有真实 Failure Case 前继续扩大 semantic Top-K 或修改现有 semantic 排序行为。
- 为修复 claim grounding 而加入针对四条问题的特例规则。

## Functional Requirements

### Independent budgets

- lexical 默认 candidate limit 为 `1000`。
- lexical hard cap 为 `5000`；所有模型输入均由 Host 二次验证，不允许无界查询。
- semantic 默认 result limit 为 `10`。
- semantic hard cap 为 `20`。
- `dense_top_k` 保持独立内部 ANN candidate 参数，默认 `40`，不因 semantic result limit 缩为 10/20，也不因 lexical 增大而增大。
- `ExecutionScope.max_results` 继续作为 trusted umbrella ceiling，但不能代替各 Tool 自身的 hard cap。
- SQL/member 等非 lexical 工具不得因 umbrella ceiling 增大而同步放宽。

### Context expansion

- broad inventory guidance 继续要求 `context_before=0`、`context_after=0`。
- context expansion 后的直接命中不得被邻居消息挤掉。
- 当 direct hits 已占满结果容量时，不执行不会进入结果的邻居读取。
- 有剩余容量时，只对稳定排序后的前 `20` 个 direct hits 自动扩展邻居；最终 semantic/context message 上限继续为 `100`。
- Trace/metadata 能区分 direct hit、context message、扩展来源数量与扩展预算。

### Tool Result and model projection

- `DEFAULT_TOOL_RESULT_TOKEN_BUDGET` 保持固定 `16_000`；本任务不引入模型 context registry。
- 文档明确 16k 分别约占 32k/64k/128k context 的 50%/25%/12.5%，并说明它只是当前固定边界。
- canonical Evidence transport 的 message 容量允许 lexical hard cap；structured/value 数据继续保留较小的独立上限，不随 lexical 放宽到 5000。
- model-visible Tool Result 超预算时，按确定性顺序先去掉非 direct-hit context、再压缩文本、最后省略尾部 direct hits，直至落入 16k。
- 省略 direct hits 时必须显式记录 omitted count、estimated tokens、truncated/partial 等价状态；citation handles 只包含模型实际可见来源。
- 若最小合法 projection 仍无法满足预算，错误显式暴露，不添加 fallback。

### Answer safety and evaluation

- Prompt 明确约束：提及不等于推荐；使用意图不等于实际使用；看过或评价产出不等于亲自安装运行；hit 数不等于唯一资源数。
- retrieval 或 model projection 为 partial/truncated 时，不允许声称“没有”“不存在”“所有资源就是这些”等强否定或穷尽结论。
- inventory answer 应区分：明确推荐/有使用评价、群内分享但无评价、自荐/求反馈/求 Star、仅提及。
- 默认质量维度至少包含：Retrieval Recall、Evidence Coverage、Citation Validity、Claim-Evidence Entailment、Enumeration Completeness、Overclaim / Unsupported Inference、User-facing Readability。
- Failure Label 至少包含：`MENTION_TO_RECOMMENDATION`、`INTENT_TO_ACTUAL_USE`、`REVIEW_TO_PERSONAL_USAGE`、`HIT_COUNT_TO_UNIQUE_ENTITY_COUNT`、`PARTIAL_TO_NEGATIVE_ASSERTION`、`MISSING_EXPLICIT_RESOURCE`、`ENUMERATION_INCOMPLETE`。

## Real Quality Cases

### Case A：综合 GitHub / Skills / 资源

- 原始问题：`最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西`
- Before Trace：`trace-0f20c501badd495f8cc9064439ae6327`。
- Baseline 约 6～6.5/10。
- 验收：Recall 明显改善；不得把 31 个消息 hit 表述为 31 个唯一项目；不得把提及、自荐、求 Star、链接分享统一概括为“有价值/推荐”。

### Case B：Agent 学习资料

- 原始问题：`最近一个月群里推荐过哪些 Agent 学习资料？`
- Before Trace：`trace-0b2409b0c5104cf78b57004ac949b8be`。
- Baseline 约 7/10。
- 验收：找回并保留 `https://www.joyehuang.me/blog/20260517---agentonboardingguide/post`；不得再声称“无链接可查”；partial/truncated 时保持不确定性。

### Case C：taste-skill

- 原始问题：`群里对 taste-skill 的评价是什么？有没有人实际用过？`
- Before Trace：`trace-621002d125374e90910c2b8283927698`。
- Baseline 约 7.5/10。
- 验收：只陈述阿鑫明确发起前端设计测试、joye 看过产出并评价；不得据此断言二人均亲自安装并完整使用。

### Case D：DeepSeek 项目（positive control）

- 原始问题：`最近两周讨论过哪些 DeepSeek 相关项目？`
- Before Trace：`trace-c0b77d168967490babe7130402050bbf`。
- Baseline 约 8.5/10。
- 验收：质量不明显退化；覆盖 DeepSeek Harness、DSH plugin、`dsh-web-ui`、DSH 整合包和只有名称无 URL 的相关项目；缺 URL 时明确标注；时间范围使用可读日期。

## Non-functional Requirements

- 保持 `Model proposes / Host validates / Host records`。
- 保持 typed Capability、trusted scope、canonical Tool Result、short `source_id`、deterministic citation validation、Evidence provenance、Trace observability。
- 错误透明，禁止 fallback、降级、静默吞错或针对单个真实问题写特殊规则。
- 新增代码使用简体中文注释；关键逻辑逐行解释。
- SQLite 1000 candidate 应处于合理 interactive latency；若 context expansion 明显慢，保留分层证据并修复根因，不随意回退预算。

## Acceptance Criteria

- [x] lexical 与 semantic 不再共享统一默认 result limit。
- [x] lexical 默认 1000、hard cap 5000，>100 hit broad query 不在 100 被截断。
- [x] semantic 默认 10、hard cap 20，`dense_top_k=40` 的独立语义不变。
- [x] Provider schema maximum 与 Capability enforcement 均有测试。
- [x] direct hits 不被 context expansion 挤掉；无剩余容量时跳过无收益邻居读取。
- [x] retrieval 可返回大量 candidate，而 model projection 始终受 16k token budget 限制。
- [x] Tool Result 超预算显式 truncated，并在 Trace/record 中可观察 estimated tokens、returned/omitted 信息。
- [x] partial/truncated answer safety 有 Prompt contract/regression fixture 覆盖。
- [x] 七个 Evaluation 维度和七个 Failure Label 可用。
- [x] 原有测试与新增 regression tests 全部通过。
- [x] 真实 archive 的 100/300/1000 性能数据完整记录。
- [x] 四条原始问题均有新 Trace、tool sequence/calls/rounds、retrieval counts、token、citation 与人工答案质量记录。
- [ ] Case B 找回指定 URL；Case C 不再作“二人均实际使用”的无依据推断；Case D 的最终正文仍漏掉 name-only/DSH 相关项，待独立枚举评估。
- [x] recall 足够但 entailment/枚举仍有边界时，已明确记录为独立 Claim Grounding / Enumeration Failure 并停止扩 scope。
- [x] `interview-defense.md` 更新设计原因、Failure Case 与取舍。
- [ ] 工作在 `codex/retrieval-budget-quality-regression` 分支提交，未合并 `main`，working tree 清洁（commit 前最后一步）。

## Delivery Constraints

- 严格顺序：规范 → 审计 → ChatLab main → Before baseline → 设计 → 测试先行 → 最小实现 → 自动化测试 → SQLite benchmark → 四条真实问题 → 人工 review → Failure 分类 → 文档 → commit。
- 最终汇报严格使用用户要求的七个章节：Root Cause、最终设计、修改文件、自动化测试、真实 Before / After、仍未解决的问题、Branch / Commit。
