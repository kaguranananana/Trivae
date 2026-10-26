# QCE 增量导出与 Trivae 导入流水线

由用户提供的 ChatGPT 脚本接入项目。仅使用 Python 标准库，调用本机 QCE API；消息入库、去重和索引复用 Trivae 正式入口。

一次运行依次执行：

1. 加进程锁后读取每群成功水位，计算到当前时间前 15 分钟的窗口。
2. 从上次成功水位前 30 分钟开始导出，跨过休眠或离线积压，不限于最近一天。
3. 记录 QCE 返回的 taskId；等待完成并核对 JSON、群号和消息条数后，原子提交该群水位。零条消息同样有效。
4. 等待新文件满足原导入器的 60 秒静置要求，再执行 `trivae import-once --update-indexes`。
5. 入库和索引成功，且所有群已补至本轮截止时间后，晚间由原有入口唤起独立日报。

导出水位说明 JSON 已成功保存；入库及索引状态继续由 SQLite 中的原有自动导入状态管理。导出成功、索引失败时保留各自状态，下次补偿。重复窗口复用项目现有消息身份去重。Canonical 与 semantic 数据库采用 WAL，使更新期间的 Web 读取保持已提交快照；未完成的新版本仍按原 readiness/freshness 契约报告，不能提前宣称就绪。在线备份使用 SQLite backup API，不能只复制主数据库文件。

## 本机配置

`config.json`、`state.json`、锁、日志和真实导出不提交到 Git。Token 每轮从 `~/.qq-chat-exporter/security.json` 读取，不复制到项目。

```sh
cp scripts/qce-incremental/config.example.json scripts/qce-incremental/config.json
# 编辑群号及 output_dir；output_dir 必须是项目 data/raw 的绝对路径。
.venv/bin/python scripts/qce-incremental/incremental_backup.py --dry-run
```

- `groups`：群号和群名。
- `initial_lookback_hours: 72`：没有成功水位时的默认首次回溯长度。
- `initial_start_time`：可选的首次 Unix 秒级起点；存在时覆盖首次回溯长度。首次有成功水位后不再使用。
- `overlap_minutes: 30`：重叠扫描边界，降低短暂延迟同步风险。
- `settle_minutes: 15`：本次只导出至当前时间前 15 分钟。
- `wait_for_api_minutes: 10`：休眠后等待连接恢复；认证、HTTP 和业务错误立即报告。
- `task_timeout_minutes: 120`：单次等待异步任务的期限；超时保存 taskId，下次查询原任务。
- `skip_resource_downloads: true`：按本机 QCE 契约跳过附件下载，保留消息结构及资源链接。
- `output_dir`：明确指向项目 raw 目录，不使用 QCE 默认目录。

本次本机配置取自 QCE 原有 8 个群任务；首次起点为 2026-10-16 00:00 +08:00，复查原批量历史导出后的区间。后续完全依赖各群成功水位。更早的历史不由这次复查覆盖，QCE 返回 completed 也不能证明 QQ 上游已同步全部历史。

## 安装与查看

```sh
# 默认只准备配置，不启动真实导出。
bash scripts/qce-incremental/install_launchd.sh --digest-label com.trivae.daily-digest

# 注册并立即补查；替换原 com.trivae.import-once 的纯入库日历。
bash scripts/qce-incremental/install_launchd.sh --digest-label com.trivae.daily-digest --enable

# 导出进度、系统任务和入库状态分别查看。
.venv/bin/python scripts/qce-incremental/incremental_backup.py --status
./scripts/macos/status-import.sh
.venv/bin/python -m trivae import-once --status
```

安装器复用 `launchd_import.py`，不再注册原脚本的 `local.qce.incremental`。每天本机时间 **10:00、22:00** 执行，`RunAtLoad` 登录补查；本机 `man launchd.plist` 明确说明休眠错过的日历事件会在唤醒后合并执行。关机期间依靠下次登录补查，不自动唤醒机器。

`KeepAlive.SuccessfulExit=false` 配合 `ThrottleInterval=300`，非零退出后约五分钟再次补偿；成功后等下个日历。配置/认证持续错误会持续记录，需要修复实际问题。原任务仍在 QCE 运行时不重复提交；已明确失败或取消的任务在后续运行重新创建。恢复旧任务后尚未赶上本次截止时间，返回 75 再补齐一次。

日志沿用 `~/Library/Logs/Trivae/com.trivae.import-once.stdout.log` 与对应 `stderr.log`。错误保留 traceback，不吞掉失败。只执行导出时直接运行脚本；要手动执行全链路，加 `--then-import --update-indexes`。`--dry-run` 不调用 QCE，也不修改水位。

移到其他项目目录或更换虚拟环境后，应更新本机 `output_dir` 并重新安装。停用整条流水线沿用 `./scripts/macos/uninstall-import.sh`，不会删除原始 JSON、SQLite 或成功水位。

## WebUI 和运行边界

全链路实际验证后，可以停用 QCE WebUI 中对应的 8 个定时导出任务，保留手动导出能力。Trivae 的导入及独立日报任务仍需要保留。QCE 服务、QQ/NapCat 登录必须可用；无需浏览器页面保持打开。本脚本不负责启动 QCE、登录 QQ 或证明上游消息完整。

30 分钟重叠和 15 分钟同步缓冲只覆盖相应边界，不能保证找回很久以后才同步到本机的旧消息；需要时明确扩大回查区间。创建 POST 已被服务接受但响应丢失的极短窗口，客户端尚无 taskId，当前 QCE 没有幂等创建契约，不能承诺服务端恰好一次；已返回 taskId 后会持久化并复用。

测试使用隔离配置、JSON 和 SQLite：

```sh
.venv/bin/pytest -q tests/test_qce_incremental.py tests/test_launchd_import.py
```
