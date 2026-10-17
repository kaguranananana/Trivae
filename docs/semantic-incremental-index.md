# Semantic 增量索引

## 原实现与审计结论

`LocalImportIndexUpdater` 曾要求 identity、数量、revision 全部一致才能 resume；一旦有新 Canonical revision，就调用 `rebuild(resume=False)`。`start_rebuild()` 删除所有 Chunk 和 vec0 表，随后完整消息流再次 Embedding。同快照 resume 能恢复中断，不能解决日常跨 revision 的重复计算。

已验证的分块规则保持原样：

- Parent 在 session、转发 root / 直接 parent / container 不同、相邻消息 gap 大于配置、消息数达到上限或有效字符超限时结束。gap 配置以秒表示，Canonical timestamp 以毫秒比较。
- Child 按有效字符／消息数与 overlap 切分；void 保留范围但不进入模型正文。转发短正文沿用既有独立规则。
- Parent ID 包含会话、首尾消息、版本及完整配置；Child ID 再包含自身首尾。ID 没有正文，因此同 ID 不证明输入没变；Parent 变化也不证明所有 Child 向量需要重算。
- 转发 occurrence 由 Canonical root 的 `content_json` 按现有 DFS 解析，不依赖 FTS 派生正文；内部消息 ID 是 root 加数组路径，时间过滤使用外层进入当前群的时间。
- 导入冲突仍为 first-wins：variant 不会覆盖 Canonical。只记录 conflict 且 Canonical 未变时，无语义索引工作；未来有效 Canonical 修订仍受数据库触发器追踪。

ChatLab 本机固定版本的参考审计见任务内 `research/chatlab-reference.md`。继承其 Parent/Child 纯函数、追加回退 Parent、metadata/vector 配对事务原则；其按游标和数量识别变化及历史补录全量 Embedding 不满足本次约束，未照搬。

## 变化记录与安全重切范围

Canonical 库新增 `canonical_message_changes(revision, old_session_id, old_timestamp, new_session_id, new_timestamp)`，与原有单调 revision 在同一个消息 INSERT/UPDATE/DELETE trigger 内提交。只记录变化位置，不复制正文。真实字段均未变的 UPDATE 不推进 revision。群名进入 Embedding header，因此仅当 `chat_sessions.name` 真正改变时推进 revision，并记录整个 session 失效。

`semantic_changes_baseline_revision` 记录首次安装位置追踪的水位；索引早于这个水位或日志缺失时显式拒绝增量，并要求 rebuild，不能猜测旧范围。不会自动清除变更历史。

`semantic_change_ranges()` 合并当前消息时间与变更的旧、新时间位置。沿相邻间隔不超过 `parent_gap_seconds * 1000` 的连通段向两侧扩展，直到独立时间 gap 或 session 边界。被删除的桥接消息仍作为虚拟时间点参加扩展，所以删除桥接／连续多条消息也不会漏掉原段另一侧。移动消息同时处理旧、新位置与会话。

从段首按现有 Chunker 重切至段末。消息数／字符上限变化可能让 Parent 分界向后传播，故不能只重切单条消息或原 Parent；段外自然 gap 与 Parent 累积状态无关，构成可证明的安全边界。段内转发树完整重放 DFS，现有容器隔离规则不变。

这采用保守的自然边界：连续长时间无大 gap 的群聊会重读较长段，但未变化输入仍复用向量。它不承诺每次只读新增消息。

## 精确复用与发布

派生索引增加 nullable `semantic_chunks.embedding_input` 与 `semantic_index_state.embedding_input_format`。保存的是 Chunker 已限制长度的实际模型输入，默认最多 6000 字符，仅用来证明向量输入相等；Citation、正文恢复与最终证据继续读 Canonical。这是对原来仅存范围元数据的必要扩展：同边界正文可改，项目又禁止内容指纹，只靠 ID 无法判断可复用性。

只有 identity 完全相同、上版状态 completed、原生／内部覆盖完整且全部输入凭据存在时，才允许作为增量基线。旧格式在下一次需要更新时完整重建一次；未完成的新格式全量构建在同快照仍使用既有 resume，跨快照先完整重建。模型／维度／pooling／query instruction／Chunker version 或 config 改变也使用完整 rebuild。CLI 的 `trivae semantic rebuild` 与 `--resume` 保留。

增量在一个 `BEGIN IMMEDIATE` 事务中执行：

1. 获得写锁后重新检查 base revision、identity 和 metadata/vector 完整性。
2. 把受影响旧块的输入及 float32 向量保存到 SQLite TEMP 表，成对删除该范围 vec0 和 metadata。
3. 用原 Chunker 生成新块；按输入全文相等从 TEMP 池取回旧向量。Parent 或 Child ID 变了但模型输入不变时，同样可以复用。
4. 只有缺失的输入调用 provider；输入全部可复用或纯 void 变化时不 preload 模型。新 metadata 与对应向量仍成对写入。
5. 再检查 Canonical revision，写入全部覆盖计数和 completed，删除 TEMP 表并提交。

未受影响范围的 vector_id、metadata、向量字节均保持原样；受影响范围重写 metadata，可重新分配内部 vector_id，因此对照实验按业务 Chunk ID 比较，不按自增 ID 比较。

存储写方法在增量事务内不再嵌套 connection context，防止隐式提前提交。真实 sqlite-vec 验证了 DELETE/INSERT 可与普通表一同回滚。Embedding 异常、KeyboardInterrupt、SystemExit 或进程直接退出均不会提交部分新索引；下次从旧发布 revision 重做受影响段。普通异常在旧状态保存 `last_error`，强停没有运行异常处理的机会。上次 completed 始终指向旧 revision，既有查询 freshness 校验会拒绝过期版本。

Canonical 与 semantic 是两个数据库，最终检查和提交不是跨库全局事务；检查后立刻发生的新 Canonical 提交仍可能使刚发布索引变旧，但检索动态比较 revision 会拒绝它，下轮处理新的变更。不能据 completed 单独声称当前数据库一定 fresh。

## 自动导入与运维

链路为 `稳定 QCE 快照 → Canonical 文件事务与位置日志 → 持久索引队列 → lexical rebuild → semantic update → queue ack`。

`auto_import_files.baseline_revision` 与原有 baseline rowid 一同在 prepare 时保存。Canonical 提交后，实际 revision 变化或新增消息均创建既有两个索引工作；零新增但改群名也不会漏排。Canonical commit 与 finish_file 之间中断，恢复按 durable batch 和 prepare revision 补回义务。多个文件／批次仍按每种索引合并一次更新。发布成功但 ack 前中断，重放相同 completed revision 直接确认，既不解析全库转发也不加载模型。

FTS 仍使用原来包含转发投影的单事务全量 rebuild，执行顺序和 CLI／launchd 参数均保持。索引错误仍由队列保存种类、尝试次数、原始错误与 traceback。

原生 `import` 或人工 SQL 修订能被 builder 的位置日志识别，但它们不自动生成 `import-once` 文件批次；只有普通入口或文件扫描而没有队列时，不会凭空触发更新。人工修订后需显式调用 Builder 更新或已有完整 rebuild CLI；不要把队列为空当成 freshness 证明。

## 验证证据（2026-10-17）

所有数据库均为独立临时库，没有对正式 Canonical、原始 JSON 或已有索引做实验。数据是合成群聊，按每 50 条形成一个自然时间段，同时新增 1 条末尾消息和 1 条历史补录。它证明计算复用与结果一致，不是生产负载质量评测。

| 指标 | 确定性 Provider | 真实 Qwen3-Embedding-0.6B |
| --- | ---: | ---: |
| 最终 Canonical 消息 | 3002 | 152 |
| 本次新增／补录 | 2 | 2 |
| 重切 Parent / Child | 2 / 12 | 2 / 12 |
| 最终有效 Child | 360 | 18 |
| 全量 Embedding 数 | 360 | 18 |
| 增量 Embedding 数 | 7 | 7 |
| 复用已有向量 | 353 | 11 |
| 全量总耗时 | 336.83 ms | 8803.01 ms |
| 增量总耗时 | 14.24 ms | 3772.92 ms |
| 全量／增量 Embedding 耗时 | 2.26 / 0.04 ms | 8788.63 / 3762.98 ms |
| 全量／增量写入耗时 | 55.50 / 1.99 ms | 7.13 / 3.16 ms |
| 元数据／向量／来源 | 全部一致 | 全部一致 |

真实模型采用现有缓存离线加载，维度 1024、normalized、last_token，真实 sqlite-vec 0.1.9。初建冷加载约 6.92 秒；上述全量和增量对比均在模型已加载后进行。该实验实际最大向量差为 0；脚本允许真实 batching 浮点舍入的绝对差不超过 1e-4。无变更批次两种实验均不 preload、不调用 document Embedding。

可复现命令（`--output` 必须是尚不存在的新文件）：

```sh
uv run --extra dev python scripts/verify_semantic_incremental.py --messages 3000 --output /tmp/semantic-fake.json
HF_HUB_OFFLINE=1 .venv/bin/python scripts/verify_semantic_incremental.py --real --messages 150 --output /tmp/semantic-real.json
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests scripts/verify_semantic_incremental.py
uv run --extra dev mypy src
```

最终样本保存为 `final-fake-benchmark.json` / `final-real-benchmark.json`，前一轮样本原样保留；不同轮次墙钟耗时有自然波动，不推导固定提升百分比。原始计数和计时见[任务验证目录](../.trellis/tasks/archive/2026-10/10-17-semantic-incremental/research/)。独立 Builder 全量对照、真实进程退出和正式自动导入工具回归分别在 `test_semantic_incremental.py`、`test_semantic_index_incremental.py`、`test_semantic_canonical_changes.py`、`test_import_index_updates.py`。

## 局限与后续触发条件

- 精确输入凭据增加派生库空间；范围内复用仍需重写 metadata/vector。只有实测 I/O 成为瓶颈时再考虑保留受影响块的内部 ID。
- 安全边界保守，长连通会话可扩大重切；若真实扫描耗时成为主要成本，再引入经全量对照证明的 Parent 边界重新汇合优化。
- `count_forwarded_messages()` 仍会在 revision 改变后扫描全库转发 root JSON；此次重点减少历史 Embedding，并未把所有 Canonical 读取都变为局部。
- 增量持有一个 semantic 写事务直到 Embedding 完成；其他构建器等待写锁，较晚计划被拒绝。未来有实际并发写和恢复耗时需求时，再评估 durable staging，当前没有引入第二套向量索引。
- 位置日志持续增长；清理前必须明确所有派生消费者水位，不能自行按天删除。
- 未做生产库迁移或生产 Agent 重新验收；正式首次格式迁移仍有一次全量成本。已有 launchd smoke 为显式选择的测试，本次未再次注册系统任务。
