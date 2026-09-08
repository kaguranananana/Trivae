# Trivae Agent 岗简历轻量修改稿

## 推荐直接使用

### Trivae 高噪声群聊分析 Agent｜个人项目｜2026.08–至今

**技术栈：** Python / OpenAI Agents SDK / SQLite / FTS5 / sqlite-vec / FastAPI / Vue 3

面向高噪声群聊构建检索分析 Agent，将 14 份来源文件中的 47.3 万条真实聊天记录统一为可追溯、可检索的事实库，支持多策略检索、受约束 Agent 执行、证据化问答与可复现 Evaluation。

- **数据工程与可追溯性：** 针对多来源聊天记录重复导入、内容冲突及失败难追溯的问题，设计统一 Canonical Store，以文件级事务实现幂等导入、冲突留痕及 partial / failed 状态管理，并保留来源与导入批次 provenance；将 FTS5、向量索引作为可重建派生数据与原始事实解耦，使索引策略调整无需修改 Canonical Message。
- **检索召回与上下文建模：** 针对关键词精确查询、语义改写、时间浏览和上下文恢复的不同召回特征，拆分 lexical / semantic / structured / context 多路检索；定位 FTS5 `unicode61` 对连续中文分词造成的短词漏召回并实现 CJK bigram v2，语义检索采用 Time-aware Parent / Small Child 分块，命中后回源原始消息恢复上下文；在 10 个可穷举精确谓词 Query 上验证 lexical Recall@10 达到 33/33。
- **Agent 执行与可靠性：** 基于 OpenAI Agents SDK 构建工具调用型 Agent，针对复杂查询中的错误工具选择、循环调用、结果膨胀和超时问题，引入复杂度路由、受限规划及统一执行编排；限制 Tool Round 和共享 Tool Result Budget，为 Router / Planner 设置独立 Timeout 并支持运行中 Cancel，在工具预算耗尽后进入一次无工具 Final Synthesis，使简单查询与复杂调查共享同一执行链路和终态语义。
- **答案可信性与引用约束：** 针对模型可能引用未实际检索、旧请求或越权数据，以及在检索失败时错误回答“没有结果”的问题，将 Claim、Evidence、Citation 显式关联，并在答案生成后校验来源是否属于当前 Run 和授权 Scope；引用仅从可信 Tool Result 回填，同时要求 zero-result 具备完整检索证据，避免无来源、跨请求及假阴性结果进入最终回答。
- **评测体系与故障归因：** 针对 Agent 回答质量难复现、失败原因容易混在最终准确率中的问题，固定 Snapshot、Environment 与人工 Ground Truth，并设计 5 组 Controlled Variant 对检索与上下文能力进行消融；完成 47 条人工裁决 GT（37 Development + 10 Calibration），基于 37 条 Development Case 完成 185 次真实 Provider、应用查询链路运行；通过 append-only Trace 将失败拆分至 Provider、Retrieval、Ranking、Context 与 Finalization，并据此发现并修复逐调用排名事实丢失和异步 Provider 生命周期两类评测链路缺陷。

## 本轮只做了哪些修改

1. 根据 Git 历史，将项目时间补为 `2026.08–至今`。
2. 将容易被理解成“14 个群”的“14 个来源”改为“14 份来源文件”。
3. 修正 `Recall@'10` 的排版，并用“可穷举精确谓词 Query”说明指标范围。
4. 将笼统的“支持 Timeout / Cancel”收紧为 Router / Planner 独立 Timeout 与运行中 Cancel。
5. 明确 47 条 GT 的组成，以及 185 次运行只来自 37 条 Development Case × 5 Variant。
6. 将 `production-path` 换成“应用查询链路”，避免被误解为已经生产上线。

其余结构、技术重点和叙述顺序均保留原稿，不额外加入 Multi-Agent、Memory、Reranker、生产 SLA 或未经验证的效果提升。
