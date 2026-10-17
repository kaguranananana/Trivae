# 设计

## 2026-10-17 启用阶段
用户在代码合并后明确要求启动真实调度，授权覆盖初期暂不启用约束。最小缺口是默认 updater 未装配，而不是 launchd 本身。新增轻量索引装配器，直接复用既有 SQLiteLexicalIndex / SemanticIndexBuilder；CLI 增加 --update-indexes，正式 launchd 默认携带此参数并指向 main 的 Python 环境。持久队列仍仅在实际新增消息时产生工作，无变更/纯重复不构建索引。

现有底层只提供全量构建和同源水位续建，没有已验证增量 API。为遵守不自行改写转发/FTS/semantic 底层的边界，本次采用有新增才构建的既有主链路，批量待办每种索引只调用一次；不是每次日历运行都全量构建。真正的局部 FTS 更新和语义 parent 重切仍需要独立性能演进。必须明确全量语义构建的耗时，不能把本方案称为向量增量算法。

语义索引若已完成且 identity/count/revision 相同，恢复确认直接复用；相同快照的 building/failed/partial 使用既有 resume，水位变化则按新快照从头构建。失败仍保留待办、原始错误与下一次调度补偿。测试先使用独立数据库/确定性 embedding，再安装正式任务并检查首轮结果。

## 最小行为差距与所有权
现有 import 每次解析全部文件，缺少持久文件状态和无人值守入口。新增 ingestion 编排、storage 状态及 bootstrap 服务，CLI 只配置和投影。新增轻量 bootstrap/ingestion 装配入口，复用同一个 SharedImporter；不修改 TrivaeApplication、现有 importer/parser/检索算法，避免初始化 Evaluation/模型资源。

## 文件与事务
- 文件版本是设备、inode、size、mtime_ns、ctime_ns 的可解释组合，不使用内容摘要。
- 所有候选文件先采样，等待稳定观察窗口后再采样；最近仍修改的文件 deferred。
- 复制候选到保留原 basename 的临时快照，复制前后校验源文件版本；快照 JSON 只由 QQExportParser 校验、解析一次，再由 import_paths 完成事务。
- 新增 auto_import_files、auto_import_index_work、auto_import_runs 表，使用同一 Canonical 连接，只增表，不更改既有 Schema。运行表记录空目录调用、中断和终态，供排查调度是否执行。
- 调用 importer 前提交 importing 意图及该文件最新 batch rowid。调用后才记录 batch / completed。中断恢复读取该意图后已提交的 batch：存在则补写文件状态及索引工作，不存在则重试；不依赖内存 cursor。
- 历史候选为同名 QQ source 的最近 completed batch，且 mtime/ctime 都早于 started_at；这些条件只做排除，不能单独证明已读到当前版本。首次需原 Parser 解码稳定快照，按 source_record_index 流式比较每条当前记录与已有 Canonical/variant 原始 JSON，并核对来源身份。完整匹配才接管，省去逐消息规范化和重复写入；无法核验则走原 import_paths。用一次性委托 Parser 缓存解码结果或已分类异常，避免同一快照二次解析，规范化仍由原 Parser 执行。
- fcntl 非阻塞文件锁按数据库绝对路径派生；进程退出自动释放。普通 import 不共享此新锁，生产集成前需约定写入窗口。

## 索引集成依赖
- 每个实际新增的 committed batch，为 lexical / semantic 分别入持久队列；空导入不触发更新。
- updater 是窄接口：按 index kind 和持久 batch 工作更新；成功必须表示这些工作已可检索，且重放幂等。索引成功而状态未提交时，下次可重放。
- 初始隔离开发未装配 updater，只报告 integration_required 与待办；启用阶段已接既有构建器，CLI 显式 --update-indexes、正式调度默认打开。检索就绪仍由实际状态与工具验证。
- 后续 lexical 应按新增/变更外层及转发内部记录维护 FTS；semantic 需重切受影响 session 的时间 parent（含迟到消息/边界），不能仅按最后 timestamp 追加。索引 identity/version、水位和失败可读性由转发任务最终设计决定。
- 不修改 semantic stale / lexical count 校验。Agent 端到端检索断言留在集成阶段。
- 当前批次 inserted_count 是外层消息计数；若最终转发实现会在外层 duplicate 时新增/回填内部记录，必须在集成时接入实际变更信号，不能仅沿用此计数宣称内部索引同步。

## 调度与运维
StartCalendarInterval 10:30、22:30；RunAtLoad 补登录/重启后的全部积压；KeepAlive.SuccessfulExit=false + ThrottleInterval=300 只在失败/尚在写入时重试。不配置 StartInterval / WatchPaths。LaunchAgent 依赖用户登录；睡眠日历事件按系统手册在唤醒时合并一次。
安装默认只准备 plist；enable 作为集成后显式操作。独立测试 label / temp paths 验证真实 launchd，不触碰生产库。

## 失败与验证（关键边界七问）
职责是文件工作编排；失败包括写入中、坏 JSON、record partial、未知导入异常、提交后中断和索引更新失败。文件/batch/索引状态及 traceback 定位所属层。保留现有错误语义，只对用户要求的可重试工作在后续执行补偿。稳定副本比双重 JSON 解析减少重复工作；同库意图和批次恢复避免跨库一致性问题。自动化测试验证已知契约；物理重启/休眠为未执行环境场景，不假称实测。
