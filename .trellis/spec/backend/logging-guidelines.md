# Logging Guidelines

> 日志与可观测性长期原则（源自工程原则第 4 节）。
> Stage 1.9 已确认 normalized event、Failure Attribution、query-scope coverage、privacy / retention 与 Trace storage 的架构语义；具体 Python / JSON Schema 和 backend 仍待实现。

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

## Pending architecture specification

- Normalized Event / Failure / Coverage Descriptor 的具体 Python / JSON Schema 与事件名
- 日志格式 / 级别体系
- Trace Collector / Store backend、指标采集与存储实现
- sensitive snapshot allowlist / redaction、具体 retention 时长与访问角色

## 已确认边界（Stage 1.9）

- 一个 Trivae-owned normalized event boundary 横跨完整 Query Execution；SDK raw event 不成为产品或 Trace contract。
- Trace 事件 append-only、versioned，并通过单 Trace sequence 与 operation causality 回放；metrics 是 derived projection。
- Error Code 由 contract owner namespace 拥有；恢复 / degradation 不抹掉原始 failure。
- Trace 默认不保存 Chain-of-Thought、逐 token stream 或完整聊天 / Tool / Model payload 副本。
- Trace access / export 不扩大 Data Access Scope；SDK built-in external tracing 保持显式关闭。
- Stage 1.9 operational metrics 不包含 Stage 1.10 quality threshold / gate。
