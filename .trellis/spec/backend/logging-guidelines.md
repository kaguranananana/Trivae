# Logging Guidelines

> 日志与可观测性长期原则（源自工程原则第 4 节）。
> Stage 1.9 已确认 normalized event、Failure Attribution、query-scope coverage、privacy / retention 与 Trace storage 的架构语义；M6 已落地 Python normalized event、独立 SQLite Trace Store、normal/debug capture、Projection 与 Application facade；Stage 1.10 Evaluation artifact、部署 retention 与 API mapping 仍待实现。

---

## 原则

1. **错误可见**：出错后必须能从日志 / Trace 定位问题发生在哪一步（Failure Attribution）。
2. **中间状态可查**：关键流程记录足够上下文（输入、决策、结果）。
3. **不静默**：恢复机制（如 Retry 成功）也要留痕，不能隐藏问题。

## 进入 Agent 开发阶段后，重要 Run 应逐步记录

- request_id
- User Query
- Router Decision
- Plan / State
- Tool Calls（参数与结果）
- Retrieval Query
- Retrieval Candidates / Results
- Evidence Selection
- Final Evidence
- Context
- Final Answer

## 运行指标（按实际架构取舍）

- Latency
- Token Usage
- Tool Call Count
- Retry Count
- Error Type
- Model
- Prompt Version

## Remaining architecture specification

- Coverage Descriptor 的更完整跨 capability Schema 与事件名扩展
- 日志格式 / 级别体系
- Trace backend 的 batch/retention/部署策略
- Trace Profile 的部署级配置来源、具体 retention 时长与访问角色

## 已确认边界（Stage 1.9）

- 一个 Trivae-owned normalized event boundary 横跨完整 Query Execution；SDK raw event 不成为产品或 Trace contract。
- Trace 事件 append-only、versioned，并通过单 Trace sequence 与 operation causality 回放；metrics 是 derived projection。
- Error Code 由 contract owner namespace 拥有；恢复 / degradation 不抹掉原始 failure。
- Trace 使用 `normal / debug` Profile：Normal 可保存 bounded / redacted actual content，Debug 可在 Data Access Scope 内保存完整或近完整的 model-visible / system-visible facts；两者都不保存 Chain-of-Thought、secrets 或越权数据。
- Trace access / export 不扩大 Data Access Scope；SDK built-in external tracing 保持显式关闭。
- Debug Profile 不改变业务授权；profile、capture policy、truncation 与 retention 必须可追踪，且 Local-first 开发环境可以由显式配置决定清理时机。
- CLI、HTTP API、Evaluation 不得各自定义 Trace / Error 语义；入口只能投影同一个 Trivae-owned Normalized Event 与 canonical Error。
- request_id 与 trace_id 必须从 Application Boundary 贯通到 Stream Projection、Trace Collector 与 Evaluation Result；入口丢失关联属于可诊断 Failure。
- Stage 1.9 operational metrics 不自动证明 Stage 1.10 quality；Evaluation quality、numerical threshold、Review artifact 与 gate 仍需真实运行校准。
