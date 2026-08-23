# Add human-readable Trace log export

## Goal

为每次 Trivae Query 提供一份可以直接用编辑器打开的纯文本 Trace 日志，方便人工体验和排查问题；已有 SQLite Trace 继续作为正式存储和 `trivae trace show` 的读取来源。

## Requirements

- 新 Query 结束后，在 Canonical database 同级的 `traces/` 目录中生成 `<trace_id>.log`。
- 文本日志必须来自现有 `StoredTrace` / normalized event，展示 metadata、事件顺序、阶段、操作、结果、耗时、payload、limitations 和 failure attribution。
- 文本日志不得新建 Query、Runtime、Retrieval 或 Provider 链路；复用已有 Trace 的 bounded / redacted payload。
- `trivae chat` 在回答下方显示 Trace ID 和日志文件路径。
- 新增 `trivae trace export <trace_id>`，能够为功能上线前已经写入 SQLite 的 Trace 生成日志；支持 `--database` 和可选 `--output`。
- 原有 `trivae trace show` 输出和 SQLite Trace schema 保持兼容。
- 用户刚才运行的现有 Trace（包括成功和失败 Trace）迁移到默认数据库的 `data/traces/` 目录。

## Acceptance Criteria

- [ ] 新 Query 的 Trace 产生对应 UTF-8 `.log` 文件，且包含有序事件和 terminal 状态。
- [ ] `trivae trace export <trace_id>` 可从现有 SQLite Trace 生成同样格式的文本文件，并输出可直接打开的路径。
- [ ] `trivae chat` 展示 `[trace: ...]` 与 `[log: ...]`，日志导出失败时显式提示而不伪装成成功。
- [ ] 成功答案仍只使用 `final_answer`，Query 生产链路和 Evaluation/Trace show 语义不改变。
- [ ] 覆盖 formatter、自动写入、已有 Trace 导出、CLI parser、chat 输出和导出失败路径测试。
- [ ] `pytest`、`ruff check src tests`、`mypy src` 通过。

## Out of scope

- 不增加 Web/TUI/Trace viewer，不替换 SQLite Trace Store。
- 不改变 Query、Router、Planner、Agent、Retrieval、Citation 或 Evaluation 语义。
- 不把日志文件纳入 Git，也不新增日志清理、压缩或远程上传机制。

## Confirmed decisions

- 默认目录为数据库路径的父目录下的 `traces/`；默认数据库因此使用 `data/traces/`。
- 新 Trace 由 Trace Store 在 normalized event 已安全投影后持续写入，`trace export` 负责完整重建已有或损坏的派生文本文件。
- 日志路径在 CLI 中输出为可直接定位的本地路径；SQLite 仍是 Trace source of truth。
