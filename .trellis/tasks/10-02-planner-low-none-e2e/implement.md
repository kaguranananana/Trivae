# 执行

1. 审计现有 Runner/Provider/Trace/8 Case/生产入口，归档结论。
2. 新增 experiment-only runner 和 provider-free tests；不编辑 src。
3. 运行 evaluation 回归、Ruff、mypy、diff check；固定代码/数据/顺序并保存 preflight。
4. 各配对一次执行，共 16 runs；每次先写 attempt、后保存完整结果，错误保留；真实请求逐个计数。
5. 生成无 treatment/耗时/token/顺序的 packet；独立 reviewer 完成全部 8 组后揭盲。
6. 分层分析、失败归因和 gate 判断；只在 C gate 执行第二阶段。
7. provider-free regression、任务文档/规范知识更新。

## 完成记录

- 第一阶段 16 runs 全部完成，63 实际 HTTP requests、16 evaluation results、16 terminal traces 对齐；两次 low Planner length 与五次 Tool alias 错误保留。
- 首次环境启动缺少仓库已锁定 semantic extra，发生在任何 logical attempt/Provider request 前；按原 lock 补齐并独立保存失败工件，未改生产实现。
- 独立 reviewer 完成全部判断后才揭盲；原始判断不改。揭盲后的完整 ToolResult 核验单列，修正 reviewer 对“北京”支持的断言。
- Gate A 停止，不追加第二阶段或全量 Development。生产本轮前已默认 none，本轮未切换配置。
- 自动分析与冻结判断/人工解释合并均已 provider-free 重算；结果一致。工程检查见 validation.md，完整结果见 report.md。
