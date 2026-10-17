# 设计与审计

## Responsibility / 边界
Canonical storage 记录 mutation revision 与旧/新 session+timestamp 位置（不复制正文）；read adapter 计算安全时间段；builder 复用既有 chunker；semantic store 原子发布。自动导入仍 lexical → semantic → queue ack。

## 识别与边界证明
消息增删改记录旧/新时间位置。session name 变化记录整个 session。对每个位置扩展到 gap 大于 parent_gap_seconds 的连通时间段；消息数/字符切分可能影响该段余下全部 Parent，故从段首重放到段末。段外 gap/session/container 边界与 Parent 累积无关，可证明不会传播。转发从这些段的 canonical root 重新解析 DFS，保留容器语义。

## 向量复用
ID 不证明内容相等，父边界变化也不证明子文本改变。为精确比较，派生表新增有界 embedding_input（chunker 已限制 6000 字符），仅作向量计算的输入凭据，不用于检索证据或 citation。相同 identity 下按输入全文相等复用 vec，更新 metadata，避免 hash；这是现有仅存范围元数据的必要扩展。旧索引没有输入凭据时，仅首次迁移全量建立凭据，后续增量。不保存第二套 canonical facts 到变更表。

## 原子性 / Failure Cases
一个 semantic BEGIN IMMEDIATE 事务覆盖删除/插入/完成状态，所有 embedding 成功且 revision 未变才提交。中断回滚；旧 completed 仍指向旧 revision，检索已有 revision 校验拒绝。失败 last_error 独立写回；再次更新重新处理安全段，不全库 embedding。队列 ack 在提交后，重放已完成 revision 不加载模型。Canonical 再变显式失败，不接受混合快照。全量首次/config 变化保留原 rebuild/resume。

## Observability / Attribution / Verification
错误归属 storage/provider/source revision；原异常上抛并队列持久化。指标记录重切 parent/child、embedding、reuse、删除、读消息、加载/embedding/write/total 耗时。测试比较 chunk_id 排序的有效 metadata 与 float32 向量，忽略内部 vector_id；真实向量使用数值容差并检查检索来源。

## 技术取舍 / Why not / Evolution
不用时间戳尾追加：迟到会传播；不只按 ID 复用：同边界正文可改；不保存 hash：项目禁止；不用第二索引/影子整库：单事务能验证 vec0 回滚。连续无大 gap 的会话可能重切较长时间段，但未变输入仍复用。长事务锁住 semantic 写入，查询仍读旧提交版本并被 canonical revision 判 stale；后续有实际并发写需求再考虑持久 staging。首次迁移需要一次全量。具体实测待证据，不能预填提升比例。
