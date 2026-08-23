# Human-readable execution transcript for debug traces

## Goal

在已经存在的 M6 `StoredTrace` / `NormalizedQueryEvent` 之上，增加一个由 canonical Trace 派生的 Human-readable Execution Transcript，使开发者只打开一个 Debug `.log` 就能沿着一次 Query 的因果顺序回答：用户问了什么、Router/Planner 做了什么、每一轮模型实际看到了什么、模型调用了什么工具、工具把什么内容返回给模型、下一轮模型如何继续，以及最终回答是什么。

本任务同时修复已确认的 model-visible capture gap：OpenAI Agents SDK 在 `on_llm_start` 传入的 input item 不只有 `{role, content}` 普通消息；当前实现会丢弃 `function_call`、`function_call_output` 和可观察的 assistant message，因此 Trace 不能解释工具回合。

## Requirements

### Canonical boundary

- SQLite `StoredTrace` / `NormalizedQueryEvent` 继续是唯一 execution source of truth。
- Transcript 只能是 `StoredTrace -> projection`，不得新增 transcript 数据库、runtime 独立日志链路、CLI 重新查询 Conversation Store 或 Retrieval 来补内容。
- `.log` 同时包含人工可读的 `EXECUTION TRANSCRIPT` 和现有完整 `RAW TRACE EVENTS`；两者必须来自同一份 StoredTrace。
- 既有 `trace show`、`trace export`、`trivae chat` 的 Trace identity、terminal status 和 Application facade 边界保持不变。

### Model-visible facts

- 在 SDK hook 已经完成 input filtering、即将调用 Provider 的 `on_llm_start(..., input_items)` 边界捕获当时实际传入的普通可观察 input items。
- 安全投影至少支持：system instructions、普通 message、assistant message、`function_call`、`function_call_output`；不直接序列化或 `repr` SDK object。
- Tool Result 在 Transcript 中优先使用后续模型回合实际收到的 `function_call_output.output`，不得从数据库重新构造一个“看起来更完整”的结果。
- Tool Call 展示 tool name、arguments 和可简化的 call identity；Tool Result 展示模型实际收到的正文，并保留 status、returned count、total hits、partial、truncated、coverage 等诊断信息。
- 模型可观察的 assistant visible output、usage、tool round、finalization/termination 状态尽可能保留到 normalized event；hidden reasoning 不属于 capture 范围。

### Human-readable transcript

- Transcript 按事件 sequence 顺序组织 `[USER]`、`[CONTEXT]`、`[ROUTER]`、`[PLANNER]`、`[MODEL TURN n]`、`[TOOL CALL]`、`[TOOL RESULT]`、`[RETRIEVAL]`、`[EVIDENCE]`、`[FINAL ANSWER]` 等区块。
- Query 区块展示原始 query、conversation/session scope 和有效时间范围（存在时），不把内部 UUID 泛滥到主阅读路径。
- Router 展示 route、confidence、source、显式 reason、degradation（存在时）。
- Planner 成功展示 title、steps、success criteria；失败明确展示 `status: failed`、error code、failure category、handling 和 `executed_without_plan`。
- Retrieval 主区块展示 strategy、query、returned/total、partial、truncated、coverage；candidate IDs/scores 等细节留在 Raw Events。
- Evidence/Citation 展示 selected sources、evidence items、bindings、unresolved 等主要诊断数量。
- Final Answer 区块展示完整的 Trace execution snapshot；Conversation Store / Answer Artifact 仍是业务事实源。

### Capture policy and privacy

- `normal` 继续 bounded/redacted，主要服务生产诊断、latency、failure、metrics；不承诺完整 Transcript。
- `debug` 在既有 ExecutionScope、secret redaction 和 retention/privacy 边界内尽可能保留近完整 model-visible input、Tool Call、model-visible Tool Result、assistant visible output 和 Final Answer。
- CapturePolicy 仍是统一的 secret filter / bound 入口；Formatter 不重复实现 secret 过滤。
- 任意 profile 都不得写入 API key、Authorization、provider secret、database credential、越权聊天数据、hidden Chain-of-Thought、provider internal reasoning、SDK reasoning/scratchpad。

### Documentation

- 以 amendment/clarification 形式更新 Stage 1.9 Trace / Observability ADR 和 backend quality guidelines，明确：完整 model-visible execution facts 不等于 hidden Chain-of-Thought；Debug Trace 必须能回答“这一轮模型实际看到了什么”。

## Acceptance Criteria

- [ ] 在当前 OpenAI Agents SDK 版本下，第一轮 `system + user` input 能被投影并持久化。
- [ ] Tool Call 后下一轮 model input 中的 previous assistant tool action 和 `function_call_output` 能被投影并持久化。
- [ ] Transcript 中的 Tool Result 内容与实际传给 model hook 的 `function_call_output.output` 一致；实现不查询数据库补齐。
- [ ] 完整 synthetic Trace 能生成并包含 User、Router、Planner、至少两轮 Model Turn、Tool Call、Tool Result、Retrieval、Evidence/Citation、Final Answer 和 Raw Events。
- [ ] `planner.failed` + `handling=executed_without_plan` 在 Transcript 中清晰可见。
- [ ] `total_hits=77`、`returned=20`、`truncated=true` 会显示为 `20 / 77` 及显式 truncation 状态。
- [ ] Debug capture 不包含 hidden reasoning、SDK internal fields 或未经允许的 raw SDK object；Normal/Debug 的边界符合 policy。
- [ ] 既有 M6/M7/CLI 行为无回归；完成 `pytest`、`ruff check src tests`、`mypy src`。
- [ ] 在有本地 DeepSeek 配置时完成真实 Query smoke test，生成一个实际 `.log` 并检查 Transcript；若运行环境缺少配置，必须把缺失条件作为明确验证结果报告，不伪造成功。
- [ ] 记录 Branch / Commit / Base、修改文件、SDK input item 形态、model-visible 保证方式、profile 差异、CoT 排除方式、测试结果、实际 log 路径，以及至少一个真实 Failure Case 的修改前后定位对比。

## Explicit non-goals

- 不重设计或替换 Stage 1.9 normalized event boundary、SQLite Trace Store、Failure Attribution、Evidence/Citation 或 Evaluation boundary。
- 不引入第二套 transcript runtime logging pipeline、独立数据库、SDK built-in external tracing 或新的 provider tracing contract。
- 不捕获 raw hidden Chain-of-Thought，也不为 provider reasoning summary 修改核心 Trace Contract。
- 不从 Conversation Store、Retrieval 或 Answer Artifact 重新恢复超出当时模型输入的内容。
- 不为了让日志更完整而静默吞掉 capture/serialization 错误或新增无证据的 fallback。
