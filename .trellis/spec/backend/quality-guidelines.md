# Quality Guidelines

> 质量与测试长期原则（源自工程原则第 2、5、6、7 节）。
> lint / type-check / 测试工具链将在业务实现任务启动前确定（当前仍不安装业务依赖）。

---

## 测试要求

- 关键行为必须有测试；测试失败优先检查实现。禁止仅为让错误实现通过而修改测试或增加特殊分支；若需求、接口契约或正式架构发生变化，或测试本身存在错误，可以同步更新测试，并记录原因。
- 重要修复：保存 Failure Case → 加入测试集 → Regression Test。
- Evaluation 优先用真实指标（Recall@K、Task Success Rate 等），避免仅凭主观感觉。
- 固定 Evaluation Set 逐步建立；不制造无意义指标。

## 禁止模式

- 为「看起来工程化」增加无实际价值的抽象与基础设施。
- 针对单个样例的特殊规则 / 兼容分支。
- 静默吞错（见 error-handling.md）。

## 质量闭环（关键模块）

实现 → 暴露问题 → 保存 Failure Case → 复现 → 定位 → Root Cause → 候选方案
→ 最小合理修改 → Test / Evaluation → 验证改善 → Regression Test → 文档沉淀

## 代码评审

- 检查是否遵守本层各指南与工程原则。
- 检查是否涉及 Pending 架构事项（architecture.md）而未经授权自行决定。

## Pending architecture specification

- Evaluation 架构（评估框架、指标口径）
- 工具链具体选型（formatter / linter / test runner 版本与配置）
