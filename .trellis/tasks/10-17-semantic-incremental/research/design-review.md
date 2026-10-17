# Research: 增量边界与原子发布审计

- Query: 安全时间段、删除桥接、转发 DFS、输入复用、源版本和发布事务是否足够？
- Scope: internal
- Date: 2026-10-17

## Findings

### Files found / Related specs

- `chunking.py`：默认 Parent gap 1200 秒、100 条、6000 字；Child 480 字/10 条，1 条 overlap。`starts_new_parent` 根据 session、直接容器 occurrence、相邻 gap、累积数/字数切分。
- `chunking.py`：`_parent_id`、`_child_id` 仅使用范围身份，不包含正文；相同 ID 不能证明向量仍然有效。
- `sqlite_read.py:874`：`_iter_forward_trees` 按 canonical 根排序后解析 Canonical JSON；`iter_forwarded_messages:898` 保留 `tree.messages` 的 DFS 顺序。`_read_forward_inventory:909` 的全库计数按 revision 缓存。
- `retrieval.py:89`：检索在 query embedding 前检查 index identity/status/count/revision，拒绝 stale。
- `sqlite_forward.py:37`：原 revision trigger 对 messages 的 INSERT/UPDATE/DELETE 递增；旧契约尚未跟踪 session 名称变化。
- `design.md`：任务当前设计由 Canonical 记录旧/新位置，范围读取，builder 重切，store 原子发布。
- 相关规范：`database-guidelines.md`、`forwarded-message-guidelines.md`、`auto-import-guidelines.md`、`engineering-principles.md`。

### Code patterns / 审计结论

1. **安全范围需到确定性 reset 边界。** 数量/字数上限不是独立边界，新增一条会把后续所有 size Parent 向后推移。对 session 内由相邻消息 gap ≤ threshold 连接的整段重切是保守且正确的；前后 gap > threshold 的段互不影响。转发根范围按外层 timestamp 选，再完整保留 DFS 与容器跳变。
2. **删除桥接消息必须覆盖两侧。** 原消息 t=0、G、2G，删除 G 后两侧变成新 gap 2G。不能只选删除位置附近的一个新连通分量；必须从旧位置同时纳入左右距离 ≤G 的 surviving seeds（再扩展各自分量），并使旧 Chunk 的时间范围被删除。多次删改应使用全部旧/新位置的并集；为空仍应有可删除旧行的历史位置范围。
3. **转发不能按内部原始时间选范围。** 所有子 occurrence 的检索 scope 使用 canonical 根外层时间。A(容器 X) → B(嵌套容器 Y) → C(容器 X) 的 DFS 容器跳变会强制新 Parent；不能将 X 下两个非相邻片段重分组。
4. **精确有界输入可证明向量复用。** 模型身份与 Chunker identity 相同、embedding_input 完全相同，即可保留同一输入的向量；Parent/Child ID 变化不要求重算同一输入。复制向量时必须写新 metadata，不能沿用旧范围、计数或 source IDs。无正文凭据的旧文件必须一次迁移建立凭据。
5. **完整 base 是增量前提。** 只有已 completed 的 base 可以沿用未受影响部分。失败/partial 全量构建可能具有输入列和匹配 identity，却没有覆盖全部历史；相同 revision 应走 resume，不同 revision 必须完整重建（该原因确有必要）。不能对不完整 base 仅处理新增范围后宣布 completed。已通知 root 添加回归。
6. **整次发布必须有单一外层事务。** BEGIN IMMEDIATE 后的局部删除、重用/新写、完成 metadata 必须共享一笔事务；现有 insert_chunks/update_progress/finish 的 connection context manager 会单独 commit，需要 store 明确关闭嵌套 commit。禁止在外层事务中使用会隐式 commit 的 executescript。
7. **版本检测必须读到新提交。** Canonical 源与 Semantic DB 分离，末尾 revision 校验必须在耗尽旧 cursor 后读取当前已提交版本；若显式源 read transaction 固定快照，单纯重复读取同一快照不能检测并发写入。校验完成后又发生 canonical 写入，发布仍标旧 revision，检索会因 revision 不同拒绝，不能标成新源版本。
8. **失败状态不损坏旧发布。** 增量异常/强停回滚 metadata、向量与 published revision；last_error 可另事务记录但不要把旧 completed 水位覆盖成目标 revision。队列 ack 在成功 commit 后，重放相同 completed revision 应不加载模型。
9. **相同输入同批内重复也应复用。** temporary reuse pool 或已写新增行应允许同一次更新中新 Chunk 共享同一输入已有向量，避免在没有初始缓存时重复 embedding；正确性不依赖该优化。

### SQLite-vec 实证

命令使用 `.venv/bin/python`、`sqlite3.connect(':memory:')`、`sqlite_vec.load`，创建一张 metadata 和 vec0 float[2]，先提交 `(id=1, old, [1,0])`。在 BEGIN IMMEDIATE 内删旧插新 `(id=2, new, [0,1])`，主动抛 RuntimeError 后 rollback，再用同序列正常 commit。

实测 SQLite **3.50.4**、sqlite-vec **v0.1.9**：

- rollback 后 metadata=`[(1, 'old')]`，vec=`[(1, (1.0, 0.0))]`；
- commit 后 metadata=`[(2, 'new')]`，vec=`[(2, (0.0, 1.0))]`。

这验证局部 DELETE/INSERT 支持普通 SQLite 事务回滚；仍须实际 store regression 证明嵌套 helper 没有提前 commit，并加进程强停/重启用例。

## Caveats / Not Found

- 并行实现中的文件行号会移动；上述引用为审计时刻入口，不代表最终代码行号。
- 当前 `count_forwarded_messages` 每 revision 解析所有 forward 根，正确性成立但转发极多时会保留全库 JSON 扫描成本；这不是全库 embedding。可在性能证据中如实记录，未证明瓶颈前不额外设计事实副本。
- 旧 revision 安装时的 tracking-start 水位必须显式保存；没有覆盖历史 mutation 日志的旧索引不能被假设可增量。
