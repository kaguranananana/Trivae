# CJK bigram v2 对照实验

以真实 Canonical 冻结快照回答原始 unicode61 到当前 v2 的召回、排序、误匹配与性能差异。不预设收益，不修改生产算法或 Prompt，不改写历史 benchmark。准备约 60 个真实语料查询，冻结查询、Scope、穷举字面 Reference 和评分口径后正式执行。复用 Evaluation 的 Case/GT/排名评分。独立数据库保证生产数据不被写入。

验收：可重放的本地私有原始产物、公开脱敏报告、总体/分类 macro 和 micro 指标及分子分母、延迟/空间/构建代价、失败样例与确定性测试、最多 40 HTTP 的真实 DeepSeek Flash Application 验证；无法严格配对时明确限制。提交代码文档、归档并推送。
