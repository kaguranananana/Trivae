# Semantic 增量发布契约

## 1. Scope / Trigger

跨 Canonical mutation、自动导入队列、Builder 和独立 sqlite-vec 的局部更新。保持现有 Chunker 规则、模型身份及 Canonical citation 回读。用户授权本次必要的 additive schema 和精确输入凭据扩展；不改变 Agent/Evidence 语义。

## 2. Signatures

- `CanonicalReadRepository.semantic_change_ranges(since_revision, gap_seconds) -> tuple[(session_id, inclusive_start | None, inclusive_end | None), ...]`
- `iter_semantic_messages(batch_size, *, scope=None)` / `iter_forwarded_messages(batch_size, *, scope=None)`：scope 时间仍 half-open。
- `SemanticIndexBuilder.update() -> SemanticBuildStats`；`rebuild(*, resume=False)` 保留。
- Store：`has_replay_inputs()`、`supports_incremental()`、`incremental_transaction(identity, count, *, base_revision, canonical_revision, forwarded_message_count)`、`prepare_incremental_ranges(ranges)`、`reusable_vectors(chunks)`。
- Canonical：`canonical_message_changes` 只存 revision、old/new session/timestamp；`semantic_changes_baseline_revision` 保存首次安装水位。
- Derived：`semantic_chunks.embedding_input TEXT NULL`、`semantic_index_state.embedding_input_format INTEGER DEFAULT 0`。全量 start 设置格式 1，打开旧库只补列，不伪造输入。

## 3. Contracts

- revision 与位置日志由同一个 trigger 原子提交；真正无变化 UPDATE 不推进 revision。群名参与输入，实际改名推进 revision 并重切整个会话。
- 旧、新 mutation 时间点和当前消息共同形成 gap 连通段，删除的桥接点不能丢弃。gap 秒数乘 1000 后比较 canonical 毫秒；`>` 才切 Parent，恰等于 gap 仍相连。段内从头重放既有 Chunker，段外独立自然 gap 保证传播终止。
- 精确模型输入全文相等才复用。Parent/Child ID 只表达边界；不使用内容指纹。输入是受长度上限约束的派生计算凭据，检索证据不读取该列。
- 增量基线必须 completed、原生/转发覆盖完整、identity 相同且具备完整格式 1 输入；未完成全量不能被局部更新补成 completed。旧格式／identity 迁移重建；同快照格式 1 的未完成全量沿用 resume。
- 一个 semantic BEGIN IMMEDIATE 内包含范围暂存、paired delete/insert、coverage、completed 和提交。各写方法不能用嵌套 connection context 提前提交。TEMP 池仅是该事务的旧输入/vec 缓存。
- 获取锁后复查 base revision 与 metadata/vector 一一对应。Canonical 版本构建中改变，抛 stale 并回滚。普通异常只在回滚后给旧状态记录 last_error；强停由 SQLite rollback journal 恢复。新 partial 内容绝不能发布为 completed。
- Canonical 和 semantic 没有跨库事务；提交后 freshness 仍由检索动态比较 identity/count/revision 保证。旧 completed revision 不等于当前可查。全量 rebuild 原有逐批持久化行为不改变。
- 空更新不读全库转发、不 preload；全部输入复用或新增 void-only 段也不加载模型。未影响向量 ID/字节保持原样。
- Stats：增量 parent_count / eligible / void 表示实际处理范围；chunk_count 为发布后总量，reused_chunk_count 为其中没有新计算的向量数。`build_mode` 区分 full/resume/incremental/unchanged；affected_message_count 含原生及转发 occurrence；affected_chunk_count 是重切输出，removed_chunk_count 是原范围删除数。

## 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| revision 早于日志安装水位／日志不连续 | RetrievalError，要求显式 rebuild；不猜测旧范围 |
| 旧输入格式／模型或 Chunker identity 变更 | 自动 update 完整重建 |
| 同快照格式 1 的失败全量 | resume，逐字段验证输入与 metadata |
| 新快照但旧全量未完成 | 完整重建，禁止沿用缺失历史 |
| metadata/vector 缺失、孤儿或计数错配 | SemanticIndexStorageError，保留根因 |
| 第二个 builder 的 base 已发布过期 | SemanticIndexStale，在写 body 前拒绝 |
| provider 失败／KeyboardInterrupt／SystemExit／强停 | 回滚新发布；恢复重切旧 revision 以后安全段 |
| 构建期间 Canonical 再变 | SemanticIndexStale；旧 rows 与水位保留 |
| 发布成功、队列 ack 前中断 | 相同 completed revision 幂等确认，零模型加载 |

## 5. Good / Base / Bad Cases

- Good：3000 条原消息，新增／补录 2 条，360 个最终 Child 中只新算 7 个，复用 353 个；与完整重建 metadata/vector/source 相同。
- Base：同文件重复导入没有有效 Canonical 变化，不创建索引工作。无关 raw payload 变化推进 revision，但全部实际输入相等时复用，零模型加载。
- Bad：仅按最新 timestamp、inserted_count、消息总数或 chunk_id 决定新计算；只重切原 Parent 而不考虑后继边界传播；删除桥接后仅看新连通段；嵌套 with connection 提前发布。

## 6. Tests Required

- `test_semantic_canonical_changes.py`：old/new、会话移动、群名、noop、事务回滚、日志缺失、多个删除桥接点、scope 转发外层时间、零新增排队及恢复。
- `test_semantic_incremental.py`：追加、迟到、边界传播、正文/void/删除/移动/转发变化与全量 oracle；逐字段 metadata、float32、检索来源；异常、并发 Canonical、真实子进程 os._exit 后重开；不完整全量及旧失败格式迁移。
- `test_semantic_index_incremental.py`：真实 vec0 rollback、原行 ID、输入相等跨 ID 复用、同 ID 新正文不复用、过期 base 拒绝、格式标记含空旧库。
- `test_import_index_updates.py`：正式 updater 多批合并，一次 update、新增/迟到均可被 Agent semantic/lexical 工具检索；ack 重放零 preload。
- `scripts/verify_semantic_incremental.py --real`：真实 Qwen 和 vec0；metadata exact、float32 最大绝对差 <=1e-4、相同 Canonical 来源，报告实测而非假定加速比例。

## 7. Wrong vs Correct

Wrong：`new_chunk.chunk_id == old_chunk.chunk_id` 就跳过模型，或者 `with connection` 在增量的每个 insert 批次提交。

Correct：identity 完全匹配后按受限输入全文相等搬用旧 vec；新的 metadata 与向量直到整次范围重切、revision 检查、coverage 完成后统一提交。
