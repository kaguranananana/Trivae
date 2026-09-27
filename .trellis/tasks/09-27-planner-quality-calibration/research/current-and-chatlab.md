# Current state and ChatLab baseline

## Trivae 事实核对

- `QueryContext` 同时供 Router 和 Planner 使用，仅传 query、locale、prior context、data snapshot、`available_capabilities` 名称。`SoftPlanner` 原 prompt 除 JSON schema/zero-result 窗口提示外没有各 Tool 用途，也未要求 Step 提供额外调查价值。
- `CapabilityRegistry` 持有 Tool wrapper；各 wrapper 持有 Capability 实例，其 `CapabilityMetadata.description` 是 domain 层已有的 canonical purpose。SDK `openai_tools.py` 的 description 主要面向参数及 Runtime；`runtime/prompt.py` 的具体检索纪律属于 Runtime。两者不适合全文复制给 Planner。
- `QueryOrchestrator` 仅在 planned 路由调用一次 Planner，过滤后的 Plan 被 `render_plan_guidance` 注入同一个 Runtime；失效 Plan 走显式 `planner.failed/skipped`，不是另一个执行器。
- v3 已暴露 Trace 中，dependent r1 的第一步保留 `mattpocock`，但建议 lexical+semantic，第二步建议 `get_message_context`+`get_recent_messages`，第三步还带 `find_members`，第四步是无工具的整理。r2 第一步写“`mattpocock 或 skills`”，允许类别词独立代替实体；四步中后两步重复 context/区分/核查。
- archify r1 先 lexical 后 semantic，再“提取命中消息上下文”，且带 `get_recent_messages`；r2 仍建议 lexical+semantic 和笼统“对命中消息取上下文”。两次都未说明优先围绕最初分享/邀请/使用讨论展开，也未排除 star 更新、公告等误锚点。
- aggregation v3 Plan 在 schema→SQL 后加“必要时用最近消息或消息上下文校验该 UTC 窗口覆盖与边界”。该用户只要确定性 text/reply count，额外 retrieval 无明确需求。
- zero-result v3 Planner 以 `finish_reason=length`、`provider_length`、2048 output tokens 失败并显式 skipped；同一次 Runtime 仍完成完整空窗证明。本任务不得用重试隐藏此类失败。
- 已归档 root-cause 文档明确：dependent v2 的第一处分歧是 Runtime 后续 `skills` 查询造成 100/244 partial；Plan 保留实体，不能把该 Runtime 失败直接归因于 Planner。archify v2 direct hits 全部返回，变异点是 Runtime 的 context anchor 选择。Planner artifact 的语义质量问题可独立校准，但不能声称修好最终答案。

## ChatLab 实读版本

读取 GitHub `ChatLab/ChatLab` 当前 main 并在本地固定为 commit `3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8`：`planner.ts`、`planning-types.ts`、`__tests__/planner.test.ts`、`router.ts`、`__tests__/router.test.ts`、`cross-chat-agent.ts`、`chart-runtime.ts`。

- 类型允许 `availableTools` 与可选 `availableCapabilities` `{id,label,tools,guidance}` 并存，还可带 dataSnapshot、assistantSummary、skillSummary、recentIntentSummary。Planner Prompt 渲染 capability guidance；测试断言其可见。`chart-runtime.ts` 的图表 summary 由工具可用性、消息意图和 chart mode 决定，包含 id、双语 label、tool list 和最多一图的 guidance；这是已读到的具体 summary 来源。当前 `cross-chat-agent.ts` 实际传 `availableCapabilities: []`，因此这是已实现的可选输入机制，不应夸大成所有 ChatLab 路径都提供非空 summaries。
- ChatLab Prompt 对开放话题/多维回顾建议 reconnaissance，对 historical fact/evidence 在该工具存在时优先 `retrieve_chat_evidence`，并禁止仅为找最大时间戳造步骤。其 parser 限 5 steps/criteria、过滤未知工具；`buildPlanGuidance` 告知 Runtime 可更直接回答。
- `cross-chat-agent.ts` 在 planned_execution 时调用 Planner，将有效 Plan 作为 system prompt 软 guidance 接到原 `runAgentCore`；失败显示 plan_skipped。Router 分类不执行 Plan。
- Trivae 可继承 capability summary 与 allowlist 分离、少量有价值步骤和 soft guidance 边界；不复制 ChatLab 的 `retrieve_chat_evidence`、segment、chart/cross-chat 工具或其特定策略，因为 Trivae 当前 Tool Surface 没有对应能力。

## 输入差异与修改假设

旧 Trivae Planner 能列工具名却不能从输入识别其适用/禁用情境，这足以解释其泛化工具建议和无意义验证的可能性；实际输出已证明这些缺陷存在。实体稀释和弱 context relation 同时与旧 prompt 没有对应约束一致，但因模型随机性不能仅凭源码断定唯一因果。P0/P1 重复 Planner-only 实验检验这个最小假设，不推断 Runtime 最终表现。
