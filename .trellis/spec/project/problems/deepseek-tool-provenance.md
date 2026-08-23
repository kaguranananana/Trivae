# DeepSeek Tool / Provenance contract failure

## Problem

真实 DeepSeek 在聊天检索 Query 中反复提交 `limit` 大于 trusted `ExecutionScope.max_results` 的 Tool Call，并在一次多 Tool Result 回合中把空结果 Tool 的父级 identity 与另一 Tool Result 的 message item locator 拼成一个 Citation source。

## Evidence

- SDK `0.22.0` 的原始 Function Tool schema 只有 `limit: integer`、默认值 20，没有本次 trusted result bound 或字段行为说明。
- 真实 smoke 捕获到 `limit=20`/`10`，而 `ExecutionScope.max_results=5`；`SearchMessagesInput` 构造成功，Capability 在 Retrieval 前返回 `INVALID_ARGUMENT`。
- 真实 unresolved run 中，Tool Call 5 为 `status=ok` 且 `message_items=0`，Tool Call 6 为 `status=partial` 且有 5 个 message items。模型 source 的 `tool_call_id/tool_result_id` 指向 Tool Call 5，`result_item_id/session_id/internal_message_id` 指向 Tool Call 6；Finalizer 返回 `UNRESOLVED_MESSAGE_SOURCE`。
- 当前 `ToolResultRecord` 已将 hits 与 `expanded_messages` 都建立为 message provenance；因此不是 expanded context 缺少 locator。

## Root Cause

Provider-facing schema 没有表达动态 trusted result bound；此外原 provenance 投影把父级 `run/tool/result` 与子级 message locator 分成两层，要求模型在最终 JSON 中再次组装，DeepSeek 在多个 Tool Result 之间发生了字段串接。

## Options

1. 在 Capability 中 clamp 或截断 `limit`：会隐藏模型违规并改变 trusted contract，拒绝。
2. 在 Finalizer 中相似匹配或自动替换 source：会破坏 current-run deterministic provenance，拒绝。
3. 使用 provider-facing schema/description 表达动态 result bound，同时保留 Capability 强校验；让每个 message/structured provenance entry 携带完整父级 identity，并用 Prompt 约束单 entry 复制。
4. Reopen M5 Citation contract，引入 `source_ref`：当前证据可通过 self-contained projection 解决，暂不采用。

## Decision

采用选项 3：

- `OpenAIAgentsRuntimeAdapter` 将当前 `ExecutionScope.max_results` 以 provider schema 的 `minimum`/`maximum`/bounded default 和 description 表达；trusted scope 仍只在 RuntimeContext/Capability 内执行。
- `SearchMessagesInput` 在自身边界统一严格校验 `sender_user_ids` 与 `message_types`，不自动修正空列表、错误类型、非法 limit、时间范围或 context window。
- `ToolResultRecord.to_model_provenance()` 为每个 source entry 重复完整 `run_id/tool_call_id/tool_result_id`；Prompt 明确空 source 列表不得生成 message citation，且不得跨 Tool Result 组合字段。
- Finalizer、ExecutionScope、Conversation commit boundary 和 `UNRESOLVED_MESSAGE_SOURCE` 语义不变。

## Why

修复直接位于 provider-facing boundary，解决了真实模型看到的 schema/provenance 搬运问题；Capability 和 Finalizer 仍是独立的确定性最后防线。没有把 Retrieval Core、SQLite 或 M5 领域语义承担 provider 兼容逻辑。

## Result

修复后 4 个真实 DeepSeek case（simple keyword、trusted session filter、context expansion、no result）全部满足：`termination=completed`、`QueryResult.is_successful=True`、无 Tool Error、Finalization completed、Conversation message count 2、Trace terminal `completed` 且 `complete`。其中 partial Retrieval 仍显式保留 partial limitation；无结果 case 以无 Evidence 的结构化答案完成。

## Trade-off

- Tool schema 会暴露本次 Query 的结果数量上限，但不暴露 session/time scope，也不能改变本地 trusted enforcement。
- 每个 provenance entry 重复少量 parent identity，增加模型可见 payload，但降低跨结果拼接概率；当前保留完整 locator contract，避免无证据引入 `source_ref` Reopen。
- Prompt 约束不能保证模型永不编造 source；Finalizer 仍会拒绝未知 locator。

## Regression

- schema regression 验证 `limit` 的动态 bound、default、字段说明和 `strict_json_schema=False` 的 DeepSeek 兼容选择。
- Capability regression 验证 keyword/list/timestamp/range/limit/context/unknown field 违规不被自动修正。
- Provenance regression 验证每个 source entry 自包含、expanded message 有 locator、跨 Tool Result 混合 locator 继续返回 `UNRESOLVED_MESSAGE_SOURCE`。
- 真实 smoke 4-case 验证 Tool → Retrieval → Finalization → Conversation commit → Trace terminal 主链。

## M5 Citation Reopen

未重开。当前问题可由 provider-facing provenance projection 和 Prompt 约束解决，M5 Finalizer 的 deterministic current-run validation 保持 Confirmed 语义。
