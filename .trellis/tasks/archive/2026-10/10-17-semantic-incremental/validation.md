# 验证与交付记录

## Outcome / Problem / Motivation

根因是自动装配只允许同 identity/count/revision resume；任何新 revision 使用清空 vec0 的 rebuild。已实现实际 mutation 范围追踪、自然边界重切、精确输入复用及整次增量事务，保留完整 rebuild/resume。生产 Canonical、原始 JSON、已有索引与冻结 Evaluation 均未用于写入实验。

## Design Rationale / Why not

- timestamp 尾追加遗漏迟到与同数量修改；ID 不含正文，不能证明向量输入未变。
- Parent 消息数／字符边界可以传播，故沿旧/新位置和当前消息构成的 gap 连通段重放，删除点也作为虚拟桥接。段外 gap 是独立于 Parent 累积的安全边界。
- bounded 输入全文凭据解决无内容指纹条件下的精确比较；只作派生计算证明，不参与证据回读。
- sqlite-vec 实际支持与 metadata 同事务回滚，不需要第二数据库或整库影子索引。单事务的写锁和失败重做范围是当前代价；有真实并发/长恢复需求再考虑 staging，而非永久拒绝。
- ChatLab 本机固定版本审计见 research/chatlab-reference.md，继承适用原则，未采用按 count/cursor 识别全部变化或迟到整库 Embedding。

## Automated Evidence

最终代码：

- `uv run --extra dev pytest -q`：**1152 passed, 1 skipped in 32.72s**，exit 0。唯一 skip 是显式注册系统 LaunchAgent 的 `TRIVAE_RUN_LAUNCHD_SMOKE=1` 测试；本次未再次创建系统调度任务。
- `uv run --extra dev ruff check src tests scripts/verify_semantic_incremental.py`：All checks passed，exit 0。
- `uv run --extra dev mypy src`：128 source files，无问题，exit 0。
- `git diff --check`：exit 0。
- `python3 .trellis/scripts/task.py validate .trellis/tasks/10-17-semantic-incremental`：implement/check 各 2 条真实上下文，exit 0。
- `uv run trivae semantic rebuild --help`：正式 rebuild / --resume CLI 保留，exit 0。
- 既有 semantic/forward/auto-import baseline：71 passed in 3.95s，见 research/baseline-environment.md。

覆盖：首建、重复／无变化、尾追加、已有 Parent 内补录、历史迟到、消息数／字符边界传播、相同 timestamp／缺失 seq、删除及多个桥接删除、会话/时间移动、void、群名、转发内部修改/新增、旧输入迁移含失败旧构建、完整性错误、Embedding 异常、KeyboardInterrupt/SystemExit、子进程 os._exit、构建期间 Canonical 再变、第二 builder 过期计划拒绝、模型/config 改变、自动导入多批合并与 ack 重放。

## Measured Performance / Scale

最终样本：research/final-fake-benchmark.json、research/final-real-benchmark.json。第一轮实验文件保留，不覆盖；墙钟变化体现运行条件波动，不推断固定加速百分比。

| 事实 | 确定性 Provider + vec0 | 真实 Qwen + vec0 |
| --- | ---: | ---: |
| 原来 / 最终 Canonical | 3000 / 3002 | 150 / 152 |
| 实际新增 | 2（追加 1 / 迟到 1） | 2（追加 1 / 迟到 1） |
| 重切消息 / Parent / Child | 102 / 2 / 12 | 102 / 2 / 12 |
| 最终 Child | 360 | 18 |
| 全量 / 增量 Embedding | 360 / 7 | 18 / 7 |
| 复用向量 / 避免计算 | 353 / 353 | 11 / 11 |
| 全量 / 增量总耗时 | 336.83 / 14.24 ms | 8803.01 / 3772.92 ms |
| 全量 / 增量模型计算 | 2.26 / 0.04 ms | 8788.63 / 3762.98 ms |
| 全量 / 增量写入 | 55.50 / 1.99 ms | 7.13 / 3.16 ms |
| float32 最大绝对差 | 0 | 0 |
| metadata / 检索 Canonical 来源 | 全部一致 | 全部一致 |

真实模式命令：`HF_HUB_OFFLINE=1 .venv/bin/python scripts/verify_semantic_incremental.py --real --messages 150 --output .trellis/tasks/10-17-semantic-incremental/research/final-real-benchmark.json`，exit 0。使用正式 SentenceTransformerEmbeddingProvider、Qwen/Qwen3-Embedding-0.6B、1024 维和 sqlite-vec 0.1.9，本机已有缓存，无 Mock 代替真实模型。初建冷加载约 6.92 秒；报告的全量／增量比较均已暖模型。增量写入计时包含最终事务提交。向量 exact 比较用于 Fake；真实允许 <=1e-4 绝对误差但本次实际 0。检索实际命中新 `qq:100:appended` 并从 Canonical 恢复来源。

正式自动装配测试另证：30 个旧块上新增／补录 2 条，只有 2 个 document 输入，29 个旧 vector_id/元数据/向量保留；lexical 与 semantic Agent tool 都检索到正确 `late` 来源；两个文件只调用一次 update，发布后的 queue replay 不 preload。

## Failure Cases / Debugging

- 审计阶段发现群名进入模型 header 却未参与旧 revision，已将真实群名变化纳入同事务位置追踪；zero-insert batch 与提交后恢复均测试。
- 新增全量 oracle 首次揭示位置范围比较把配置秒误当毫秒：append 后旧 `m10..m11` Parent 留存。修复范围层的单位为 `gap_seconds * 1000`，所有 oracle 重新通过。未修改 Chunker 或削弱断言。
- 旧格式失败全量缺少输入，不能直接按新比较规则 resume；自动 update 明确迁移完整重建。新格式同源失败仍复用已完成批次。
- 最终审查修复多孤立范围尾 Parent 的 pending 累积，每段均尝试按 provider batch 上限 flush；提交成本计入增量写入时间。修改后重跑两个实验与完整测试。
- 测试初始化期间曾在存储 API 尚未写完时失败，缺失列/方法是并行实现未完成状态；整合后才做正式 gate。一次文档 CLI 核验写错 semantic-index 子命令，依据真实 --help 改为 semantic rebuild。

## Boundary / Ownership / Observability

Storage 拥有 SQL/事务与位置事实；Repository 输出范围/投影；Builder 只调用原 Chunker/Provider 并编排；Bootstrap 接入原队列。未改 Router/Planner/Evidence/Citation。异常原样上抛，普通增量错误写 old-state last_error，队列保存 attempts/error 并日志 traceback。build_mode 与 affected/removed/embedding/reused/time 指标均可查，不能把 completed 单独当作 fresh。

## Limitations / Evolution

- 自然 gap 范围保守，密集长会话可能重切很长段；输入相同仍复用。后续只有真实扫描瓶颈才考虑更细 Parent 重新汇合边界。
- 转发 inventory 在 revision 变化后仍扫描全库 root JSON；未宣称所有读取都局部。
- 单事务包含 Embedding，持有 semantic 写锁；并发写等待并验证旧 base，强停会重做受影响范围。
- 输入凭据增加派生空间；日志没有自动清理，清理必须有所有消费者水位证明。
- 人工 SQL/普通 import 会被 ledger 跟踪，但不自动形成 import-once 文件批次，需显式更新入口。生产迁移与 Agent 全链路重新验收未执行。
- 完整 rebuild 仍沿用既有清空/逐批写入及 resume，首次/格式迁移有完整成本；此次原子发布保障针对增量。

## Interview Defense Notes

事实索引：根因见 import_indexes.py 旧行为；边界证明见 design.md 与 sqlite_read.py；复用输入见 index.py；失败恢复见真实 os._exit / vec0 transaction 测试；实测见两份 final JSON；正式工具链见 test_import_index_updates.py。上述是测量事实／回归案例；长事务和日志增长属于已识别工程限制，不虚构生产事故或质量提升。

## Final Diff Review

已检查任务相关源码、测试、脚本、规范与运维文档。未暂存 .opencode/package.json、生产 lock 和用户未命名 base；未改 frozen Evaluation 或原始数据。工作提交后按约定独立归档与 journal，最后统一推送。

工作提交：`43343eae8c8cf4058cf2b0434b4be77a15c0db69`。
