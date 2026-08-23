# DeepSeek 真实 Tool Calling 与 Provenance 稳定化

## Goal

在不放宽既有 Capability、ExecutionScope、Citation Finalizer 和 Conversation commit contract 的前提下，修复真实 DeepSeek 在

`search_messages → Retrieval → Tool Result → Final Synthesis → Citation Validation → Conversation Commit`

主链上的已观察失败。

## Requirements

- 先用 debug Trace 与真实 Provider smoke 获取脱敏的失败参数、失败阶段和 provenance locator 差异；不得先改业务代码。
- 保持 `SearchMessagesInput`、`ExecutionScope`、current-run provenance、trusted hydration 与 invalid citation 显式失败语义不变。
- 根据证据在 Tool schema/description、system prompt 或 provider-facing adapter 中实施最小修复；不把兼容逻辑放进 Retrieval Core。
- 如果确认模型可见的消息缺少可引用 provenance，补齐 Trivae-owned current-run projection；不得由 Finalizer 猜测 canonical 消息。
- 如果确认完整 locator 搬运是主要根因，必须记录 M5 Citation contract Reopen Reason、Evidence、Decision、Trade-off、Compatibility 与 Rollback。
- 为每个真实 Failure Case 增加 deterministic regression test，并覆盖合法参数、非法参数、scope 不变和 citation 拒绝边界。
- 使用真实 DeepSeek 完成至少 3 个小型数据检索 smoke，覆盖简单检索、filter/context、无结果或 partial；可行时补充多 Evidence Source case。
- 沉淀 Failure Case、根因、候选方案、最终选择、验证结果和质量门禁记录；不写入 API key、Authorization、完整聊天正文或 hidden reasoning。

## Acceptance Criteria

- [x] Trace 能给出每个真实失败 Tool Call 的安全参数投影、round、contract 字段错误或 SDK decoding 阶段归因。
- [x] Trace/诊断能给出每个失败 Citation locator 与 current-run provenance 集合的字段级差异分类。
- [x] 已证实的 `INVALID_ARGUMENT` 类型在真实 smoke 中消除或显著稳定，且非法输入的严格 contract regression 仍通过。
- [x] 已证实的 `UNRESOLVED_MESSAGE_SOURCE` 类型不再由合法 Tool Result 触发；模型编造 source 时 Finalizer 仍拒绝。
- [x] 至少一个真实 DeepSeek 数据检索 Query 完成 Runtime、Tool、Retrieval、Finalization、Conversation commit 和 `query.completed` 全链路。
- [x] Trace Store、Conversation commit boundary、ExecutionScope 和 M5 Citation semantics 未被重设计或静默放宽。
- [x] `pytest`、`ruff`、`mypy`、`git diff --check` 通过；提交前工作树只包含本任务变更。
