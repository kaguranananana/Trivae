# Technical Decisions

> 重大技术决策（ADR）的沉淀位置与格式。
> 当前状态：**暂无独立 ADR**。Stage 1.1 已确认的一级架构方向记录于 architecture.md；具体技术选型与实现级决策仍在后续 Stage 中确认。

---

## 记录位置

正式决策文档：`.trellis/spec/project/technical-decisions/<slug>.md`，本文件作为索引。

## 决策问题链

以下链路按决策类型取舍；`Problem / Constraint`、`Root Cause` 或 `Regression` 不适用时应明确标注，而不是强行制造 Failure Case。

```
Initial Design / Context
↓
Problem / Constraint (if applicable)
↓
Evidence / Rationale
↓
Root Cause (if applicable)
↓
Candidate Solutions
↓
Decision
↓
Reason
↓
Result
↓
Trade-off
↓
Regression
```

禁止只记录结论（如 "Use Hybrid Retrieval."）而不记录演化原因。

## 来源分级

- 来自「框架默认 / ChatLab 如此 / 某开源项目如此」的方案视为 **Initial hypothesis / reference design**，不能直接视为最终结论。
- 应根据决策类型，通过项目约束、复杂度分析、Prototype、Test、Benchmark、Evaluation 或真实 Failure Case 等证据确认方案，再升级为决策记录。

## 重点关注清单

优先记录影响 Quality / Reliability / Latency / Token / Cost / Complexity / Maintainability 的决策，例如：

- Rule Router / LLM Router / Hybrid Router
- Keyword / Semantic / Hybrid Retrieval
- 是否需要 Reranker
- Agent Loop 终止条件
- Tool 参数错误处理
- Context 规模控制
- Retry / Fallback 策略
- Token / Latency 控制

## 当前记录

### Stage 1.1：整体架构骨架

- 状态：Draft / In Progress，不是最终 Architecture Specification。
- 内容：Data Plane + Query Plane、Query 主链路、Router / Planner / Agent Runtime / Tool Layer / Retrieval / Evidence 的一级职责边界。
- 记录位置：[architecture.md](./architecture.md)。
- 后续：Stage 1.2-1.11 分别确认剩余细节，完成后再统一升级文档状态。
