# Trivae Agent 岗简历轻量修改稿

## 推荐直接使用

### Trivae 高噪声群聊分析 Agent｜个人项目｜2026.08–至今

**技术栈：** Python / OpenAI Agents SDK / SQLite / FTS5 / sqlite-vec / FastAPI / Vue 3

面向高噪声群聊构建检索分析 Agent，将 88 份来源文件中的 81.2 万条真实聊天记录（2026-10-20 冻结快照）统一为可追溯、可检索的事实库，支持多策略检索、受约束 Agent 执行、证据化问答与可复现 Evaluation。

- **数据工程与可追溯性：** 针对多来源聊天记录重复导入、内容冲突及失败难追溯的问题，设计统一 Canonical Store，以文件级事务实现幂等导入、冲突留痕及 partial / failed 状态管理，并保留来源与导入批次 provenance；将 FTS5、向量索引作为可重建派生数据与原始事实解耦，使索引策略调整无需修改 Canonical Message。
- **检索召回与上下文建模：** 针对关键词精确查询、语义改写、时间浏览和上下文恢复的不同召回特征，拆分 lexical / semantic / structured / context 多路检索；定位 FTS5 `unicode61` 对连续中文分词造成的短词漏召回并实现 CJK bigram v2，语义检索采用 Time-aware Parent / Small Child 分块，命中后回源原始消息恢复上下文；在 10 个可穷举精确谓词 Query 上验证 lexical Recall@10 达到 33/33。
- **Agent 执行与可靠性：** 基于 OpenAI Agents SDK 构建工具调用型 Agent，针对复杂查询中的错误工具选择、循环调用、结果膨胀和超时问题，引入复杂度路由、受限规划及统一执行编排；限制 Tool Round 和共享 Tool Result Budget，为 Router / Planner 设置独立 Timeout 并支持运行中 Cancel，在工具预算耗尽后进入一次无工具 Final Synthesis，使简单查询与复杂调查共享同一执行链路和终态语义。
- **答案可信性与引用约束：** 针对模型可能引用未实际检索、旧请求或越权数据，以及在检索失败时错误回答“没有结果”的问题，将 Claim、Evidence、Citation 显式关联，并在答案生成后校验来源是否属于当前 Run 和授权 Scope；引用仅从可信 Tool Result 回填，同时要求 zero-result 具备完整检索证据，避免无来源、跨请求及假阴性结果进入最终回答。
- **评测与质量治理：** 基于版本化 GT，在 81.2 万条消息冻结快照上完成 20 题 40 次真实 Agent A/B 及 4 次复测，沿召回、模型可见与最终引用分层定位失败；结合证据覆盖、事实引用复核和 Token 成本否决退化 Prompt 候选，保留逐题分母、Trace 与请求级预算账本。

## 历史轻量修改记录

1. 根据 Git 历史，将项目时间补为 `2026.08–至今`。
2. 将容易被理解成“14 个群”的“14 个来源”改为“14 份来源文件”。
3. 修正 `Recall@'10` 的排版，并用“可穷举精确谓词 Query”说明指标范围。
4. 将笼统的“支持 Timeout / Cancel”收紧为 Router / Planner 独立 Timeout 与运行中 Cancel。
5. 明确 47 条 GT 的组成，以及 185 次运行只来自 37 条 Development Case × 5 Variant。
6. 将 `production-path` 换成“应用查询链路”，避免被误解为已经生产上线。

其余结构、技术重点和叙述顺序均保留原稿，不额外加入 Multi-Agent、Memory、Reranker、生产 SLA 或未经验证的效果提升。

## 2026-10-20 第五条证据更新

本次仅更新当前快照规模及第五条。未取得可信质量提升，候选已回退；不写提升百分比。第四条来源约束仍不能保证语义全部正确，第二条33/33是历史10个精确谓词Query，不外推到当前全语料。

详见[证据账本与面试](Evaluation优化-证据账本与面试.md)和[端到端实验](Evaluation端到端质量实验-20261020.md)。旧47条人工GT、185次五Variant历史运行依然有效，但不与本轮20题A/B合并成同一质量分母。
