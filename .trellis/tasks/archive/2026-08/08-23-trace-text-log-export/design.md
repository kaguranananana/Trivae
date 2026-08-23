# Design: Human-readable Trace text logs

## Boundary

Trace 的正式事实仍由 `SQLiteTraceStore` 保存。新增一个 observability 层文本 writer，把同一份 `NormalizedQueryEvent` / `StoredTrace` 投影为本地 UTF-8 文本文件；Application 暴露导出 facade，CLI 只负责参数和结果展示。

## Data flow

```text
TraceCollector
  -> SQLiteTraceStore (SQLite canonical Trace + incremental text sidecar)
  -> data/traces/<trace_id>.log

trivae trace export <trace_id>
  -> TrivaeApplication.export_trace_log()
  -> read_trace()
  -> TraceTextLogWriter.export()
```

## Implementation choices

- 新增 `trivae.observability.text`，集中负责默认目录、文件名、纯文本格式和完整导出，避免 CLI 自己解释 raw payload。
- `SQLiteTraceStore` 在 metadata/event/terminal 写入成功后更新同名 sidecar；sidecar 是可重建的 derived projection，写入异常沿用当前 Trace degradation 语义并通过已有 logger 可见，不控制业务 Query。
- `TrivaeApplication.export_trace_log()` 读取现有 `StoredTrace` 后完整重写文件，因此可修复缺失或不完整的 sidecar，也支持自定义 output path。
- `trivae chat` 在 Query 结果已经展示后调用 Application export facade，成功显示绝对日志路径；导出失败显示明确的 `[trace log unavailable: ...]`，继续保留答案和 Trace ID。
- `trivae trace show` 保持 JSON projection；新增 `trace export` 只生成文件并打印路径。
- 默认日志使用已有 Trace capture 的 bounded/redacted payload，不额外读取数据库、不重新检索、不调用模型。

## Compatibility and rollback

- SQLite schema、`TraceStore` Protocol、QueryRequest/QueryResult 不变；现有 fake TraceStore 仍可用于业务测试。
- `data/*.log` 已被 Git 忽略，运行时日志不会进入提交。
- 回滚时删除 text writer、Application facade、CLI export/parser 和对应测试即可，SQLite Trace 数据不受影响。

## Risk controls

- Trace ID 作为默认文件名时拒绝路径分隔符，避免把 CLI 参数解释为目录；`--output` 仍是用户明确指定的目标。
- formatter 只序列化现有安全 payload；无法序列化或文件 I/O 失败显式抛出 typed export error，由 CLI 转成可读诊断。
- 测试同时验证自动 sidecar、完整重导出、失败提示和原有 trace show parser。
