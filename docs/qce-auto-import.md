# QCE 本地增量导入与 macOS 调度

已实现文件发现、状态持久化、失败恢复、独立 CLI 和调度管理，并与「合并转发内部消息检索」代码完成合并。用户在合并后明确授权启动真实调度；本轮为正式调度接入既有索引构建器，默认携带 `--update-indexes`。实际安装、首轮运行和生产检索验收结果需以任务验证记录及下述状态命令为准，不能只凭配置已生成就视为启用成功。开发测试使用隔离数据库，不修改 QCE、原始 JSON 或冻结 Evaluation。

2026-10-17 11:06 +08 正式任务已实际启用并立即运行。首轮全部 40 文件完成，新增 23,087 条，FTS 与 Agent lexical/recent 工具已验证；语义索引仍在构建，完整生产验收尚未完成。实测证据和限制见 [启用验证记录](../.trellis/tasks/10-16-qce-auto-import/enable-validation.md)。

## 单次执行与处理状态

在项目目录执行：

```sh
uv sync --extra dev --extra semantic
.venv/bin/python -m trivae import-once \
  --raw-dir /Users/anontokyo/Downloads/Project/Learn/Trivae/data/raw \
  --database /Users/anontokyo/Downloads/Project/Learn/Trivae/data/trivae.sqlite3 \
  --update-indexes
```

以上命令会写真实数据库，手工执行前应确认没有其他导入进程；开发测试改成独立目录与数据库。`import-once` 不需要 Web UI 或 QQ 接口，底层复用 `SharedImporter.import_paths()`。终端命令不带 `--update-indexes` 时只做 Canonical 导入，不加载模型，新增数据的索引工作明确保留为 pending；正式调度默认开启索引更新。

默认先间隔 5 秒检查大小、修改时间等文件属性，再要求最近至少 60 秒未修改。尚在写入的文件记为 `deferred`，不会作为已完成文件跳过；下次执行仍会检查。稳定文件复制到临时快照后由现有 QQ parser 校验 JSON 并导入，原文件保持不变。每次检查目录内全部 JSON，不以“上次运行时间”截断，因此导出延迟或错过调度不会永久遗漏旧文件。

成功文件的版本、状态和批次持久化在同一 SQLite 数据库的新增表中。只有文件事务已提交才标记成功。导入失败、单条失败导致的 `partial`、未提交中断均会在后续执行重试；已提交但状态尚未落盘的中断通过原批次恢复。未变化且已成功文件不重复解析。

旧批次没有保存解析前的文件版本；文件时间早于批次开始，也不能排除“旧导入器解析后、创建批次前 QCE 又写入”的竞争。首次接管历史文件时，会对稳定快照做一次原 Parser JSON 校验，并逐条核对数据库已有的原始记录与来源位置。能证明全部记录已导入才接管，省去逐消息规范化和重复写入；已有来源记录不能证明完整覆盖时，由原 import_paths 幂等补齐。同一快照的解析结果会复用，避免再次解码。首次核验后持久化文件版本，后续未变文件不再读 JSON；不能只凭文件名或批次时间跳过历史数据。

同一个数据库的 `import-once` 共享按数据库绝对路径派生的进程锁；进程退出后系统释放。现有普通 `import` 命令不使用这把新锁，生产集成时须先停止其他导入写入任务，约定导入窗口。

| 退出码 | 含义 | 后续操作 |
| --- | --- | --- |
| `0` | 本次文件处理完成，包括空目录；不代表 Agent 全链路已验收 | 查看数据库和索引状态 |
| `1` | 文件、记录或索引更新失败 | 查看错误、原批次和 stderr；修复后补偿 |
| `2` | 文件已处理，仍有索引工作等待集成或补偿 | 带 `--update-indexes` 再运行补偿 |
| `75` | 文件仍在写入，或同一数据库已有导入进程 | 保留状态，等待后续执行 |

实际新增消息的已提交批次才产生 lexical / semantic 索引工作；重复导出没有新增消息时不产生新的索引更新。索引失败保留 pending/failed 工作及错误，后续可单独补偿而不重新解析成功文件。队列为空只说明这些工作处理完毕；全库 readiness 与 Agent 检索仍需后续验收确认。

`--update-indexes` 将持久化待办交给现有 FTS5 和语义构建器；一轮内每种索引至多构建一次，没有新增数据且没有待办时不构建。现有底层只有全量构建和同源水位续建，因此这是**数据变更触发的全量索引更新，不是向量局部增量算法**。它保留现有合并转发和语义 parent 重切行为，避免对迟到消息只做错误的时间追加。相同快照失败或中断后按既有 resume 恢复；已完成且身份、消息计数及 revision 相同则确认复用，不重复计算向量。

全量成本可能很高：[合并转发验证记录](../.trellis/tasks/archive/2026-10/10-16-qq-forward-retrieval/validation.md) 中，本机对 765,780 条 Canonical、12,484 条转发内部记录续建时，复用 20,104 个块，新计算 72,184 个向量仍耗时约 **5 小时 13 分**。这不是从零重建耗时，也不是本次调度的预计完成时间。首次新增触发后可能长时间处于 `building`；期间不能声称最新消息已经通过语义检索验收。

## 准备调度配置

```sh
./scripts/macos/install-import.sh \
  --raw-dir /Users/anontokyo/Downloads/Project/Learn/Trivae/data/raw \
  --database /Users/anontokyo/Downloads/Project/Learn/Trivae/data/trivae.sqlite3
```

默认仅准备 plist，输出 `status: prepared`、`enabled: false`。准备文件放在 `~/Library/Application Support/Trivae/launchd/`，没有写入 `~/Library/LaunchAgents/`，因此下次登录也不会提前启动真实导入。准备时只用项目 `.venv/bin/python -m trivae import-once --help` 校验入口，不打开数据库。脚本可从其他工作目录执行。

plist 固定使用绝对 Python 路径、`-m trivae import-once --update-indexes`、raw/database 路径和项目工作目录，不依赖交互 shell 的 PATH、uv 别名或激活虚拟环境。可用 `--project-dir` 指向最终集成工作目录；默认 Python 是该目录的 `.venv/bin/python`，也可用 `--python` 显式指定。虚拟环境被移动或删除后必须重新准备并安装配置。安装输出的 `update_indexes` 及 plist 参数说明是否启用索引更新，`integration_required` 仅表示是否尚未装配 updater，不代表生产检索已经验收。

正式调度的环境显式设置 `HF_HUB_OFFLINE=1`，复用已验证的本机 Qwen 模型缓存，避免既有 Hub HEAD SSL EOF 导致启动失败；缓存缺失仍明确报错，不换模型或降级。需要 `semantic` extra 和正确模型缓存。隔离的只入库测试可给安装脚本传 `--no-update-indexes`；生成的命令不请求索引更新，也不设置该离线模型环境项。

调度为机器本地时区每天 **10:30 和 22:30**：

```xml
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>30</integer></dict>
  <dict><key>Hour</key><integer>22</integer><key>Minute</key><integer>30</integer></dict>
</array>
```

`RunAtLoad=true` 在登录或重启后登录时补查全部积压；它是用户 LaunchAgent，需要用户登录后才运行。根据本机 `man launchd.plist` 的 `StartCalendarInterval` 契约，睡眠中错过的日历事件在唤醒后合并执行一次；关机期间依靠下一次登录的 RunAtLoad 补查。不会唤醒关闭的机器，也不会强行要求本机重启/休眠来测试。

`KeepAlive.SuccessfulExit=false` 让非零退出后补偿；`ThrottleInterval=300` 限制连续启动频率。失败、文件写入中和索引 pending 都明确保留退出码和日志，持续失败时会继续每五分钟左右补偿，直到修复或卸载。成功后只等待下个日历事件；没有 `StartInterval`、十五分钟轮询或无条件全量索引重建。多个日历/重试/手工执行由核心数据库锁互斥。

真实 macOS 验证发现，刚执行完就调用 `launchctl kickstart` 也会受 300 秒节流，命令可能一直等待到允许启动。不要把它误判成导入卡死；`launchctl print` 中 `state=spawn scheduled`、`minimum runtime=300` 能说明原因。需要立即验证新安装参数时可重新执行显式安装命令，让管理器 bootout/bootstrap；常规补偿应等待系统调度。

## 启用调度

使用最终集成目录及已安装 semantic 依赖的 Python 环境，在 prepare 命令上增加 `--enable`：

```sh
./scripts/macos/install-import.sh \
  --raw-dir /Users/anontokyo/Downloads/Project/Learn/Trivae/data/raw \
  --database /Users/anontokyo/Downloads/Project/Learn/Trivae/data/trivae.sqlite3 \
  --enable
```

`--enable` 会创建日志目录、写入用户 LaunchAgents、bootstrap 并立即运行一次积压补查。更新已加载的同 label 服务时先 bootout，再加载新配置。默认索引更新失败会保留错误和待办，在后续调度中恢复；不要把 launchd 装载成功或 Canonical 入库成功当成索引已经就绪。

macOS 如果拒绝 launchd 访问 Downloads，stderr 会保留对应 `PermissionError`；需在系统设置中解决实际执行环境的文件访问权限后再执行。不要把权限失败解释为“目录内没有新记录”。

## 如何确认运行正常

先查看系统任务：

```sh
./scripts/macos/status-import.sh
```

输出包含准备/安装路径、`loaded` 以及完整 `launchctl print` 内容。确认 program arguments 指向最终工作目录和正确数据库，`runs` 在计划执行或唤醒后增加，`last exit code` 为 `0`。`loaded=true` 仅证明服务存在；`state=waiting` 可以是成功完成后等待下次日历，也可能是失败重试间隙，必须结合退出码和日志判断。

默认日志：

- `~/Library/Logs/Trivae/com.trivae.import-once.stdout.log`：每次命令的 JSON 结果与文件、批次、索引待办。
- `~/Library/Logs/Trivae/com.trivae.import-once.stderr.log`：明确错误与 traceback。

再读取业务状态，以下命令只读，不创建数据库或 Application：

```sh
.venv/bin/python -m trivae import-once \
  --database /Users/anontokyo/Downloads/Project/Learn/Trivae/data/trivae.sqlite3 \
  --status
```

检查 `last_run`、按状态统计的 `files`、`unfinished_files`、`pending_indexes` 和 `retrieval_readiness`。坏 JSON、部分导入失败、写入中或索引失败不能视为已全部完成。无更新时 run 仍应成功结束，文件不被重新解析。`not_initialized` 表示自动导入状态尚未初始化，不等于历史 Canonical Store 中没有消息。

确认“最新消息已经入库”时，在数据库上只读查询对应 session、消息来源 ID、时间和文本，并对照本次 batch 的 inserted/duplicate/failed 计数。例如：

```sh
sqlite3 -readonly data/trivae.sqlite3 \
  'SELECT session_id, source_message_id, timestamp, content_text FROM messages ORDER BY timestamp DESC LIMIT 5;'
```

确认“Agent 已可检索”必须验证：索引补偿没有 pending/failed；FTS5 与语义检索都能按真实 scope 命中新批次消息；Agent 查询使用唯一短语能返回新消息，并产生正确来源与 citation。还应包含合并转发内部消息、迟到消息和 session 时间边界，不能仅靠普通消息关键词命中就宣布端到端通过。实际生产结论由本次启用阶段的验证记录报告。

## 停止与卸载

```sh
./scripts/macos/uninstall-import.sh
```

脚本先确认 bootout 成功，再删除本 label 的已安装和已准备 plist；原始 JSON、SQLite 数据库及日志全部保留。失败会返回非零并保留具体系统错误。没有加载的服务可重复卸载，不会创建任何导入任务。

## 隔离验证与集成依赖

脚本支持 `--label`、`--plist-dir`、`--launch-agents-dir`、`--log-dir`、`--raw-dir`、`--database` 和 `--no-update-indexes`。独立 smoke 必须使用临时目录与单独 label，例如 `com.trivae.import-once-test.<pid>`；显式启用测试任务后务必用相同 label/目录参数卸载。真实任务是否已启用，由安装结果与 `status-import.sh` 核实。

自动化验证：

```sh
.venv/bin/pytest -q tests/test_launchd_import.py
```

该测试覆盖日历与重试配置、保留虚拟环境路径、带空格的绝对参数、默认索引参数和离线环境、显式只入库配置、默认 prepare 不自启动、不读写数据库、入口失败、显式启用/更新/卸载流程、系统错误透明和 wrapper 从任意目录执行。

真实 macOS smoke 为显式选择的隔离测试：

```sh
TRIVAE_RUN_LAUNCHD_SMOKE=1 .venv/bin/pytest -q \
  tests/test_launchd_import.py -k real_launchd
```

它只注册唯一测试 label，用临时 SQLite/raw/日志验证 RunAtLoad、重新 bootstrap 后的状态恢复、新文件入库，显式传 `--no-update-indexes` 验证 pending 的非零退出和重试调度，不加载真实模型，最后在 `finally` 中卸载。真实 launchd smoke 与 CLI/持久状态验证结果保存在本任务验证记录中。物理重启和休眠为待用户使用机器时验证的场景，不宣称已经强制实测。

共享接口保持窄边界：自动导入只新增状态表并交接已提交批次；lexical / semantic updater 必须幂等，返回成功必须表示交接数据可检索。当前装配器复用既有转发检索的索引身份、forwarded children 与 parent 重切行为，没有改写底层算法。真正的局部增量维护仍需另行验证迟到消息和语义 parent 边界，不能简单追加 timestamp 水位以后消息。生产整链路结论以实际消息、索引和 Agent 验收为准。
