# Semantic 增量索引

## 目标与约束
少量 Canonical 变更后只重切受影响范围并复用未变化向量；保留完整 rebuild/resume CLI。完成审计、实现、回归、性能对照、真实 Qwen + sqlite-vec 验证及提交推送。用户已明确授权自主完成所有阶段，无需中间确认。

## 已确认事实
- import_indexes.py 在 revision 改变后 rebuild(resume=False)，start_rebuild 删除全库向量。
- Parent 按 session、forward container、gap、消息数和有效字符数切分；Child ID 不含正文。
- messages 的 revision trigger 覆盖 insert/update/delete；session name 同样进入 embedding header，现有 revision 未覆盖。
- 冲突导入采用 first-wins，仅记录 variant 不改 canonical；内部消息由 root content_json 派生，不能用 inserted_count 决定变化。

## 验收
首次、重复、追加、迟到、边界传播、正文/转发修改、删除、失败/强停重放、并发修改、模型/config 变化均回归；增量与全量有效 metadata/vector/检索一致；fake 输入计数与真实 provider 证据分别记录。质量检查 pytest/ruff/mypy。生产数据与冻结 evaluation 不修改。

## 非目标
FTS 增量、Agent/Router/Planner/Evidence 改动，新向量数据库，参数重新校准。
