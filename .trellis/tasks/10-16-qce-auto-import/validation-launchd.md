# macOS 调度验证

2026-10-16，独立 worktree 的本地 macOS 用户 gui 域。所有真实运行均使用临时 SQLite、raw、日志和唯一测试 label；没有操作默认 `com.trivae.import-once`，没有打开生产数据库，没有修改 QCE 或原始导出。

## 实现与单元验证

- 新增 `launchd_import.py`，三个可执行 wrapper：`install-import.sh`、`status-import.sh`、`uninstall-import.sh`。
- 默认 prepare 写入 Application Support，避免下次登录自动启用；只有 `--enable` 才写 LaunchAgents 并 bootstrap。
- 每天本地时间 10:30、22:30 的 `StartCalendarInterval`，`RunAtLoad=true`，`KeepAlive.SuccessfulExit=false`，`ThrottleInterval=300`。未配置 StartInterval 或 WatchPaths。
- 直接使用项目 `.venv/bin/python -m trivae import-once`，保留虚拟环境软链接路径，不解引用为基础解释器。工作目录、输入、数据库和日志均为绝对路径。
- prepare 仅调用 `import-once --help` 校验已安装入口，不构造 Application 或数据库。

命令与结果：

```text
.venv/bin/python -m trivae import-once --help
exit 0，出现 --raw-dir / --database / --settle-seconds / --min-age-seconds / --status

.venv/bin/ruff check scripts/macos tests/test_launchd_import.py
All checks passed!

TRIVAE_RUN_LAUNCHD_SMOKE=1 .venv/bin/pytest -q tests/test_launchd_import.py
14 passed in 26.17s
```

默认运行上述测试时，真实 launchd 用例跳过；显式设置环境变量才会创建临时测试服务。三个 wrapper 的 `--help` 在另一个临时工作目录真实执行通过。单元测试覆盖准备不启用、入口失败、启用和已加载配置替换、系统错误透明、bootout 失败保留配置、卸载保留原数据和日志。

## 真实 launchd smoke（实测事实）

第一次手工 smoke 的空目录任务成功 exit 0。紧接着执行 `launchctl kickstart` 时命令等待，读取系统状态确认原因是 300 秒节流：`state = spawn scheduled`、`minimum runtime = 300`、`runs = 1`、`last exit code = 0`。只终止了这个测试的 kickstart 子进程，finally 成功卸载该 label `com.trivae.import-once-smoke.27475`。这是启动节流的真实语义，没有改成绕过节流的重试配置。

随后使用 `com.trivae.import-once-smoke.28095`，在临时目录独立验证：

1. prepare 返回 `enabled=false`，SQLite 文件和 LaunchAgents 目录均不存在。
2. 显式安装 bootstrap 后 `RunAtLoad` 执行空目录，exit 0。
3. bootout/bootstrap 后同一 SQLite 的 `last_run.run_id` 推进，第二次空目录仍 exit 0。
4. 写入一个合成 QCE JSON，再次 bootstrap；原 SharedImporter 提交 1 条消息，文件 completed。
5. lexical / semantic 各有 1 条 pending 工作，`retrieval_readiness=pending`、`updater=integration_required`，任务 exit 2。
6. `launchctl print` 保留 `state=spawn scheduled`、`minimum runtime=300`、`last exit code=2` 和两组 `Hour=10/22, Minute=30` 日历事件。
7. stdout 记录三次完整 JSON 运行结果，stderr 为空。
8. finally 卸载后 `loaded=false`、`installed=false`、`prepared=false`；临时目录随后自动清理。

提交的 opt-in pytest 将这条 smoke 固化为可重复测试，唯一 label 为 `com.trivae.import-once-test.<pid>.<time_ns>`。它验证 prepare、RunAtLoad、更新配置导致的重装补查、新消息与索引 pending/失败调度，并在 finally 中卸载；本次执行通过。立即 kickstart 也受节流的事实已写入运维文档。

## 适用边界与后续集成

- 不强行重启或休眠共享开发机。重启后登录与唤醒补查采用本机 `man launchd.plist` 的 RunAtLoad/StartCalendarInterval 契约，加持久化全目录扫描的自动化验证；没有宣称物理重启/休眠实测。
- 未等待完整 300 秒验证第二次失败重启；真实系统已展示失败后的 `spawn scheduled` 和 `minimum runtime=300`，配置及退出码已实测。
- 本分支默认 updater 缺失，因此只证明 Canonical 写入与 pending 工作透明，不证明真实 FTS5/语义索引和 Agent 检索就绪。真实任务必须等待转发检索集成后启用。
- 最终工作目录或虚拟环境路径变化时须重新 prepare/install；不能直接把临时 worktree 路径当作最终部署路径。
- 默认 label 的真实 prepare/启用由父任务单独负责；本子任务未修改它。
