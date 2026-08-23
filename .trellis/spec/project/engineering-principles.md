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

## 8. 最小可验证改动与证据化完成

- 发现问题：复现 → 定位 → 假设 → 最小修改 → 验证。
- 只有现有结构明显阻碍正确性、可维护性或迭代时，才提出结构性调整。
- 重大问题按 architecture.md 的规则处理（记录问题，停止改动，等待架构决策）。
- 每轮修改都应验证当前假设；如果没有产生新证据或改变排查策略，不重复尝试。
- 完成状态必须由与变更直接相关、可复现的证据支持，不能只依据“代码已经修改”“看起来正确”或 Agent 的自然语言声明。证据可以是 automated test、regression test、lint / type-check、命令 exit code、可复现案例、benchmark / evaluation、CLI / API 实际输出，或 diff 与既有 contract / spec 的一致性检查；按任务选择最小但真实的证据，不机械要求所有类型。
- 如果缺少可靠验证方式，先建立最小可复现 case、测试、evaluation 或验证命令；在此之前不得把任务标记为完成。若连最小验证也无法建立，应按第 10 节停止并升级。

## 9. 禁止事项（当前阶段 / 未定架构时）

未由正式设计文档定义的内容（模块边界、数据模型、检索选型、Agent 架构、API 边界等）：

- 不自行补全，标记 `Pending architecture specification`；
- 发现已有架构重大问题：记录 `Problem / Evidence / Impact / Possible Options` 后停止对应改动，等待新决策。

## 10. 有界自主与 Agent → Human 升级边界

自主闭环是执行权，不是无限设计权限。Coding Agent 只有在目标、行为边界和验收条件能由现有 task、contract、spec 或已确认 Architecture Decision 明确约束时，才应自行分析、修改、验证和迭代。默认优先继承适用于 Trivae 的 ChatLab-first 设计；实现中的局部问题不能单独成为重新设计架构的理由。

### 允许 Agent 自主闭环的范围

在满足上述前提、修改局部、风险低且存在真实验证方式时，Agent 可以自行处理：

- 局部 bug 修复；
- 已明确 contract 下的小功能与实现细节；
- 测试补充、lint / type / import 等工程问题；
- 已确认设计内的小范围重构；
- 文档与实际实现同步；
- 测试、日志或 evaluation 暴露出的局部 Failure Case。

这些事项仍必须遵守根因优先、Smallest Effective Change、错误透明和 Evidence-driven 验证原则；自主范围不授权新增无依据的 fallback、retry、兼容分支、抽象或基础设施。

### 必须停止扩大修改范围并升级给人的情况

| 边界 | 触发条件 |
| --- | --- |
| 整体架构与模块 ownership | 会改变系统整体架构、模块边界、依赖方向或职责归属 |
| 已确认决策 | 需要修改 Confirmed Architecture Decision / Technical Decision，或重新打开既有 ADR |
| Public contract / data model | 需要重大改变 public contract、API、数据模型、schema、持久化语义或兼容策略 |
| 核心行为语义 | 会改变 Router、Planner、Retrieval、Agent Runtime、Evidence / Citation 或其他核心链路的语义 |
| ChatLab 基线 | 需要偏离已确认且适用于 Trivae 的 ChatLab 设计，或不能证明当前基线不适用 |
| 重要 trade-off / 设计不确定性 | 存在多个合理方案且质量、复杂度、成本、延迟、可维护性或风险取舍重要，或 Agent 无法用现有证据判断哪种设计正确 |
| Evaluation 暴露的系统性问题 | Failure / Evaluation 结果可能要求重新设计，而不只是局部修复 |
| 不可逆或高风险操作 | 数据迁移、删除、破坏性变更，以及 security、credential、permission 边界变化 |
| 依赖与基础设施 | 需要明显的 dependency、运行时、部署或基础设施层重大变更 |
| 范围与验证边界 | 修改明显超出当前 task，连续尝试没有产生新证据，或无法建立可靠验证方式 |

遇到上述情况，Agent 可以继续做不改变外部状态的诊断、复现和证据整理，但不得沿未经决定的方向继续扩大修改。升级说明至少应包含：

```text
当前现象 → 已有证据 / Failure Case → Root Cause 判断及不确定性
→ 已尝试方案及结果 → 为什么现有设计可能不足
→ 候选方案与 trade-off → 需要人工决定的问题
```

具体的 ChatLab 继承 / 偏离、ADR Reopen、Architecture Problem Handling 和模块级 Failure Contract，分别以 [architecture.md](./architecture.md)、[technical-decisions.md](./technical-decisions.md) 及对应 ADR 为准。本原则不取消已经确认的模块级 degradation contract（例如 Router 的显式、可观测降级），也不允许 Agent 自行新增或扩大这类例外。
