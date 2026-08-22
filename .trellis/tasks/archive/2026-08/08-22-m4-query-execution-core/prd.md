# M4 Query Execution Core

## Goal

在已完成 M4a Agent Runtime baseline 的基础上，完成 Trivae 的 Query Execution Core：把一次用户查询从上下文装配、两路路由、可选轻量规划，送入同一个真实 Agent Runtime，并提供可观察、可取消、可收敛的执行生命周期。

## Background

当前仓库已有 SQLite/Lexical Retrieval、Capability/Tool boundary 和 DeepSeek/OpenAI Agents SDK adapter，但 Query 入口仍直接依赖 runtime，Router、Planner、Orchestrator、streaming、cancellation、tool-round finalization 和 provider lifecycle 尚未闭合。本任务只补齐 M4，不提前实现后续 Retrieval、Evaluation、Workflow 或 UI 阶段。

## Requirements

### Query path

- 增加 Trivae-owned `Router`，只保留 `standard_execution` 与 `planned_execution` 两种 route。
- Router 先使用可测试的结构化规则；可选 LLM 判断必须是受约束的 JSON completion，失败时保留静态判断并显式记录 degraded diagnostic。
- Router 不读取数据库、不执行工具、不生成可执行步骤；“分析谁发言最多”等结构化统计不能仅因出现“分析”二字而误路由到 planned。
- 增加轻量 `Planner`，输出 bounded soft guidance；最多 5 个 step、最多 5 个 success criterion，过滤未知 capability，禁止在本任务引入 step executor、replan 或 workflow state machine。
- Planner 输出异常、超时、无效 JSON 或不可用时跳过规划，查询仍使用同一个 runtime 执行，并保留可诊断的 degraded 信息。
- 增加 `QueryOrchestrator` 和 `QueryRequest/QueryResult`。standard 与 planned 必须进入同一 `AgentRuntime` 和同一 capability registry；scope 是受信任的本地上下文，不得拼进模型可见文本。

### Runtime path

- 保留 M4a 的 typed tool contract、scope identity check、known tool error envelope 和 unknown exception terminal failure 语义。
- 使用当前已验证的 `openai-agents==0.22.0` streamed runner；`run()` 只是完整消费 `stream()` 的便利入口。
- 暴露稳定的 Trivae `RuntimeEvent`：run/turn/tool/content/finalization/completed/failed/aborted；只投影安全字段，不泄露 SDK 内部对象、scope、provider secret 或原始异常正文。
- 明确区分 tool round budget 与 SDK absolute `max_turns` backstop：一轮模型响应中的多个 tool call 只消耗一个 tool round；达到预算后隐藏 tools，并让模型进行最终综合。
- budget finalization 必须显式产生 `finalizing`，且不得把正常收敛误报成 SDK max-turn failure；SDK backstop 仍应以明确的 `MAX_TURNS_EXCEEDED` 暴露。
- 支持运行前和运行中的 cancellation；取消后不再发起 final synthesis，不产生 `completed`，并等待 SDK stream cleanup 完成。
- provider client/model 必须由 runtime/application 持有并可重复安全关闭；不得只清空引用。同步和异步 application lifecycle 都要覆盖。
- runtime/provider 错误必须 secret-safe，保留稳定 error code、stage/category/type 等诊断字段，不把异常字符串、请求体或 key 放入 `RuntimeResult`、事件或日志。

### Quality and scope

- 默认 deterministic tests 覆盖 Router、Planner、Orchestrator、runtime streaming、tool budget、max-turn backstop、cancellation、lifecycle、secret-safe failure。
- 若环境存在 DeepSeek credentials，执行独立、低成本的 live smoke，记录 provider/model/tool/termination/usage 和异常行为；没有 credentials 时明确记录未测，不影响 deterministic suite。
- 不引入 HTTP/FastAPI/SSE/UI，不实现 M5/M6/M7 的 semantic/vector/hybrid/reranker、Evaluation 或 Workflow。
- 不为了通过测试添加静默 fallback、重试、兼容分支或样例特判；错误要沿主链路显式暴露。

## Acceptance Criteria

- [x] `QueryRequest -> Router -> optional Planner -> QueryOrchestrator -> same AgentRuntime -> QueryResult` 主链路可执行。
- [x] Router 只产生两种 route，静态/LLM 判断和 degraded 原因可观察；单个“分析”关键词不会误触发 planned。
- [x] Planner 约束在 5 steps / 5 criteria 内，过滤未知工具，失败不阻塞查询。
- [x] scope identity 和 capability whitelist 在 standard/planned 两路都保持；scope 不进入模型输入。
- [x] stream events 只有 Trivae contract 字段，completed 发生在 SDK stream fully consumed 之后。
- [x] 多 tool call 同一模型回合只消耗一个 tool round；预算耗尽后能 finalizing 并完成；SDK `max_turns` 仍明确失败。
- [x] cancellation 在开始前和运行中都可验证，且不会误报 completed 或再次启动模型。
- [x] runtime/application close 实际关闭 provider/model/data resources，并具备幂等行为。
- [x] `pytest`、`ruff`、`mypy`、CLI help、Trellis validation 和 `git diff --check` 通过。
- [x] 任务验证文档记录实际 SDK 版本、deterministic 结果与 live smoke 是否可用。

## Notes

- Persistent Conversation Store schema 仍为后续阶段 pending；本任务只允许 bounded in-memory/model-visible context。
- Planner 的 5/5 bound 是第一版可校准参数，不把 ChatLab 的业务 prompt 或三路 route taxonomy 机械复制进 Trivae。
