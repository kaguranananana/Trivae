# QCE 自动导入契约

## 1. Scope / Trigger
无人值守扫描 QCE raw 目录、持久增量导入和 launchd 调度。文件发现属于 ingestion，运维状态属于 storage，独立轻量装配属于 bootstrap。QQ 解析、Canonical 去重及最终检索实现仍由既有模块拥有。

## 2. Signatures
- `trivae import-once [--raw-dir PATH] [--database PATH] [--settle-seconds 5] [--min-age-seconds 60] [--update-indexes] [--status]`
- `run_import_once(database_path, raw_directory, *, settle_seconds=5, min_age_seconds=60, index_updater=None) -> AutoImportReport`
- `IncrementalIndexUpdater.update(index_kind, work: tuple[IndexWork, ...]) -> None`
- additive 表：`auto_import_files`（path/version/status/batch_id/baseline_rowid/baseline_revision/attempts/error）、`auto_import_index_work`（batch_id + index_kind/status/attempts/error）、`auto_import_runs`（开始/结束/摘要/错误）。
- `scripts/macos/{install,status,uninstall}-import.sh`；安装默认 prepare，只有显式 `--enable` 才注册 LaunchAgent；正式参数默认含 `--update-indexes`，可用安装参数 `--no-update-indexes` 显式选择只导入。

## 3. Contracts
- 仍调用 `SharedImporter.import_paths()`，不复制 QQ parser、dedup、transaction 或 conflict/provenance 语义。
- 版本用 device/inode/size/mtime_ns/ctime_ns；未变成功文件不解析。历史时间仅筛选候选：旧 importer 在 parse 后才 create_batch，故 mtime/ctime < started_at 也可能含未读记录。首次需原 Parser 解码稳定快照，逐条用 source_record_index 核对已有 Canonical/variant raw，并检查来源 identity；完整覆盖才接管，不重做规范化和重复写入。无法证明的历史交回 import_paths；委托 Parser 缓存该快照结果/已分类错误，避免二次解码。
- 一轮双采样共用等待；过新/变化文件 deferred。稳定二进制快照保留 basename，复制前后核对路径与打开 fd 的版本；JSON 只由既有 parser 校验解析一次。
- importer 调用前提交 importing 意图、当前 batch rowid 与 canonical revision。文件状态在 Canonical 提交后更新；重启先据水位后的已提交 batch 恢复状态和索引义务。未提交则重试。
- 状态与 Canonical 使用同一连接/数据库，只添加运维表，不修改原表。轻量入口不创建 Query/Evaluation；只在显式更新语义索引且存在待办时加载模型。
- 已提交批次实际 revision 改变或 inserted_count > 0 时创建 lexical/semantic 索引工作；零新增的群名修改同样排队，first-wins conflict 没有有效变化则不排队。索引提交后才能确认；running/failed 重放要求 updater 幂等。
- 终端默认只入库，未传 `--update-indexes` 时明确 integration_required / pending。正式调度默认传入该参数，装配既有 FTS/语义构建器；一轮每种索引合并所有持久待办为一次构建，无新增且无待办时不构建。FTS 保留全量；SemanticIndexBuilder.update() 按变更位置局部重切、精确输入复用并单事务发布。同 identity/count/revision 的 completed 索引只补确认；完整新格式基线允许跨 revision 增量，同快照未完成的新格式全量构建 resume；旧输入格式、模型/config 变化或不完整跨快照基线完整重建。具体契约见 semantic-incremental-guidelines.md。队列为空仅表示本工作队列无欠账，retrieval_readiness 仍是 not_verified，Agent 是否可检索须另行实测。
- 进程锁按 resolve 后数据库路径派生；持锁范围涵盖恢复/导入/索引。锁文件不删除，进程退出由内核释放。普通 import 尚不使用此锁，集成前须约定唯一写入窗口。
- StartCalendarInterval 每天本地 10:30/22:30；RunAtLoad 补登录积压；KeepAlive.SuccessfulExit=false + ThrottleInterval300 仅失败重试。不使用 StartInterval/WatchPaths。LaunchAgent 需用户登录。
- 更新索引的正式调度设置 `HF_HUB_OFFLINE=1`，复用已验证本机模型缓存，避免已发生的 Hub HEAD SSL EOF；缺缓存明确失败，不更换模型或降级。显式关闭索引更新的隔离任务不设置此项。
- prepare plist 放 Application Support，避免写入 LaunchAgents 导致下次登录提前启用。用户已在本轮明确授权真实启用；仍由显式 `--enable` 执行，实际运行和检索验收必须留证。

## 4. Validation & Error Matrix
| 输入/故障 | 文件/索引状态 | 退出码 |
| --- | --- | --- |
| 空目录/全部未变，且无索引欠账 | completed | 0 |
| 写入过新、采样/复制时变化 | deferred，后续重查 | 75 |
| 另一进程持锁 | 明确 IMPORT_ALREADY_RUNNING，不打开数据库 | 75 |
| 坏 JSON/record partial/文件导入异常 | failed/partial，错误和批次保留 | 1 |
| 索引 updater 异常 | failed，记录种类、批次、尝试次数和 traceback | 1 |
| 新增已提交但 updater 未连接 | index_pending / integration_required | 2 |
| --status | 只读；不存在时 not_initialized，不创建 DB | 0 |

## 5. Good / Base / Bad Cases
- Good：提交后进程退出，下一次从 durable batch 补回 completed 与两个索引工作，完全不再解析该文件。
- Base：重导同一消息的新文件保留 provenance，inserted=0，不新增索引工作。
- Bad：按上次运行时间过滤旧文件、导入前写 completed、跳过 partial、把索引 pending 当作 Agent 已命中。

## 6. Tests Required
`test_auto_import.py` 覆盖真实进程在 commit 前后退出、稳定采样/复制变化、同长覆盖保留 mtime、历史接管与 parse→batch 竞争期间新增/同数量替换、历史坏 JSON 和来源变化、延迟积压、partial/JSON/未知异常、索引失败重放、锁释放和 CLI→Canonical→Agent 工具。
`test_launchd_import.py` 覆盖 plist 类型、绝对虚拟环境、默认索引参数与离线环境、显式只入库配置、prepare 隔离、系统错误、显式启用/卸载；真实 smoke 必须使用独立 label 和临时 DB，显式关闭模型索引更新，并在 finally 卸载。
物理重启/休眠和真实索引/Agent 验收另行记录，不得用配置断言冒充实测。

## 7. Wrong vs Correct
Wrong：更新文件成功状态后再导入；每次无条件 rebuild 两个索引；默认把配置写入 LaunchAgents。

Correct：持久 importing 意图 → 稳定快照 → 原 import_paths 文件级 commit → 文件状态和新增索引义务 → 复用既有索引构建器成功后确认。正式调度默认请求索引更新，生产 updater 与转发内部记录/语义 parent 边界仍必须实际验收。
