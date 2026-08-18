# Logging Guidelines

> 日志与可观测性长期原则（源自工程原则第 4 节）。
> 具体 Trace Schema / 日志格式由 Architecture Specification 决定。

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

- Trace Schema 的具体结构
- 日志格式 / 级别体系
- 指标采集与存储方式
