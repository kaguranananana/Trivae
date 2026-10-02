# 执行计划

1. 核对上轮原始有效 Plans、执行快照和当前生产源码；创建任务与固定设计。
2. 实现最小 experiment-only replay runner 与 provider-free tests。
3. 运行相关回归、Ruff、mypy；通过无网络预检后冻结正式工件。
4. 单次固定 4-run batch，逐次记录 attempts、HTTP、Trace、Answer 和 Evaluation；失败保留。
5. 核对实际输入隔离、代码/快照、请求/trace 计数；逐条复盘 Tool → Evidence → Answer。
6. 归档分析、判断边界与最小后续动作；工程回归与规范知识同步。

## 完成事实

以上步骤已完成。4 次固定重放全部完成，16 HTTP / 16 completed model turns，Planner HTTP=0；7 次真实 Tool 参数失败保留。132 个 frozen 文件执行后逐字相等。报告、manual-audit、analysis 与全部原始工件保存。

结论：原 none 两处错误未重现；相同 guidance 下观察到检索、参数、Evidence/Answer 的方差。没有把全部波动归为 Answerer 单层原因，也没有证明 Plan 质量等价。旧 Gate A 保持，没有当场修复生产逻辑或追加付费运行。

设计取舍与事实索引见 report.md：复用既有 Planner injection/EvaluationRunner/HTTPRecorder，不复制 Agent loop；保留 source_id→canonical resolver 的 ownership；下一步为独立参数契约/时间关系 Failure Case 修复。工程检查见 validation.md。
