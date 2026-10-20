# 历史失败驱动的端到端质量实验

2026-10-20，官方DeepSeek Flash、固定811,892条canonical快照；A=`8def8d7`、B=`3d9cc0e`，只改变具名资源充分性Prompt片段。

20题40次正式A/B + 4次关键复测，118/120次真实HTTP。候选未改善目标并出现退化，已拒绝，生产保留基线。人工质量结论仍unavailable；这里的Case来自历史Development，不是fresh/blind Holdout。

- [历史审计](../../../interview-docs/Evaluation历史失败审计-20261020.md)
- [A/B与复测报告](../../../interview-docs/Evaluation端到端质量实验-20261020.md)
- [独立验证与失败](../../../interview-docs/Evaluation独立验证-20261020.md)
- [简历证据与面试](../../../interview-docs/Evaluation优化-证据账本与面试.md)
- [逐题脱敏统计](metrics.json)

完整私有Snapshot、AnswerArtifact、Trace、Evaluation SQLite、ReviewPacket及HTTP账本留在ignored `data/evaluation/quality-optimization-20261020/`。公开仓库可复现工具和计算流程；真实质量重放仍需要有权访问相同私有数据，不能声称公开克隆即可重现语料实验。
