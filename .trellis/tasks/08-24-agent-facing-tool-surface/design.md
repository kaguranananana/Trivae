# Design

## Scope boundary

本任务的最小行为变化是：把已存在的 lexical/semantic retrieval capability 以两个
canonical Tool 默认交给现有 Agent Runtime，并在同一条正式链路上按 A/B/C 顺序补齐四个
已确认的 capability/tool contract。不会新建 runtime、orchestrator、evidence 或 trace
实现，也不会修改 Qwen、embedding dimension、semantic chunking 或检索融合策略。

## Existing-to-target flow

```text
User Query / Interactive CLI / Evaluation Case
        ↓
QueryRequest + ExecutionScope
        ↓
Router → optional Planner guidance
        ↓
existing Agent Runtime
        ↓
model-visible Tool adapters
        ↓
CapabilityRegistry
        ↓
Capability → Retrieval / Canonical SQLite / derived index
        ↓
ToolResultRecord + Evidence/Citation + TraceCollector
        ↓
existing final synthesis / Conversation Store
```

Tool adapter 只负责 model-visible schema、参数解析、scope 传递、Tool Envelope 和 trace
边界；Capability 负责可复用的业务能力；Registry 负责名字到 capability/tool 的正式绑定。

## Compatibility and naming

- `lexical_search` 是新的正常 Agent-facing lexical 名称。
- `semantic_search` 是正常 Agent-facing semantic 名称，并保留已有 explicit unavailable/stale
  failure 行为。
- `search_messages` 保留为 legacy compatibility Tool/entry point，供旧测试、旧 Evaluation
  和显式 callers 使用；不把它继续作为正常 Agent 默认 surface。
- 不对现有旧调用方做机械 rename；代码和文档只在 canonical Agent surface、legacy boundary
  和 compatibility test 中清楚区分三者语义。

## Stage A design

默认 `QueryRequest.available_capabilities` 和由它编译出的正常 Interactive CLI Runtime request
使用 `("lexical_search", "semantic_search")`。低层直接构造的 `AgentRunRequest` 继续默认
`("search_messages",)`，作为明确的 legacy compatibility boundary；显式传入的 capability
列表仍按既有契约工作，因此旧 caller 不被静默改写。

两个 retrieval Tool description 只提供选择信号：

- lexical：repository、URL、code、error message、nickname、exact phrase、明确技术名词等
  精确字符串/标识符。
- semantic：paraphrase、概念、模糊回忆、原文没有复现用户措辞的自然语言意义。

Agent 的实际选择、是否第二次调用和最终回答仍由既有 Runtime/model loop 完成。Tool layer
不自动 hybrid、不自动重试、不静默改变数据源。空结果和 capability unavailable/stale 仍以
显式 Tool Envelope/error 进入同一 Trace。

Tool Selection evaluation 使用 diagnostic case 的 `expected_behavior`/category 作为版本化
contract expectation；模型实际行为单独记录为观察结果，不把“首个工具必须唯一正确”硬编码
成脚本。既有 paired retrieval evaluation 继续独立保留。

## Stage B design

`get_message_context(message_id)` 只调用已经存在的 canonical read/context expansion 能力，
以 stable `message_id` 定位，沿用 `ExecutionScope`、bounded window、conversation boundary
和 truncation 语义。Search Tool 的 bounded local context 不改变；显式 context call 只在
Agent 判断证据不足时发生。

`find_members` 通过现有 identity/membership 数据和 scope 返回候选、session 关联及匹配依据。
多候选是正常结果而不是错误；unknown member 也必须是可解释结果。后续 Retrieval/SQL 只能
使用 Agent 明确选择的候选，不在 Tool 中偷偷 resolve 唯一身份。

## Stage C design

`get_schema` 和 `execute_sql` 复用 canonical SQLite connection/access path。Schema 输出只
包含允许 Agent 理解的 physical tables/columns/relationships，延续现有 secret 和 internal
implementation 边界，不创建 analysis views。

`execute_sql` 的只读确认使用适合 SQLite 的结构化/驱动级查询验证与连接权限，而不是一个
简单字符串 denylist；阻断 write、DDL、事务改变和 scope escape，并对每次执行应用硬 scope
和 max rows/equivalent bound。模型提供的 SQL 不承担权限责任；不自动加 WHERE/LIMIT、不
改写、不 fallback。成功、no rows、truncated、malformed、blocked 和 scope violation 均
沿用 Tool Envelope、Trace 和 Evidence 的显式状态。

## Trace and evaluation contract

每个 Tool action 继续在现有 normalized trace boundary 记录：visible capabilities、selected
tool、公开参数、scope-safe result summary、tool error/empty/truncated state、Evidence/Citation
以及最终 answer。不得记录 hidden chain-of-thought 或超 scope 数据。

Evaluation 按阶段增加 diagnostic cases，但不删除既有 retrieval benchmark：

1. A 记录 tool availability、首个工具、完整序列、round/count、结果支持度、错误和成本。
2. B 记录 search→context 的必要性、member ambiguity 处理和 scope。
3. C 记录 schema→SQL、聚合正确性、read-only/scope enforcement 和 citation。

对于 lexical→semantic 和 semantic→lexical 等价调查序列，评估任务成功、明显错误调用、
Evidence 和成本，不强制唯一序列。

## Rollback boundary

- Checkpoint A 只改变默认 Agent surface、selection descriptions 和 A evaluation；legacy
  `search_messages` 注册及显式 contract 不删除。
- Checkpoint B 只新增 context/member 的 capability、adapter、evaluation 和 docs；回滚不会
  影响 A 的双 retrieval default。
- Checkpoint C 只新增 schema/SQL 的 capability、adapter、scope/read-only enforcement、
  evaluation 和 docs；回滚不会影响 A/B。

每个 checkpoint 在独立 commit 中完成，出现真实 Failure Case 时先定位 Tool Contract、
Runtime、Retrieval、Context、Identity、SQL、Scope、Evidence、Provider 或 Evaluation 的
归属，再做最小修复。
