# ChatLab Evidence / Citation 研究

## Snapshot

- Repository: `ChatLab/ChatLab`
- Default branch: `main`
- Verified commit: [`f9b87c00ee886997c3f82d35dbcec9b1aa5e1264`](https://github.com/ChatLab/ChatLab/commit/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264)
- 核验日期：2026-08-21
- 核验时默认分支 HEAD 与 Stage 1.7 已引用的 baseline commit 相同。

## 1. ChatLab 实际存在两套 Citation / Evidence 机制

### 1.1 应用内：结构化 Evidence Content Block

ChatLab 的 `ChatEvidencePayload` 包含：

- `query / criteria / mode`
- payload `complete / partial / empty / unavailable`
- warnings
- `groups[]`
- group 的 `included / excluded / uncertain`
- source 的 `messageId / startMessageId / endMessageId / timestamp / senderName / snippet / sourceKind`

证据：[`evidence-types.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/core/src/ai/evidence-types.ts#L10-L86)。

该 payload 作为 Assistant Message 的 `contentBlocks` 持久化，前端渲染为可展开 Evidence Block，并用 `messageId` 点击回到聊天记录：

- [`chats.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/node-runtime/src/ai/chats.ts#L29-L58)
- [`EvidenceBlock.vue`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/src/components/AIChat/chat/EvidenceBlock.vue#L45-L47)
- [`EvidenceBlock.vue`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/src/components/AIChat/chat/EvidenceBlock.vue#L115-L151)

但 Evidence Block 与回答正文中的具体 claim 没有结构化绑定；用户能看到“回答 + 一组证据”，不能确定哪条证据支撑哪一句结论。

### 1.2 外部 CLI：`[#message_id]` 文本标记

ChatLab 的外部 Agent Skill 要求使用 `[#1021]`、`[#1021*]`、`[#1021-1024]` 引用消息；单消息 ID 可继续调用 context，合并 range 只是展示。

证据：[`chatlab-analyze/SKILL.md`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/skills/chatlab-analyze/SKILL.md#L70-L76)。

这套标记没有与应用内 `ChatEvidencePayload` 统一成一个 claim-to-source contract，因此 ChatLab 当前更像“两套可借鉴的局部机制”，而不是完整 Citation Architecture。

## 2. ChatLab 值得继承的部分

1. **Evidence 与普通回答文本分块持久化**：适合历史查看、UI 独立渲染和点击追溯。
2. **Source 保留稳定 Message Anchor**：`messageId` 不是纯文本引用；语义来源还可保留 message range。
3. **不持久化 raw dump**：Evidence payload 只保存安全 snippet、message anchor 与必要元数据，不保存原始全文或 embedding 文本。
4. **显式 incomplete / unavailable**：缺少 semantic / keyword capability、semantic partial 等会进入 warnings / payload status，而不是全部伪装成成功。
5. **当前数据库才是事实依据**：AI 历史、旧 AI 回答与压缩摘要只用于理解意图；聊天事实必须重新通过 Tool 获取。
6. **用户可追溯体验**：Evidence Panel 支持汇总、展开、状态展示和点击回原消息。

## 3. Trivae 不应复制的部分

### 3.1 不复制 `retrieve_chat_evidence` 专用 Tool

ChatLab 把 semantic + keyword retrieval、merge、dedup、time grouping、Evidence Judge 和 payload assembly 全部放进一个 Agent Tool：

[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L420-L466)。

Trivae Stage 1.4 已明确不提供 `retrieve_evidence` Tool，并要求 Agent 通过既有 Retrieval / SQL Tool 取回 Candidate Data，Evidence Selection 属于后续 Answer Synthesis 领域输出。复制 ChatLab Tool 会推翻已确认边界。

### 3.2 不复制固定中文关键词 Judge

ChatLab 用固定计划词和发生词把时间组判为 `included / excluded / uncertain`，非中文 locale 直接 `uncertain`：

[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L30-L39)，[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L221-L230)。

该规则只适用于少量“旅行是否实际发生”的例子，无法处理技术情报中的采用、回滚、反对、条件性建议、后续状态变化等 question-specific criteria。

### 3.3 不复制固定时间聚类作为 Evidence Group 语义

ChatLab 以 2 小时间隔、每组最多 5 个 source 进行分组：

[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L30-L34)，[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L240-L283)。

Trivae 的 Evidence Group 应围绕 claim / criterion / investigation finding 组织；时间接近只是可用线索，不能定义语义归属。

### 3.4 不把 retrieval path status 当作 answer sufficiency

ChatLab 的 `complete / partial / empty / unavailable` 由“是否有路径运行、是否有结果、是否出现 capability warning”计算：

[`retrieve-chat-evidence.ts`](https://github.com/ChatLab/ChatLab/blob/f9b87c00ee886997c3f82d35dbcec9b1aa5e1264/packages/tools/src/definitions/retrieve-chat-evidence.ts#L326-L335)。

它表达 retrieval execution completeness，不回答“这些来源是否足以支撑最终 claim”。Trivae 需要把两者拆成独立维度。

### 3.5 不依赖隐式当前 Session

ChatLab Tool 明确只查 CURRENT conversation，source 本身没有 `session_id`。Trivae 已支持跨群 / 跨 Session 调查，Citation Source 必须显式携带或可确定解析出 session identity。

### 3.6 不让 Evidence Block 与正文 claim 脱节

独立 Evidence Panel 很适合展示，但不能单独承担 Citation。Trivae 需要正文 claim-level binding，Evidence Panel 作为同一结构化 Citation 数据的展开视图，而不是第二份互不关联的数据。

## 4. 对 Trivae 的架构推论

1. 第一版应保留 ChatLab 的“结构化 Evidence Content Block + 点击追溯”，同时吸收 CLI 的稳定 message marker 思路，为正文提供 claim-level Citation。
2. Final Evidence 不由某个 Retrieval Tool 产出；由 Agent 在 Answer Synthesis 时基于当前 Run 的 Tool Results 选择和组织。
3. Citation ID 应引用结构化 Evidence Item；Renderer 决定显示为脚注、角标或其他 UI，不让显示字符串成为 source identity。
4. Message Source 应至少能够解析 `session_id + internal message_id`，再由 Canonical Store 追溯 source/platform message id。
5. Structured Result 需要独立 Source Reference（例如稳定 Tool Result identity + value/row locator）；不能伪装成 Message Source。
6. Citation Validator 可以确定性验证 ID 存在、来源属于当前 Run、在授权 Scope 内且可解析；它不能确定性证明自然语言 claim 与证据在语义上真的一致。
7. Retrieval completeness 与 evidence sufficiency 必须分轴表达。
8. Evidence-aware stopping 第一版不应引入 Runtime-owned State Machine；是否增加更强 completion gate，应由真实 Failure Case 与 Stage 1.10 Evaluation 决定。

## 5. ChatLab 上游演进信号

Evidence 功能从首个 payload/tool 到当前版本经历了多次专门修复：时间单位、时间过滤、semantic evidence text、UI compactness、streaming progress 和 source presentation 均单独调整。这说明 Evidence 同时横跨 Retrieval、Privacy、Persistence、Runtime Event 与 UI；Trivae 应先冻结领域边界和稳定 reference contract，再进入实现，避免把临时展示结构当长期数据模型。
