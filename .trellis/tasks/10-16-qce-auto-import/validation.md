# 独立开发阶段验证

2026-10-16；基于 main@22e464f 的 codex/qce-auto-import 独立 worktree。本记录只证明独立导入/调度阶段，不表示索引集成和生产 Agent 验收完成。

## 1. Problem / Motivation
原 import 每次重读整个目录，依赖人工执行。QCE 每天导出后需要可恢复的待办发现，且不能把文件提交与可检索混成一个成功标志。

## 2. Design Rationale
复用原 import_paths，而非复制 normalize/dedup/transaction。文件系统版本判断减少重复解析；稳定副本消除解析期间源文件继续写入的竞争。处理意图与 batch 恢复填补提交后的确认窗口；运维状态同库，避免 sidecar 与 Canonical 恢复时失配。

## 3. Why not
- 无条件全量 rebuild：与现有 473,236-message baseline 的规模及用户要求不符，永久拒绝作为自动轮询行为。
- 本分支实现增量 FTS/语义底层：当前不做，等待转发检索的最终索引设计；重新考虑触发是另一任务完成后的集成阶段。
- 内容摘要：遵从用户明确约束，未新增相关实现。
- 提前启用生产：用户补充要求禁止；正式 plist 仅准备，未复制到 LaunchAgents 或 bootstrap。

## 4. Failure Cases
以下是 regression test case，除另注外不假称生产故障：
- 写入过新、两次采样间变化、复制过程中变化：deferred，零 Canonical batch；后续稳定后补偿。
- 稳定但非法 JSON：failed batch；同目录正常文件继续；失败版本下次仍检查。
- record partial：有效数据提交，错误保留，文件不标 completed；修复后幂等补足。
- 未知 write_message 异常：整文件回滚，后续文件仍导入，原 traceback 保留。
- 真实子进程分别在 Canonical commit 前、commit 后/状态前直接退出：前者重导，后者恢复批次不再解析；最后消息与批次各仅一条，两个索引工作不丢。
- 索引失败：failed 工作带异常及 attempts；不重复解析文件，只重试未完成索引。
- 索引成功返回后、确认 completed 前中断：running 工作可重放，updater 契约要求幂等。
- 持锁进程被 kill：内核释放后可继续，不靠删锁文件。
- real local reproduction：复核发现旧导入 parse 后、batch 创建前文件被覆盖时，单凭时间接管会漏导。已修复为稳定快照逐条 raw/provenance 核验；新增与同数量替换两个竞争回归均补齐消息，且原 Parser 每快照只解码一次。历史坏 JSON/来源变化仍由原入口明确失败，可信历史不再规范化或重复写入。
- test fixture correction：最初同位置覆盖测试误以为原 Store 必须新增 variant；审计确认原契约只记 conflict_count。新文件 occurrence 的 raw variant 另测通过，未改 Store。
- test fixture correction：最初语义 E2E 使用过短文本，现有 chunker 无向量，因此先报 NOT_READY；改用既有长文本 fixture 先断言确实有向量，再验证新增后 STALE。lexical Tool 层原有错误码为 CAPABILITY_UNAVAILABLE，保留该投影。
- real local environment failure：仅 dev extra 不含 tqdm，完整测试收集失败；使用 uv run --with tqdm 提供现有 process_warmup 测试所需可选依赖，未改业务代码或依赖锁文件。

## 5. Evaluation / Evidence

| 命令/场景 | 实测结果 |
| --- | --- |
| 修改前 ingestion/CLI/Application baseline | 47 passed |
| 自动导入专项 test_auto_import.py | 28 passed |
| uv run --with tqdm pytest -q | 最终 1047 passed, 1 skipped，22.31s |
| uv run ruff check src tests scripts/macos | All checks passed |
| uv run mypy src | 125 source files，Success |
| task.py validate 本 task | implement/check context 均通过 |
| git diff --check | 通过 |
| opt-in macOS launchd 测试 | 14 passed，详见 validation-launchd.md |
| 正式 prepare + plutil -lint | prepared=true、installed=false、loaded=false，plist OK |
| 独立只读复核 | 原 P1 历史接管竞争已关闭；5 项历史专项通过；无其他确定问题 |

CLI→Canonical→Agent 工具验证使用临时数据库：新增 m2 提交后 get_recent_messages 返回 m1/m2；旧 FTS5 返回明确 CAPABILITY_UNAVAILABLE/stale，语义返回 SEMANTIC_INDEX_STALE；两个 pending 工作保留。此结果证明未假装已完成检索更新，未执行真实 Provider/LLM 请求。

## 6. Observability / Debugging
stdout 是包含 run_id、每文件 outcome、原 batch summary 和索引工作列表的 JSON；stderr 保留未知导入/索引异常 traceback。只读 --status 提供 last_run、unfinished_files、pending_indexes。文件/批次/索引错误可以分别定位，不把 loaded 等同业务完成。

## 7. Scale / Performance
已知仓库基线为 473,236 条 Canonical 消息，来自既有 spec，不是本次生产测量。新扫描只做文件 stat、每文件批次查询及新增快照；不会为未变文件读 JSON，也不调用全表索引 rebuild。代表性大规模新导入吞吐、磁盘峰值和最终增量索引耗时本次未测，不报告性能提升百分比。

## 8. Boundary / Ownership
本任务拥有文件待办、稳定输入、状态恢复、CLI 和调度；SharedImporter/Parser/Canonical 仍拥有消息语义和事务。没有修改 TrivaeApplication、FTS/semantic/Evidence/Citation 核心，也没有操作另一会话工作区、生产 SQLite、原始 JSON 或冻结 Evaluation。共享源码仅在 cli.py 添加两个薄挂接点。

## 9. Evolution / Integration
待转发检索任务完成后核对外层 inserted_count 与内部记录实际变更、实现并接入幂等 updater、统一其他写入窗口，再验收新消息/迟到消息/内部转发的 Canonical、两个索引和 Agent Citation。正式 plist 目前指向本 worktree 的虚拟环境，集成路径确定后必须重新生成。
物理重启/休眠没有强制执行；SQLite 重启恢复和重新 bootstrap 已测，系统睡眠唤醒合并日历事件依据本机手册。真实任务保持未启用。

## 10. Evidence Index
- 为什么复用稳定快照：auto_import.py 与采样/复制/源文件继续变化测试。
- 为什么确认状态后置：sqlite_auto_import.py 的 prepare/recover/finish_file 与真实子进程退出测试。
- 为什么队列不代表检索已就绪：AutoImportReport 与 CLI→Agent stale 回归。
- 为什么登录补查不会依赖某个时间窗：全目录扫描与 delayed/backlog 测试。
- 调度实际可运行的证据：validation-launchd.md 的唯一测试 label、退出码、日历、Throttle 和卸载事实。
