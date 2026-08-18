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

具体 Trace Schema 由正式架构决定，当前阶段不实现。

## 5. Evaluation

- 逐步建立固定 Evaluation Set，验证真实问题和真实改动。
- 指标按模块选取真正有意义的（Router: accuracy/error rate；Retrieval: Recall@K/Precision@K；Tool: 参数校验错误率/执行成功率；Agent: 任务成功率/循环失败率；System: P95/超时率/外部失败率）。
- **不要为了指标数量制造指标**。具体 Evaluation 架构由正式设计决定。

## 6. 关键模块开发前必须回答的 7 问

适用于 Router、Retrieval、Tool、Agent Runtime、Context、Evidence、Evaluation 等关键模块：

1. **Responsibility**：解决什么问题？为什么需要？职责边界？输入输出？
2. **Failure Cases**：可能怎么失败？哪些输入易失败？边界情况？模型不稳定时的表现？
3. **Observability**：出错后如何发现？日志在哪？有无 Trace？能否看到中间状态？
4. **Failure Attribution**：错误属于哪一层（Router / Retrieval / Tool Selection / Tool Arguments / Planning / Context / Evidence Selection / Evidence / Answer Generation / External Service）？
5. **Technical Decision**：原方案？问题？候选？为何选择？适不适合当前规模？trade-off？
6. **Verification**：通过 Test / Evaluation / Metric / Regression 证明改善，避免仅凭主观感觉。
7. **Regression**：重要修复后保存 Failure Case、加入测试集、增加 Regression Test，必要时增加 observability / validation / guardrail。

## 7. 最小可验证改动

- 发现问题：复现 → 定位 → 假设 → 最小修改 → 验证。
- 只有现有结构明显阻碍正确性、可维护性或迭代时，才提出结构性调整。
- 重大问题按 architecture.md 的规则处理（记录问题，停止改动，等待架构决策）。

## 8. 禁止事项（当前阶段 / 未定架构时）

未由正式设计文档定义的内容（模块边界、数据模型、检索选型、Agent 架构、API 边界等）：

- 不自行补全，标记 `Pending architecture specification`；
- 发现已有架构重大问题：记录 `Problem / Evidence / Impact / Possible Options` 后停止对应改动，等待新决策。
