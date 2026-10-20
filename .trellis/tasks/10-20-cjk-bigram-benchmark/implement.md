# 实施顺序

- [x] 审计与历史证据定位，确认环境、snapshot 与生产 guard。
- [x] 编写隔离实验 adapter 和真实语料发现/冻结命令，使用既有 GT 与指标。
- [x] 冻结约 60 Query/Reference/Scope/配置后执行 A/B，B 校验生产 parity。
- [x] 真实 Agent 有界诊断（配对无法保证时明确声明），保存 HTTP usage 与 trace。
- [x] 分类指标、失败样例、性能代价、可复现报告与 interview-docs 索引。
- [x] 确定性测试、ruff、mypy、pytest、diff 检查；工作提交后归档/journal，统一 push（收尾步骤待执行）。

回滚：只删除本任务新增的实验目录/文件；本地数据快照与原始结果保留，不触碰生产数据库。
