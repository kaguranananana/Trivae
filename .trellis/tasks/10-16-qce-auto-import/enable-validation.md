# 2026-10-17 正式调度启用验证

用户在 main 合并后明确要求启动调度，覆盖最初暂不启用约束。开发继续使用独立 worktree / codex/qce-enable-schedule，主工作区已有无关改动保持原样。

## 启用前验证

- `uv run --with tqdm pytest -q --tb=short`：1104 passed、1 skipped，23.45s；唯一 skip 为 opt-in 真实 launchd smoke（原独立阶段已通过）。
- `uv run ruff check src tests scripts/macos/launchd_import.py`：通过。
- `uv run mypy src`：128 source files，通过。
- 独立只读复核：未发现本轮新增阻塞；updater 专项 5 passed。未改动转发/索引/Evidence/Citation 底层。
- 定向 47 passed、1 skipped：真实 FTS/语义构建器至 Agent 工具、转发内部正文、无变更/纯重复不构建、embedding 部分提交失败后的同快照续建、新水位重建、提交后队列确认恢复、CLI 显式更新与只读状态。
- 新测试首轮发现的两处测试自身错误已修正：正式 readiness 的完成值为 completed；mock 必须先保存原 rebuild，避免 side_effect 引用 mock 自身。真实构建器及状态契约未作特殊分支修改。

## 生产基线（只读）

2026-10-17 10:57 +08：40 个 raw JSON，Canonical 765,780 条，FTS 转发投影 12,484 条，semantic completed / revision 0 / chunk 92,288。尚无 auto_import 状态表；正式服务此前未安装也未加载。

## 索引成本与验收边界

仅新增已提交批次产生工作，每种索引一轮合并调用一次现有 builder；不是每次日历执行全量构建。现有 API 不提供跨水位局部向量增量，本轮不改写底层算法。历史本机续建 72,184 个向量曾耗时约 5h13m；本轮若触发全量构建可能长期 building，不据 loaded 或 Canonical 完成宣称语义已可检索。

## 实际安装和首轮执行

2026-10-17 11:06:21 +08 从 main 以正式 `.venv/bin/python` 安装并 bootstrap `gui/501/com.trivae.import-once`，结果 enabled=true。已安装 LaunchAgents plist，StartCalendarInterval 含 10:30 / 22:30，WorkingDirectory / raw / DB 均为主项目绝对路径，携带 --update-indexes 和 HF_HUB_OFFLINE=1；RunAtLoad / KeepAlive / ThrottleInterval=300 均已加载。

首启曾停在 Python 读取虚拟环境文件；`sample` 定位到 getpath_readlines / fopen，系统 tccd 的同一请求 396.1120 显示 Downloads 授权提示，11:07:09 authValue=2 后进程继续。没有绕过/改写 TCC；11:07:09.991 创建运行记录 477c0701075e4fa2b7a9c4990b616af6，state=running / runs=1 / pid=81092。

11:08:47 +08 已处理 39/40 文件，28 个本次 completed batch 新增 23,087 条、重复 447,072 条、error_count=0；其余为历史核验接管。两个索引各有 15 个 committed batch 待办，尚在文件处理阶段，不能称新消息已通过语义检索。

11:09:48 +08 全部 40/40 文件 completed；29 个本次批次 completed，新增 23,087 / duplicate 448,949 / error_count 0。11 个历史文件核验后接管；Canonical 总计 788,867。两个索引各处理 15 个实际新增批次，未因 14 个纯重复批次创建额外索引工作。

FTS 在 11:09:14 完成一次构建，耗时 26.586s：788,867 Canonical + 12,847 forwarded = 801,714 行，所有 lexical 工作 completed。11:10:26 用正式 LexicalSearchTool → LexicalSearchCapability → LexicalRetrieval 唯一短语搜索，命中本轮新入库真实消息 qq:1080949127:7697449274723192811（2026-10-17 09:54:29 +08），status=ok / hits=1。只读 Repository，没有创建 Application 或修改 Evaluation。

正式 RecentMessagesTool 已返回最新消息 qq:1080949127:7697450885806348823，时间 2026-10-17 10:00:44 +08。全局 coverage.partial / unexpanded_forward_content 来自既有 189 个原导出未展开转发节点，不是本轮导入失败；不掩盖该来源缺口。

语义构建在 11:09:14 启动，MPS / 本机缓存 Qwen 加载成功。11:10:26 持久状态 building，canonical_count=788,867 / revision=23,087，已处理 1,427 条 Canonical / 184 个块，last_error=null；15 个 semantic 工作仍 running。旧快照不能冒称最新，因此本轮仅确认 Canonical 和 lexical 工具已经覆盖新数据，完整 semantic / Query / Citation 生产验收仍待构建完成。任务保持 in_progress，不提前归档。

物理重启/休眠没有在共享机器强行执行；登录 RunAtLoad 与 backlog 补查机制有隔离测试，后续实际系统使用可据 runs/持久状态核验。
