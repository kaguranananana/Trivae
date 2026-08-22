# Engineering Principles

> 本项目长期工程原则，浓缩自项目创建规范。每次开发前阅读，并遵守。
> 目标是：可验证、可定位、可维护、可迭代。

---

## 1. 根因优先，错误透明，最小修复

- 遇到异常、失败或测试不通过：先复现、定位根因、修复主链路。
- **禁止**用 fallback、降级、兼容分支、静默吞错、临时 patch 掩盖真实问题。
- 错误显式暴露，保留足够日志 / Trace 便于定位。
- 新增加重试 / fallback / 兼容逻辑前，必须有真实 Failure Case 或接口契约证明必要，并说明触发条件、适用边界、测试覆盖。

## 2. Failure Case Driven Development

所有重要优化由真实问题驱动，不先堆复杂机制再找问题：

```
发现真实问题 → 保存 Failure Case → 稳定复现 → Trace/Log 定位 → 确认 Root Cause
→ 提出候选方案 → 选择成本合理的最小方案 → Test/Evaluation → 比较修改前后 → Regression Test
```

- 普通胶水代码：契约清晰、错误显式、关键行为有测试、实现简单。
- 不要为了「看起来工程化」增加无实际价值的抽象与基础设施。

## 3. Retry / Fallback 原则（默认不加）

- 默认优先修复主链路根因；不通过 fallback / retry / 兼容分支掩盖问题。
- 仅当真实运行证明某类错误无法完全消除（外部 API 短暂失败、网络抖动、模型偶发格式错误等可恢复 transient error）时才引入。
- 引入时说明：触发条件、为什么主链路无法直接解决、最大次数/边界、失败后如何暴露错误、测试覆盖、相关指标。
- 恢复机制必须可观测，不能静默隐藏问题。

## 4. Observability

进入 Agent 开发阶段后，重要 Agent Run 应逐步具备可追踪能力（按实际架构记录）：

- request_id、User Query、Router Decision、Plan/State、Tool Calls（含参数与结果）、Retrieval Query、Retrieval Candidates / Results、Evidence Selection、Final Evidence、Context、Final Answer；
- 指标：Latency、Token Usage、Tool Call Count、Retry Count、Error Type、Model、Prompt Version。

Stage 1.9 已确认 normalized event、Failure Attribution、query-scope coverage、Error Code ownership、privacy / retention 与 Trace storage 的概念契约；具体 Python / JSON Schema、Collector / Store backend 与业务代码仍未实现。

## 5. Evaluation

- 端到端评测以 Evaluation Case Bundle 为 canonical truth，固定 Case、Dataset Snapshot、Data Access Scope 与受控 Variant 条件，验证真实问题和真实改动。
- Reference 必须针对具体 Finding 说明 `exhaustive / partial / unknown` annotation completeness 与 provenance；Case 级完整度只能派生，partial / unknown Finding 不得机械推导强 Precision / Recall。
- Router / Planner 先在除 Planner 是否介入及其 guidance 外其他条件完全相同的 forced standard / forced planned 路径上测 Planner Utility，再评价 Router 是否能识别值得调用 Planner 的 Case；不能只看 Route accuracy，也不强制没有明显收益的 Case 填 `expectedRoute`。
- 质量轴（Finding Correctness、Evidence Completeness、Groundedness、Uncertainty Calibration、Relevance）与 Trace / latency / token / Tool Call 等模块诊断分开，不压成单一总分。
- Baseline 必须是 pinned Controlled Variant，Candidate 只声明显式 diff；Core / Regression 通过 versioned Suite 演进并保留历史结果。
- paired quality review 优先 blind、随机 A/B、同 rubric、同 Evidence visibility；Judge 不是唯一真相源，关键争议转人工。
- 数值 threshold 与参数必须等待真实 baseline、随机方差、评审一致性与 Failure Cost；不能用 ChatLab 经验参数或静态 Seed 伪造质量结论。

## 6. 关键模块开发前必须回答的 7 问

适用于 Router、Retrieval、Tool、Agent Runtime、Context、Evidence、Evaluation 等关键模块：

1. **Responsibility**：解决什么问题？为什么需要？职责边界？输入输出？
2. **Failure Cases**：可能怎么失败？哪些输入易失败？边界情况？模型不稳定时的表现？
3. **Observability**：出错后如何发现？日志在哪？有无 Trace？能否看到中间状态？
4. **Failure Attribution**：错误属于哪一层（Router / Retrieval / Tool Selection / Tool Arguments / Planning / Context / Evidence Selection / Evidence / Answer Generation / External Service）？
5. **Technical Decision**：原方案？问题？候选？为何选择？适不适合当前规模？trade-off？
6. **Verification**：通过 Test / Evaluation / Metric / Regression 证明改善，避免仅凭主观感觉。
7. **Regression**：重要修复后保存 Failure Case、加入测试集、增加 Regression Test，必要时增加 observability / validation / guardrail。

## 7. 实现任务的证据化面试防守记录

这条原则适用于以后所有实现任务，尤其是 Retrieval、Tool、Agent Runtime、Context、Evidence、Evaluation、Storage 等关键模块。实现文档除了说明“做了什么”，还必须能够基于真实证据回答“为什么这样设计、有哪些替代方案、失败如何定位、如何证明修改有效、规模扩大后会怎样、未来何时演进”。

这不是面试话术要求，也不要求为了面试制造复杂度。只记录 architecture decision、implementation、test、真实数据运行、benchmark、evaluation 或真实 Failure Case 能证明的内容；没有证据时必须明确写成未知、`anticipated risk` 或 `waiting for evaluation evidence`，不得虚构 Failure Case、性能数字或设计过程。

每个实现任务完成时，必须在实现/验证/评审记录中覆盖：Problem / Motivation、Design Rationale（problem → considered options → selected option → reason → trade-off）、Why not、Failure Cases、Evaluation / Evidence、Observability / Debugging、Scale / Performance、Boundary / Ownership、Evolution，以及简短的 `Interview Defense Notes` 事实索引。必须区分 `measured fact` 与 `engineering expectation`，也必须区分 `real failure`、`regression test case` 与 `anticipated risk`，以及 `permanently rejected` 与 `currently unnecessary / waiting for evaluation evidence`；后者需要写出 reconsideration trigger。

质量门禁是：面试官连续追问“为什么、替代方案、失败、验证、debug、规模、扩展”时，仓库中的代码、测试和文档能指向事实来源；不能只回答“代码就是这么写的”，也不能靠虚构项目经历补齐。

面试回答的默认叙事必须以 Trivae 自己的问题、约束、实现、测试和真实数据证据为中心，不把 ChatLab、参考实现或“参考某个成熟开源项目”作为设计理由、技术结论或答案主线。内部文档可以保留真实的参考来源；如果面试官直接询问参考来源，必须如实说明，并进一步解释 Trivae 的适配、取舍和验证，不能伪造完全独立的原创来源。

详细模板见 [Interview Defense Evidence](./interview-defense.md)。

## 8. 最小可验证改动

- 发现问题：复现 → 定位 → 假设 → 最小修改 → 验证。
- 只有现有结构明显阻碍正确性、可维护性或迭代时，才提出结构性调整。
- 重大问题按 architecture.md 的规则处理（记录问题，停止改动，等待架构决策）。

## 9. 禁止事项（当前阶段 / 未定架构时）

未由正式设计文档定义的内容（模块边界、数据模型、检索选型、Agent 架构、API 边界等）：

- 不自行补全，标记 `Pending architecture specification`；
- 发现已有架构重大问题：记录 `Problem / Evidence / Impact / Possible Options` 后停止对应改动，等待新决策。
