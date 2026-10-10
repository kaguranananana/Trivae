# Trivae 架构图交付

本组图于 2026-10-10 使用已安装的 Archify 3.0.1 生成，依据源码版本 `9e531eb8793757eb00bb41b5869f045f212a13a4`。主图只呈现实际实现的组件与调用关系，条件能力明确标注。仓库没有根目录 README；本次阅读了 Evaluation README、架构文档、Agent Runtime 规范、项目工作流与相关源码。

## 打开与编辑

| 图表 | 可交互 HTML | 可编辑 JSON | 反映的内容 |
| --- | --- | --- | --- |
| Architecture | [trivae-system.html](architecture-trivae-system-20261010-104943/trivae-system.html) | [candidate.json](architecture-trivae-system-20261010-104943/candidate.json) | Query Plane、Data Plane、Agent Runtime 与 Tool/Retrieval、Evidence、Conversation、Trace 的依赖边界 |
| Sequence | [trivae-request.html](sequence-trivae-request-20261010-104943/trivae-request.html) | [candidate.json](sequence-trivae-request-20261010-104943/candidate.json) | 真实 Web 查询入口，经上下文、路由、可选规划、模型工具循环、最终化、提交，再返回；含重要失败与取消条件 |
| Data Flow | [trivae-evidence.html](dataflow-trivae-evidence-20261010-104943/trivae-evidence.html) | [candidate.json](dataflow-trivae-evidence-20261010-104943/candidate.json) | QQ 导出文件、Canonical 事实、显式派生索引、独立检索、Tool Result、模型候选到最终引用 |

HTML 可直接在浏览器打开，包含完整的 inline SVG 与 Archify Viewer Runtime。保留节点聚焦、来源徽标、上下游探索、有向路径探索、缩放、明暗主题与导出功能。长时序图采用纵向页面滚动；条件行不表示每次请求必然执行。State Stores 泳道合并展示 Conversation 与 Trace 的逻辑组件，调用标签分别指明读写对象。

SSH origin 按 Skill 契约使用 `local-only` 源码关联：节点保存完整仓库相对路径和行区间，不伪造外部 Web 链接。关系 Schema 不接受 `sources` 字段，因此逐边源码依据保存在 [evidence-20261010-104943.json](evidence-20261010-104943.json)，用稳定 ID 与三张 JSON 对应。路径探索只遍历作者声明的有向边，不表示实际时序或自动证明运行因果。

修改 JSON 后，应重新执行完整 `finalize`，不得直接编辑已验证 HTML。示例命令中的 `ARCHIFY_CLI` 设为已安装 Skill 的 `bin/archify.mjs`：

```sh
node "$ARCHIFY_CLI" finalize architecture \
  .archify/architecture-trivae-system-20261010-104943/candidate.json \
  .archify/architecture-trivae-system-20261010-104943/trivae-system.html \
  --repo-root . --quality showcase --out-dir .archify/architecture-trivae-system-20261010-104943/review-next --json
```

## 实现核实

| 设计 | 当前状态与范围 | 关键源码 |
| --- | --- | --- |
| Context Assembly | 已实现职责，分布在 Application 会话历史投影、QueryContext/AgentRunRequest 编译与 Runtime input/instructions；没有独立 ContextAssembly 服务。历史 Evidence 只作指代理解，不能当作本轮 fresh citation。`data_snapshot` 默认空，不暗示入口自动扫描资料。 | [application.py:684](../src/trivae/bootstrap/application.py#L684)、[query/contracts.py:151](../src/trivae/query/contracts.py#L151)、[conversation/contracts.py:172](../src/trivae/conversation/contracts.py#L172)、[openai_adapter.py:1508](../src/trivae/query/runtime/openai_adapter.py#L1508) |
| Router | 已实现 RuleRouter；高置信规则直接选路，模糊请求调用 completion。支持可配置 Jev primary/shadow；shadow 不决定主路径。失败可保留规则，显式 degraded。 | [router.py:193](../src/trivae/query/router.py#L193)、[application.py:727](../src/trivae/bootstrap/application.py#L727) |
| Planner | 已实现 SoftPlanner，一次模型调用，输出经过解析与校验的 soft guidance；只在 planned_execution 调用。分类失败后无计划继续并记诊断；不执行步骤、不接管工具参数。 | [planner.py:185](../src/trivae/query/planner.py#L185)、[orchestrator.py:302](../src/trivae/query/orchestrator.py#L302) |
| Agent Runtime | 已实现 OpenAIAgentsRuntimeAdapter 与 SDK Runner.run_streamed，支持模型/工具循环、预算、max-turn 终态、显式 failure 与 cooperative abort。两种路由共用同一 Runtime。 | [openai_adapter.py:1182](../src/trivae/query/runtime/openai_adapter.py#L1182)、[orchestrator.py:421](../src/trivae/query/orchestrator.py#L421) |
| Tool / Retrieval | 已实现 Registry、SDK adapters、Scope-enforced Capability，以及 Structured、FTS5 Lexical、sqlite-vec Semantic、消息上下文与成员检索。默认工具包含 lexical_search、semantic_search、get_recent_messages、get_message_context、find_members、get_schema、execute_sql。search_messages 注册但不在默认 allowlist。 | [application.py:1098](../src/trivae/bootstrap/application.py#L1098)、[query/contracts.py:109](../src/trivae/query/contracts.py#L109)、[registry.py:53](../src/trivae/capabilities/registry.py#L53)、[tools.py:75](../src/trivae/capabilities/tools.py#L75) |
| Evidence / Citation | 已实现 Candidate → Final Evidence → Citation-bound Answer 的 Host finalization、current-run provenance 与 scope 校验、来源 hydrate、引用绑定。局部错误允许 deterministic recovery 并标 degraded；可信来源或 scope 错误 failed。该实现不等于自动证明每个自然语言 Claim 语义正确。 | [evidence.py:2646](../src/trivae/query/evidence.py#L2646)、[evidence.py:3139](../src/trivae/query/evidence.py#L3139)、[orchestrator.py:490](../src/trivae/query/orchestrator.py#L490) |
| Conversation Store | 已实现持久化历史、scope 绑定、会话 CRUD 和单事务 User/Assistant turn 提交；保存 Artifact、trace_id、过程摘要。失败/aborted 不提交成功 turn，但新请求已经创建的空会话可能存在。 | [sqlite.py:247](../src/trivae/conversation/sqlite.py#L247)、[application.py:763](../src/trivae/bootstrap/application.py#L763)、[application.py:942](../src/trivae/bootstrap/application.py#L942) |
| Trace Store | 已实现 normalized event、FailureInfo、normal/debug capture、SQLite append 与终态；Store/capture 错误进入 TRACE 日志与 warnings，业务可继续。自动 retention/删除传播未发现实现。 | [collector.py:178](../src/trivae/observability/collector.py#L178)、[collector.py:316](../src/trivae/observability/collector.py#L316)、[sqlite.py:36](../src/trivae/observability/sqlite.py#L36) |
| 对外接口 | 已实现 CLI/Textual TUI 与 Vue Web/FastAPI，本次时序从 POST /api/query/stream 开始，返回 NDJSON。scope 预检、stop、断连、会话/source inspection/Trace API 已存在。文档规划的 /api/v1 尚未采用。 | [client.ts:90](../web/src/api/client.ts#L90)、[routes.py:37](../src/trivae/interfaces/web/routes.py#L37)、[streaming.py:130](../src/trivae/interfaces/web/streaming.py#L130)、[server.py:53](../src/trivae/interfaces/web/server.py#L53) |
| Ingestion / 索引 | 已实现 QQ JSON 文件批量导入、规范化、去重、来源与导入诊断。FTS5 显式全量 rebuild，Semantic time-aware Parent/Child → 本机 Qwen3 embedding → vec0 显式 rebuild。导入不会自动同步派生索引。 | [importer.py:31](../src/trivae/data/ingestion/importer.py#L31)、[sqlite_lexical.py:47](../src/trivae/data/storage/sqlite_lexical.py#L47)、[builder.py:80](../src/trivae/retrieval/semantic/builder.py#L80) |

默认物理布局：Canonical、FTS5、Conversation、Trace 共用主 SQLite 文件；Semantic 使用独立 `*.semantic.sqlite3`。Evaluation 与 Feedback 子系统也已实现，默认独立 SQLite，作为辅助能力在图卡说明，不展开为用户查询主链路。[application.py:161](../src/trivae/bootstrap/application.py#L161)、[application.py:1087](../src/trivae/bootstrap/application.py#L1087)、[application.py:1131](../src/trivae/bootstrap/application.py#L1131)

外部依赖以 [pyproject.toml](../pyproject.toml) 为依据：FastAPI/Uvicorn、OpenAI Agents SDK、sqlite-vec、Textual；sentence-transformers 是 semantic extra。LLM 使用配置选择的 OpenAI-compatible Chat Completions endpoint；Qwen3 Embedding 是本机模型，不是独立托管向量服务。未读取私密 `.env`，因此不把当前启用 Provider、Jev mode、部署端口或现有索引可用状态当作已确认事实。

## 已有异常、恢复与规划差异

- `AsyncOpenAI(max_retries=0)`；Router 与 Planner completion 不自动重试。[openai_adapter.py:1144](../src/trivae/query/runtime/openai_adapter.py#L1144)
- OpenCode Go 有一次条件 JSON finalization 修复：原回合有工具、未返回 function call 且最终输出不是 JSON object 时，移除工具重发一次；不属于通用网络重试，也不表示当前配置必然启用。[openai_adapter.py:393](../src/trivae/query/runtime/openai_adapter.py#L393)
- Semantic 缺失/stale/building/failed 显式暴露错误；检索不自动降级为 Lexical。两种检索供 Agent 独立选择，没有自动融合或独立 reranker。[retrieval.py:73](../src/trivae/retrieval/semantic/retrieval.py#L73)
- 当前采集范围只确认 QQ exporter JSON。未发现 NapCat/QQ 实时采集器、在线消息总线、OCR/ASR 处理流水线；不根据文档的来源枚举补画节点。
- Context Assembly 的职责已经实现，但独立服务/独立类未实现；Planner 不是可执行 Workflow，不是第二个 Agent Runtime。
- Trace/Evaluation 和 Web 已有代码实现；部分架构/阶段文档仍写 Pending，图表以源码为准。生产级 Trace retention、跨环境迁移/部署和长期 human-verified quality calibration 不作为已完成能力。

## 验证与视觉检查

三张图的最终 `finalize` 均为 exit 0，`validate`、`deliver`、严格 provenance `check`、真实 Chrome `browser-check` 全部通过，最终诊断为零。必要结果：

| 图表 | 最终规格/产物门禁 | 当前浏览器证据 | 当前截图索引 |
| --- | --- | --- | --- |
| Architecture | [finalize-summary.json](architecture-trivae-system-20261010-104943/trivae-system.finalize-summary.json) | [browser-check.json](architecture-trivae-system-20261010-104943/trivae-system.browser-check.json) | [visual-check.html](architecture-trivae-system-20261010-104943/visual-check/trivae-system.visual-check.html) |
| Sequence | [finalize-summary.json](sequence-trivae-request-20261010-104943/review-5/trivae-request.finalize-summary.json) | [browser-check.json](sequence-trivae-request-20261010-104943/review-5/trivae-request.browser-check.json) | [visual-check.html](sequence-trivae-request-20261010-104943/visual-check-5/trivae-request.visual-check.html) |
| Data Flow | [finalize-summary.json](dataflow-trivae-evidence-20261010-104943/review-5/trivae-evidence.finalize-summary.json) | [browser-check.json](dataflow-trivae-evidence-20261010-104943/review-5/trivae-evidence.browser-check.json) | [visual-check.html](dataflow-trivae-evidence-20261010-104943/visual-check-5/trivae-evidence.visual-check.html) |

每张当前 HTML 的 native visual-check 已通过 containment、readability、viewer chrome、theme 与四张 capture 检查，覆盖 1440×900 / 2048×1320 的明暗主题。截图不自动证明视觉质量；本次另行人工式目视检查了代表性明暗截图，确认主链、箭头、标签与节点层次可读，并检查了 [时序图后半段](sequence-trivae-request-20261010-104943/sequence-lower-supplemental.png)。目视结论与实际看过的截图列于 [quality-report-20261010-104943.json](quality-report-20261010-104943.json)，原始 native receipt 的 `visualReview: pending` 保持不变。

额外检查：[viewer-interaction-20261010-104943.json](viewer-interaction-20261010-104943.json) 记录三张图真实 focus 与 directed Route Probe 的通过结果；[source-range-check-20261010-104943.json](source-range-check-20261010-104943.json) 核对 32 个源码文件、151 处来源区间、关系 ID 与固定版本内容。区间检查证明定位有效，架构含义由实际调用点阅读和关系账本支持，不将行号合法性等同于语义正确性。

`review-4`、旧 `visual-check` 与早期失败 receipt 保留用于诊断历史；Sequence/Data Flow 当前以 `review-5` 和 `visual-check-5` 为准。此次仅添加 `.archify/` 文件，未修改业务源码、配置或依赖；已有 `.opencode/package.json` 改动未纳入本次提交。

提交前 `git diff --cached --check` 检出三份原生 HTML 各 15 行空白行尾空格，根因为 Archify `assets/template.html` 自带格式。保留原生输出与验证回执一致；未后处理 HTML 或修改 Skill。其余新增文件空白检查通过，格式提示记录在质量报告中。
