# Design

## 已确认状态与根因边界

生产 `QueryContext.available_capabilities` 只有名称；`SoftPlanner._build_prompt` 提供 JSON 结构与 zero-result 特例，但没有各工具的用途/禁用场景，也没有每步增量价值或证据关系的约束。Capability 类已有 `CapabilityMetadata.description`，SDK Tool adapter 另有较长参数/Runtime 描述，`SYSTEM_PROMPT` 也含 Runtime 策略。Planner 不应复制完整 Tool Schema 或 Runtime prompt。

v2 dependent Trace 的 Planner 保留实体与 firsthand-use 目标，随后 Runtime 自行发出泛化 `skills` 查询。因此本次只改善 Plan artifact，不能宣称修复 Runtime 失误。v2 archify direct hits 完整但 context anchor 不稳定；Planner 旧句“获取上下文”未解释哪个 direct hit 最有关系。Aggregation 有 SQL 后无意义检索风险；zero-result 有 Provider length 失败，旧 graceful skip 必须继续保留。

## ChatLab 对照

读取 commit `3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8`。其 PlannerInput 同时有 availableTools allowlist、availableCapabilities `{id,label,tools,guidance}`、dataSnapshot、assistant/skill/recent intent 摘要；Prompt 编码高层调查、evidence tool 优先和不做 max-timestamp 空步骤；Router 仅选择 planned_execution，validated plan 转 `buildPlanGuidance` 后仍进同一 Agent。Trivae 继承工具 allowlist 与 guidance 分离、软计划、精简步骤的思想，不复制 ChatLab 的跨群、segment、图表、`retrieve_chat_evidence` 等当前不存在的工具。

## 方案

`CapabilityRegistry` 暴露已注册 Tool 所持 Capability 的 `CapabilityMetadata`。Application 构造默认 `SoftPlanner` 时传入这些 metadata；测试注入的 Planner 不受影响。`SoftPlanner` 只从 metadata 取 canonical `name/description` 作为 purpose，并在 Planner 模块对现有稳定 Tool 名附加简短 planning guidance。summary 是 Planner-owned projection，不写入 `QueryContext`，Router 无需接收。最终 prompt 只列 allowlist 内 summary；未知 Tool 仍由原 parser 过滤。

Prompt 将 Plan 目标改为调查约束与证据策略：每步必须有 Query 未直接给出的价值；实体为 primary anchor；关系型证据围绕相关 direct target；使用 Tool 的具体触发条件；确定性结果和简单 lookup 不凑步骤。保留现有 schema、5/5 bounds 和 zero-result 特殊 contract。所有规则通用，不引用 Case 名或实体字面量。

Planner-only runner 使用同一 provider completion boundary，对固定的 P0 prompt 与 P1 当前 prompt 各独立运行；每次都通过同一个 SoftPlanner parser。实验只输入 Case query、locale、允许工具及既有 compact snapshot，不读 corpus、不开 Runtime。P0 固定为任务起始 commit 的 prompt，P1 固定代码版本。A/B 映射独立保存，Review packet 不包含版本标签。

## 边界与取舍

Capability metadata 的 purpose 是现有 source of truth；短 guidance 只表达 Planner 选择关系，不复制 SDK 参数或 SQL 文档。多出极小的 summary mapping，但避免 Router contract 改动与双份长期 Tool 文档。静态测试证明输入/解析契约；实际语言质量必须由重复 Provider 输出与人工复核支持。若 P1 仍不稳定，保留失败并停在本阶段。
