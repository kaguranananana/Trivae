# M4 Query Execution Core Design

## Boundary

```text
QueryRequest
  -> context assembly (trusted scope stays local)
  -> Router (standard_execution | planned_execution)
  -> optional Planner (bounded soft guidance)
  -> AgentRunRequest
  -> one AgentRuntime + one CapabilityRegistry
  -> QueryResult / RuntimeEvent
```

Router、Planner、QueryOrchestrator 是 Trivae-owned domain/application code，不导入 OpenAI Agents SDK。SDK 依赖只存在于 runtime adapter；这样 deterministic tests 可以验证路由和规划，不需要网络，也不会把 provider 的内部类型扩散到业务层。

## Context and contracts

- `QueryRequest` 携带 query、trusted `ExecutionScope`、locale、bounded prior model context、capability names 和 request id。
- scope 只交给 `RuntimeContext` 和 Tool Layer 做 identity/authorization check；模型只看到 query、允许展示的历史上下文和 plan guidance。
- `RouteDecision` 保留 route、confidence、source、reason 和 degraded diagnostic；route 失败时只回到静态/保守判断，不执行第二套隐藏业务路径。
- `Plan` 是短文本 guidance，不是可执行工作流。Orchestrator 把它编译成 runtime instructions，绝不遍历 plan steps 调 tool。
- `RuntimeEvent` 是跨 adapter 的稳定事件面；SDK event 只在 adapter 内映射，原始 payload 不越过边界。

## Router

静态规则识别多目标/依赖、时间状态变化、跨阶段证据或显式恢复要求等任务结构；单个“分析/总结/比较/最近一年”词不单独触发 planned。可选 completion 只负责严格 JSON 分类，解析或 provider 失败时保留 static decision 并标记 degraded。

## Planner

Planner 只接受 query、bounded context snapshot 和 capability names，解析出最多 5 个 step 和 5 个 success criterion，并过滤未知 capability、去重和截断字段。任何结构性无效都返回 `PlannerFailure`；Orchestrator 记录失败但继续调用同一 runtime。

## Runtime and lifecycle

当前 SDK `0.22.0` 的 `Runner.run_streamed` 是唯一执行循环。adapter 使用 hooks 统计每一轮 tool result，并在达到 Trivae tool-round budget 时清空 agent tools、注入 final synthesis instruction；不复制 SDK 的 model/tool loop。SDK `max_turns` 是 absolute backstop，不能代替产品级 tool budget。

由于 SDK hooks 不能直接 yield，adapter 通过内部 event queue 将 hook 观察结果与 raw text delta 汇合；只有完整消费 `stream_events()` 并完成 cleanup 后才发 `completed`。取消通过 SDK `RunResultStreaming.cancel("immediate")`，并继续消费/等待 cleanup。

Application 持有 runtime、provider client、model 和 data resources；`aclose()` 负责真正关闭，`close()` 只在没有 running event loop 时提供同步包装。异步环境必须使用 `await aclose()`，避免隐藏 event-loop 错误。

## Trade-offs

- 采用两路 route 保持 M4 scope 清晰，不复制 ChatLab 的 direct/tool/planned 三路 taxonomy。
- 采用 soft plan guidance 降低编排复杂度，后续若 Evaluation 证明需要 workflow，再单独进入 M7。
- 使用当前 SDK streamed runner，保留 provider SDK 的 loop semantics，同时在 Trivae contract 层增加可观测 budget/cancel。
- 第一版使用 bounded in-memory context，不提前假设持久化 conversation schema。
