# Technical design

## Baseline evidence

当前真实 Debug export `trace-12f2784e0bc3405789212fe2d4ad54bd` 为 14,922 行、898,176 bytes；`RAW TRACE EVENTS` 占主要体积，且每一轮重复完整 system/user/tool context。GitHub `origin/main` 与 `main` 仍在 `7de3c67`，上一轮 Transcript 位于 feature branch `codex/human-readable-execution-transcript`，本任务只在该 branch 继续提交。

## Selected projection contract

```text
StoredTrace
  ├── format_trace_text(view="transcript", context="delta")  # 默认 .log
  ├── format_trace_text(view="transcript", context="full")   # Debug detail
  └── format_trace_text(view="raw")                            # 显式 raw export
```

`format_execution_transcript()` 仍是纯 `StoredTrace -> str` projection，不访问 Application、Conversation Store、Retrieval 或 Runtime。它新增可选 context mode：

- `delta`：第一轮显示完整 input；后续按 plain model item 的稳定 JSON 表示做 common-prefix subtraction，只显示相对上一轮新增 items，并保留 `capture limitations`。
- `full`：保留当前每轮完整 model-visible input，满足 Debug 需要核对 Provider request 的场景。

delta 不是新的事实字段，也不修改 StoredTrace；当上一轮缺少 context、当前 item 无法安全比较或存在 capture limitation 时，显示明确的 `context baseline unavailable` / limitation，不把推测内容当成事实。

## Text views

- `transcript`：metadata + Trace Summary + Execution Transcript，默认输出到 `.log`。
- `raw`：metadata + `RAW TRACE EVENTS`，只在显式 `trace export --view raw` 时输出；Raw events 仍然首先存在 SQLite。

`TraceTextLogWriter` 只负责组合/写文件；`Application.export_trace_log()` 传递 view/context 参数；CLI 只解析参数并调用 Application facade。

## Summary projection

Summary 只读取已存在的 normalized events：terminal outcome/duration、model turn 数、observable tool call 数、planner failure 数、retrieval partial/truncated 数、final answer availability。它不生成质量 root cause，不把 planner failure 改写为 query failure，也不重新查询业务数据。

## Compatibility and privacy

- 默认 view 改为 transcript 是 presentation change；`trace show`、SQLite schema、incremental sidecar 和 canonical events 不变。
- `raw` view 保留旧的完整 event 文本能力，避免丢失现有工程排查路径。
- full context 只读取已经经过 CapturePolicy 的 StoredTrace；formatter 不重新做 secret filter。
- 不捕获/展示 hidden Chain-of-Thought、provider internal reasoning 或 SDK raw object。
