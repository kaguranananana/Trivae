# Agent-facing Tool Surface

## Goal

按已确认的 Stage 1.4 Tool / Capability Layer 架构，分三个可独立回滚的 checkpoint，
把第一版 Agent-facing Tool Surface 接入现有 Trivae Runtime：

- Stage A：`lexical_search`、`semantic_search`
- Stage B：`get_message_context`、`find_members`
- Stage C：`get_schema`、`execute_sql`

每个阶段都必须经过实现、单元测试、集成测试、真实 Provider smoke、Trace 检查、Evaluation
和 Failure Case 记录后，才能进入下一阶段。

## Baseline and confirmed constraints

- 工作基线为 `codex/agent-facing-tool-surface`，从 `main` 的 `8061aac` 创建；语义索引和
  lexical/semantic retrieval 已存在。
- Stage 1.4、1.5、1.6、1.7、1.9、1.10 的设计已经确认，不重新设计 Router、Planner、
  Agent Runtime、Evidence 或 Trace。
- `search_messages` 继续作为兼容入口；正常 Agent-facing canonical lexical tool name
  为 `lexical_search`，不做无必要的大规模 rename。
- Tool 与 Capability 分离。所有工具必须复用现有 `QueryRequest`、`ExecutionScope`、
  `CapabilityRegistry`、Agent Runtime、`ToolResultRecord`、Evidence/Citation、
  `TraceCollector` 和 `EvaluationRunner`。
- 不加入 fixed hybrid、RRF、reranker、query rewrite、multi-query expansion、第二套
  Runtime/Query pipeline、candidate state、Analysis View、替代 embedding model 或隐式
  lexical fallback。
- 不持久化 hidden chain-of-thought，不提交真实聊天正文，不把 provisional 标签伪造为
  `human_verified`。

## Current evidence

- 现有 Application 已注册 `search_messages`、`lexical_search` 和 `semantic_search`，
  但正常 `QueryRequest`/Runtime 默认 visible capabilities 仍以 `search_messages` 为主。
- lexical retrieval、semantic retrieval、semantic unavailable/stale 的显式失败语义、
  Trace 基础设施和 paired retrieval evaluation 已经存在。
- 在当前未安装项目依赖的环境中，`compileall` 通过；直接运行测试因缺少 `trivae`/`agents`
  导入失败，`pytest`、`ruff`、`mypy` 命令也暂不可用。依赖安装和完整验证属于实施阶段，
  不能把该环境问题误判成产品行为结论。

## Requirements

### Stage A — Dual Retrieval Agent Surface

1. 正常生产 Query 和 Interactive CLI 默认只向 Agent 暴露 `lexical_search` 与
   `semantic_search`；显式 legacy callers 继续能够使用 `search_messages`。
2. 两个 Tool description 简洁说明精确字符串/标识符检索与语义/改述检索的选择依据，
   不把 routing 写成大量硬编码规则。
3. Agent 可以在同一 Runtime 内从一种 Retrieval Tool 继续调用另一种；不自动固定为
   hybrid，也不因第一种结果为空而静默 fallback。
4. 保留 paired lexical-vs-semantic retrieval benchmark，新增 Agent Tool Selection /
   Retrieval Behavior diagnostic evaluation，记录可见工具、首个工具、完整工具序列、
   tool rounds/count、结果强弱、Evidence/Citation、错误、latency/usage。
5. Trace 能解释 User query → visible tools → selected tool/arguments → result summary →
   optional second retrieval call → Evidence → final answer，并区分选错工具、检索错误、
   context 不足、分析错误、过多调用和 semantic unavailable/stale。
6. 覆盖 lexical-dominant、semantic-dominant、weak-result multi-search、no-result/no-
   hallucination、semantic unavailable/stale 五类测试和真实 smoke。

### Stage B — Context and Member Tools

1. `get_message_context(message_id)` 复用现有 Canonical Read / bounded Context Expansion
   能力，稳定使用 `message_id`，执行 scope、会话边界和截断约束。
2. Search 继续自动返回 bounded local context；Agent 判断需要深挖时才显式调用
   `get_message_context`，Trace 区分两者。
3. `find_members` 遵循 identity/membership 模型，返回候选及匹配依据，保留 nickname、
   alias、username、platform identity、multiple sessions 和 ambiguity，不强制唯一 resolve。
4. 覆盖 search → context、invalid ID、scope boundary、truncation、conversation boundary、
   unique/ambiguous/alias/multiple-session/unknown member 等测试和综合 Provider smoke。
5. Evaluation 记录关键消息后是否合理展开上下文，以及涉及成员身份时是否先识别候选。

### Stage C — Structured SQL Tools

1. `get_schema` 提供受边界控制的 physical SQLite schema；继承已有 secret/internal-only
   和 derived implementation table 边界，不新增 Analysis View Layer。
2. `execute_sql` 只允许 read-only SQL；判定不能只依赖简单 denylist，不能静默改写 SQL 或
   fallback 到 Retrieval。
3. Data Access Scope 是 hard boundary，由 Tool/adapter/connection 层强制；模型 SQL 是否
   自己写 `WHERE session_id` 不影响权限。结果必须有 max rows/equivalent execution bound
   和显式 truncation 语义。
4. 覆盖 COUNT、GROUP BY、time range、sender/session aggregation、合理 JOIN、no rows、
   malformed/read-write/DDL、scope escape、large result truncation 以及 schema → SQL 链路。
5. Structured question evaluation 验证统计问题优先使用 SQL，并检查 SQL answer 的
   Evidence/Citation policy、Trace 和 Failure Case。

## Acceptance criteria

- Stage A/B/C 各自的 acceptance criteria 在 `implement.md` 中逐项勾选后才允许进入下一阶段。
- 每个 checkpoint 有独立 commit，能单独回滚该批 Tool；不把六个工具做成不可分割提交。
- 每阶段的 unit/integration/provider smoke/Trace/Evaluation/Failure Case、Trellis validation
  和 interview-defense 更新均有证据；不以“tests pass”替代真实 Agent 行为验证。
- 最终 Agent-facing surface 恰好包含六个 canonical tools；`search_messages` 仍作为明确的
  legacy compatibility entry point 存在。
- 最终工作树 clean，测试、ruff、mypy、Trellis validation 和文档状态可复核。

## Out of scope

- 固定 hybrid/RRF/reranker、query rewrite、multi-query、embedding/chunking 参数调整。
- PostgreSQL、外部向量库、替代 embedding model、embedding dimension 变更。
- 第二套 Agent Runtime、QueryOrchestrator、Evidence/Trace 系统或 candidate state machine。
- Analysis Schema/Views、自动 `human_verified`、隐藏思维链持久化、真实聊天正文入 Git。

## Open decisions

没有需要在实现前改变已确认架构的产品决策。Evaluation 阈值和“正确工具序列”的唯一性
保持开放：记录 deterministic contract expectation 与 LLM quality judgement 的区别，
不伪造人工 ground truth。
