# M7 DeepSeek invalid Answer Artifact 修复设计

## 已确认的根因边界

真实 baseline 的失败发生在生产 Runtime 已完成之后的 Answer Finalizer：最终模型文本以对象形状返回，但不能通过 JSON/Answer Artifact contract。provider capture 证明最终请求已经带 `response_format={"type":"json_object"}`，所以不修改 Finalizer，也不把失败包装成成功。

同一复现还观察到 Router/Planner 的 optional completion 没有显式 JSON mode；Planner 请求曾以 `finish_reason=length` 结束并没有可解析 content。这是相同 provider completion boundary 的独立可测问题，按现有 ADR 仍保留 Planner failure/degraded 语义。

## 最小修复

```text
DeepSeekSettings
  ├─ final model output budget
  └─ Router/Planner JSON completion budget
          ↓
OpenAIAgentsRuntimeAdapter
  ├─ Agent ModelSettings(response_format=json_object, max_tokens=...)
  └─ complete_text(response_format=json_object, max_tokens=...)
          ↓
生产 QueryOrchestrator / Finalizer
```

- 使用显式正整数配置，默认值来自真实多轮失败的输出边界和 provider JSON contract：final synthesis `16384`，Router/Planner JSON completion `2048`。
- 预算只改变 provider 请求参数；不截断模型输出，不修复非法 JSON，不改变 Tool 参数或 Evidence/Citation。
- `ModelSettings.max_tokens` 作用于同一 Agent 的每个 provider turn，保持 tool call 与 final synthesis 使用同一生产 Runtime；Trace/Run 继续记录真实 tool/terminal facts。
- Router/Planner 仍是可选/soft 组件；预算不足或 provider 仍返回非法 JSON 时，既有 explicit degraded/failed path 保持不变。

## 回归边界

- Unit：safe settings、正整数校验、Agent model settings、provider completion request。
- Integration：生产 `QueryOrchestrator` 仍只调用同一 Runtime；invalid structured output 仍在 Finalizer 失败。
- Real-data：临时 canonical copy + 同一 Snapshot 重跑 context-expansion、planned/standard paired smoke，并保留 Trace diagnosis。
