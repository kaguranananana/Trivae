# 设计

根因位于 Evidence 的 run-level 时间与覆盖聚合，而非工具或 Provider。选择按 resolved absolute boundary 分组，在各组内复用原 coverage 汇总和 source-local 时间校验。AnswerArtifact 增加 Host-owned retrieval_windows，保存每个独立窗口的事实。单窗既有两个字段继续有效；多窗将单值字段置空，逐窗字段完整保存，避免取首窗/最大窗或直接拼接 coverage。

损坏快照与合法多窗必须区分：每个 record 的 resolved boundary 必须和该 record 查询边界一致。继续拒绝同窗 count/coverage 不一致与引用越界。codec 对新增字段缺省为空，只用于真实存在的历史持久化记录；不增加运行时 retry/fallback。

预期文件：evidence.py（领域和聚合）、serialization.py（回放）、orchestrator.py（Trace）、test_temporal_overview_coverage.py（主链路回归）、时间规范和本任务记录。沿用单一 Query/Evidence ownership，不改变工具或数据库 schema。
