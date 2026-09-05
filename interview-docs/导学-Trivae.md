# Trivae 项目导学

> 文档归档：`interview-docs/`，与项目面经及后续面试材料统一维护。
>
> 项目事实边界：本文基于当前仓库源码、Trellis 架构文档与 `resume-benchmark-v1` 事实索引整理。当前可证明的是 Development 基线与工程验证；Holdout 尚未生成，个人职责边界与线上业务指标待补，不据此推断。

## 1. 前置知识（面试高频标注）

| 知识点 | 为何需要 | 在本项目中的位置 | 高频度 |
| --- | --- | --- | --- |
| Python 类型、dataclass、Protocol | 理解领域契约、端口抽象和显式错误模型 | `src/trivae/**/contracts.py`、`src/trivae/data/model.py` | 高频 |
| SQLite 事务、FTS5、只读 SQL | 理解规范化存储、幂等导入、关键词检索和结构化查询边界 | `src/trivae/data/storage/`、`src/trivae/retrieval/sql.py` | 高频 |
| 向量检索与 Embedding | 理解语义索引身份、向量生成、近邻召回和索引失效 | `src/trivae/retrieval/semantic/` | 高频 |
| RAG、Agent Tool Calling | 理解自然语言问题如何转成检索动作并进入答案生成 | `src/trivae/query/`、`src/trivae/capabilities/` | 高频 |
| 证据与引用建模 | 理解为什么模型文本不能直接提交，以及引用如何绑定当前运行证据 | `src/trivae/query/evidence.py`、`src/trivae/query/completion.py` | 高频 |
| 状态机与异步流式协议 | 理解查询生命周期、取消、增量输出和终态收敛 | `src/trivae/query/streaming.py`、`src/trivae/interfaces/web/streaming.py` | 中高频 |
| 可观测性与 Failure Attribution | 理解 append-only Trace、因果关联和错误归属 | `src/trivae/observability/`、`src/trivae/evaluation/benchmark/failures.py` | 高频 |
| 离线评测与消融实验 | 理解 GT、Snapshot、Variant、分母、paired comparison 和数据泄漏边界 | `src/trivae/evaluation/`、`evaluation/` | 高频 |
| FastAPI、Vue 3、Pinia | 理解 Web 薄适配层、NDJSON 流和前端投影 | `src/trivae/interfaces/web/`、`web/src/` | 中频 |

## 2. 重点亮点与学习顺序（先看这个）

| 亮点标题 | 为什么重要 | 通用技术关键词 | 先看哪些文件 | 建议学习顺序 |
| --- | --- | --- | --- | --- |
| 数据规范化与索引分层 | 原始群聊高噪声且格式不稳定，必须先形成可追溯的统一事实底座 | Canonical Model、幂等导入、Source of Truth、Derived Index | `src/trivae/data/model.py` → `src/trivae/data/ingestion/importer.py` → `src/trivae/data/storage/sqlite.py` | 1 |
| 多路检索与访问边界 | 精确谓词、语义改写、时间范围和上下文恢复不是同一种检索问题 | FTS5、Vector Search、Structured Retrieval、Scope、Context Expansion | `src/trivae/retrieval/` → `src/trivae/capabilities/contracts.py` → `src/trivae/capabilities/registry.py` | 2 |
| 轻路由与受约束编排 | 将“是否先规划”和“如何调用工具”分开，避免把 Router、Planner 做成第二套执行引擎 | Rule-first Router、Soft Plan、Bounded Agent Loop、Budget | `src/trivae/query/router.py` → `src/trivae/query/planner.py` → `src/trivae/query/orchestrator.py` → `src/trivae/query/runtime/` | 3 |
| 证据约束的答案提交 | 模型输出只有绑定当前运行真实 Tool Result 并通过校验后，才能成为可复核答案 | Claim-level Citation、Provenance、Finalization、Atomic Commit | `src/trivae/query/evidence.py` → `src/trivae/query/completion.py` → `src/trivae/conversation/` | 4 |
| 可观测性与评测闭环 | 把失败从“答案不好”拆成 provider、召回、排序、上下文、覆盖度和答案契约问题 | Append-only Trace、GT、Ablation、Failure Artifact、Regression | `src/trivae/observability/` → `src/trivae/evaluation/checks.py` → `src/trivae/evaluation/benchmark/` | 5 |
| 流式产品边界 | 后端事件、停止请求和前端过程块共享稳定契约，产品层不重新实现查询逻辑 | NDJSON、Cancellation、Projection、Thin Adapter | `src/trivae/query/streaming.py` → `src/trivae/interfaces/web/streaming.py` → `web/src/stores/chat.ts` | 6 |

## 3. 必备知识点

- [ ] 能画出 Data Plane 与 Query Plane，并说明两者为什么通过 Tool Layer 隔离。
- [ ] 能区分 Canonical Store、FTS5 索引和 sqlite-vec 语义索引的事实与派生关系。
- [ ] 能解释关键词、语义、结构化、时间浏览和上下文扩展各自适用的问题。
- [ ] 能说明 Data Access Scope 为什么是授权边界，而 Query Filter 只是本次查询条件。
- [ ] 能解释 Router 只判断执行复杂度，Planner 只给软指导，Agent Runtime 才负责工具循环。
- [ ] 能说清 Tool Round、预算、超时、取消和最终合成的边界。
- [ ] 能解释 Citation 为什么必须来自当前 Run 的 Tool Result，并通过范围和来源校验。
- [ ] 能区分 no-result、partial coverage、truncated 和 provider failure。
- [ ] 能说明 Trace 如何用顺序号和因果字段串起一次完整 Query。
- [ ] 能解释 GT、Development、Calibration、Holdout、Variant 与 paired comparison 的边界。
- [ ] 能复盘 failure attribution 与跨 event loop provider lifecycle 两个真实根因。
- [ ] 能明确当前局限：语义检索没有被证明全面优于关键词检索，context uplift 不稳定，Holdout 尚未执行。

## 4. 推荐阅读（结合仓库）

| 主题 | 通用技术点 | 建议阅读位置 | 预计时间 | 读完能回答什么 |
| --- | --- | --- | --- | --- |
| 项目全貌 | 目标、边界、已完成与待验证项 | `.trellis/spec/project/overview.md`、`.trellis/spec/project/architecture.md` | 45 分钟 | Trivae 解决什么问题，为什么拆成两个平面？ |
| 工程原则 | 根因优先、错误透明、证据驱动 | `.trellis/spec/project/engineering-principles.md`、`.trellis/spec/project/interview-defense.md` | 30 分钟 | 为什么不随意加 fallback、调参或包装指标？ |
| 统一数据模型 | 身份、来源、批次、消息不变量 | `src/trivae/data/model.py`、`src/trivae/data/ingestion/importer.py` | 45 分钟 | 原始 QQ 数据如何进入统一模型，如何保证可重放？ |
| SQLite 数据层 | 事务、幂等、持久化边界 | `src/trivae/data/storage/sqlite.py`、`src/trivae/data/storage/sqlite_read.py` | 60 分钟 | 哪些数据是事实源，导入失败如何暴露和回滚？ |
| 关键词与结构化检索 | FTS5、只读 SQL、查询范围 | `src/trivae/retrieval/lexical.py`、`src/trivae/retrieval/sql.py`、`src/trivae/retrieval/structured.py` | 60 分钟 | 精确关键词、聚合统计和人物查询为何走不同能力？ |
| 语义检索 | 索引身份、分块、向量、上下文恢复 | `src/trivae/retrieval/semantic/contracts.py`、`src/trivae/retrieval/semantic/chunking.py`、`src/trivae/retrieval/semantic/builder.py`、`src/trivae/retrieval/semantic/retrieval.py` | 90 分钟 | 为什么语义索引是派生数据，stale/partial 如何显式暴露？ |
| Tool 能力层 | 契约、注册、授权范围、结果信封 | `src/trivae/capabilities/contracts.py`、`src/trivae/capabilities/registry.py`、`src/trivae/capabilities/tools.py` | 60 分钟 | Agent 能调用什么，工具错误如何结构化返回？ |
| Query 编排 | Route、Plan、Runtime、预算 | `src/trivae/query/router.py`、`src/trivae/query/planner.py`、`src/trivae/query/orchestrator.py`、`src/trivae/query/runtime/budget.py` | 90 分钟 | 标准执行和计划执行如何汇入同一个 Runtime？ |
| 证据型答案 | 来源句柄、引用绑定、校验与提交 | `src/trivae/query/evidence.py`、`src/trivae/query/completion.py` | 120 分钟 | 如何阻止模型引用未检索到、越权或失效的消息？ |
| 会话持久化 | 对话事实源、序列化、原子写入 | `src/trivae/conversation/contracts.py`、`src/trivae/conversation/serialization.py`、`src/trivae/conversation/sqlite.py` | 60 分钟 | 用户消息、助手结果和 AnswerArtifact 如何保持一致？ |
| Trace | 标准事件、采集、持久化、投影 | `src/trivae/observability/contracts.py`、`src/trivae/observability/collector.py`、`src/trivae/observability/sqlite.py`、`src/trivae/observability/projection.py` | 75 分钟 | 一次失败怎样定位到 Router、Tool、Retrieval 或 Finalizer？ |
| Evaluation | Case、Variant、Runner、指标与 Failure | `src/trivae/evaluation/contracts.py`、`src/trivae/evaluation/checks.py`、`src/trivae/evaluation/benchmark/` | 120 分钟 | 怎样建立可复现评测，怎样避免把外部 provider 故障误判为算法问题？ |
| 产品交互 | HTTP 流、取消、前端投影 | `src/trivae/interfaces/web/streaming.py`、`web/src/stores/chat.ts`、`web/src/components/chat/` | 75 分钟 | 后端过程事件如何稳定地映射成 UI？ |
| 真实评测证据 | 分母、指标限制、可写数字 | `evaluation/reports/resume-benchmark-v1-fact-index.md` | 45 分钟 | 哪些结果能写，哪些结果不能泛化？ |

## 5. 自学提醒

若某文件或原理看不懂，请继续追问 AI；本技能负责给学习路径与题目，不提供逐行讲解。

建议每读完一个主题，用三句话复述：它解决的失败现象是什么、核心机制怎样工作、哪些边界仍未验证。无法回答时不要继续堆文件，先回到对应契约与测试。

## 6. 项目技术定位

**交叉方向：AI 应用工程 + 后端/检索系统 + 评测基础设施。** 依据是项目同时包含统一数据底座、关键词/语义/结构化检索、Agent 工具执行、证据引用、全链路 Trace、离线评测，以及 CLI/TUI/Web 薄适配层；前端是产品入口，但不是核心技术重心。

## 7. 核心原理解析

### 7.1 统一事实源与派生索引

- **问题：** QQ 导出是来源特定的高噪声格式，若查询层直接依赖原字段，后续增加来源、重建索引或修正解析都会影响主链路。
- **机制：** 导入层把来源、会话、成员、消息和批次标准化到 Canonical Model；SQLite Canonical Store 保存事实，FTS5 与 sqlite-vec 只保存可重建的派生索引。
- **项目落点：** `src/trivae/data/model.py` 定义领域对象，`src/trivae/data/ingestion/importer.py` 统一导入，`src/trivae/data/storage/sqlite.py` 管理事务与 provenance，语义索引用独立数据库和身份信息检测 missing、stale、partial。

### 7.2 由问题类型决定检索策略

- **问题：** 精确关键词、同义改写、时间浏览、人物解析和聚合统计的最优查询方式不同，强行合成一个万能搜索接口会掩盖策略与失败原因。
- **机制：** 关键词、语义、结构化 SQL、最近消息和上下文扩展被拆成稳定能力；Agent 根据问题选择工具，返回结果保留 strategy、coverage、truncated 和 provenance。
- **项目落点：** `src/trivae/capabilities/registry.py` 注册固定能力，`src/trivae/retrieval/` 实现不同检索原语，`src/trivae/capabilities/scope.py` 将授权范围交到每个能力执行。

### 7.3 Router、Planner 与 Runtime 的职责分离

- **问题：** 如果 Router 同时选择工具、Planner 执行步骤、Runtime 再做一遍决策，就会形成多套状态与不可解释的分支。
- **机制：** Router 只判断执行复杂度；复杂查询先产生一次经过校验的软计划；两条路径最终都进入同一个受预算约束的 Agent Runtime，由 Runtime 执行工具循环和最终合成。
- **项目落点：** `src/trivae/query/router.py` 提供 rule-first 分类，`planner.py` 生成和清洗指导，`orchestrator.py` 统一生命周期，`runtime/budget.py` 与 `openai_adapter.py` 管理轮次、超时和 provider 交互。

### 7.4 当前运行证据约束答案

- **问题：** 模型可能生成看似合理但未检索到的引用，或把历史、越权、过期来源当成当前答案证据。
- **机制：** 工具结果先投影成有界、带来源句柄的记录；最终答案以结构化 Artifact 表达 claim、evidence 和 citation binding；提交前验证来源确实来自当前 Run、属于 Scope，并可水合为用户可查看的消息快照。
- **项目落点：** `src/trivae/query/evidence.py` 负责解析、编译、水合与校验，`completion.py` 负责终态收敛，会话层只持久化通过契约的结果。

### 7.5 事件化 Trace 支持故障归因

- **问题：** “答案错了”无法告诉工程师问题发生在 provider、路由、检索、排序、上下文、覆盖度还是最终答案契约。
- **机制：** 每次 Query 产生带版本、顺序号和因果关系的 append-only 事件；Trace 投影汇总时延、工具轮次和失败 ownership，Evaluation 再用 GT 将观测映射到稳定失败类别。
- **项目落点：** `src/trivae/observability/contracts.py` 定义事件契约，`collector.py` 采集，`sqlite.py` 持久化，`src/trivae/evaluation/benchmark/failures.py` 按 acceptance condition 顺序分类。

### 7.6 冻结环境上的可复现评测

- **问题：** 数据、索引、代码、模型或工具面任一变化都可能让对照结果失真；把 provider 故障放入质量分母也会误导结论。
- **机制：** Snapshot、Environment Gate、Controlled Variant 与 Case Bundle 固定输入；单变量对照解释组件差异；质量指标、运行完成率、不可用原因和 Failure Artifact 分开报告。
- **项目落点：** `src/trivae/evaluation/benchmark/environment.py` 做预检，`variant.py` 固定配置，`orchestrator.py` 走真实应用入口，`metrics.py`、`report.py` 与 `failures.py` 产出可审计结果。

## 8. 关键设计决策

| 决策 | 备选 | 取舍 | 风险 | 验证 |
| --- | --- | --- | --- | --- |
| Canonical Store 是事实源，搜索索引是派生数据 | 直接查询原始导出；把向量库当事实源 | 增加标准化成本，换来来源解耦、可重建和稳定 provenance | 模型演进与迁移成本 | 重放导入、索引重建、identity/stale/integrity 测试 |
| 保留独立关键词与语义工具 | 在一个 hybrid 工具内自动融合 | 策略更透明、便于消融；Agent 选择成本更高 | 工具选择可能不稳定 | tool-selection diagnostics、module retrieval、paired evaluation |
| Scope 下沉到所有 Capability | 仅在入口过滤；依赖模型遵守提示 | 多一层契约传递，换来硬授权边界 | 漏传 Scope 会形成越权风险 | 每个工具的 scope 单元测试与端到端测试 |
| Router 只判复杂度，Planner 只给软指导 | Router 直接选工具；Planner 变成工作流执行器 | 状态更少、两条路径共享 Runtime | 软计划可能被忽略或质量不稳定 | forced route Variant、Trace 中的 route/plan/runtime 事件 |
| Citation 在提交前强校验 | 直接展示模型生成的文本与引用 | 增加 finalization 复杂度，换来可追溯与失败透明 | 严格契约可能降低 valid answer 率 | invalid/unresolved citation regression、AnswerArtifact checks |
| no-result 必须有完整空结果证据 | 没搜到一次就直接回答“没有” | 降低假阴性表达，但需要覆盖度事实 | 时间范围或结果截断会造成证据不足 | zero-result Case、coverage/truncation 轴、false-zero guard |
| Trace 为 versioned append-only 事件 | 只写文本日志；每层独立日志 | 查询链可重放和归因，但事件契约需治理 | payload 膨胀与隐私边界 | capture policy、projection test、raw/Evaluation/Trace 对齐 |
| Benchmark 运行共享一个 event loop | 每个 Variant 单独 `asyncio.run` | 生命周期一致，避免 async client 跨 loop | CLI 异步入口更复杂 | lifecycle regression 与 185-run 完整性审计 |
| 不因一轮数据直接加 reranker/fusion/retry | 立即调参、自动重试或降级 | 保持根因清晰，避免把外部故障或小样本包装成收益 | 短期指标不够好看 | Failure Case、重复实验、Holdout 评测后再决定 |

## 9. 量化与验证（含待测，建议）

### 已有、可复核的工程事实

- Canonical Snapshot：473,236 条消息、14 个来源；FTS5 为 473,236 rows；语义索引为 54,267 个向量，具体口径见事实索引与环境记录。
- GT：47 条已人工裁决，其中 Development 37、Calibration 10；Holdout 不存在。
- Development 基线：37 个 Case × 5 个 Variant × 1 次重复，共 185 次真实 production-path provider 运行。
- 冻结门禁：environment gate 4/4、freeze verification 12/12 通过。
- 工程验证记录：pytest 576 passed，ruff、mypy 与 diff check 通过；这是当时任务记录，不替代当前重新运行。
- 关键词检索在 10 个 exhaustive/corpus predicate query 上 Recall@10 为 33/33；该结论只适用于该 scope，不得泛化为全系统召回率。

### 建议补测

| 目标 | 当前状态 | 建议测法 | 通过标准如何定 |
| --- | --- | --- | --- |
| 个人贡献范围 | 待补 | 以 PR、commit、任务文档逐项标出设计、实现、评测和协作边界 | 每个简历 bullet 都能对应至少一项本人证据 |
| Holdout 泛化 | 待测 | Gate 3 后按既定隔离流程生成并人工审核 Holdout，再在冻结版本上运行 | 先定义指标与不退化边界，再开封结果 |
| 语义检索真实增益 | 待测 | 扩大 human-verified paraphrase Case，分别报告 lexical、semantic 与组合策略 | 不用单轮小样本；按类别与置信区间解释 |
| 上下文恢复收益 | 待测 | 增加 required-context Case，分别测自动扩展和显式上下文工具 | 同时看 evidence recall、context recovery 与成本 |
| 延迟与资源成本 | 待测 | 固定 Snapshot/provider，对各阶段和工具做 P50/P95、tokens、调用次数剖析 | 目标来自产品 SLO，不把本地一次运行当生产 SLA |
| 索引重建可靠性 | 待测 | 故障注入 interrupted/failed/stale，验证可重建与状态可见性 | 事实源不受损，状态不静默伪装为 completed |
| 线上用户价值 | 待补 | 定义真实任务成功率、证据展开率、反馈与人工复核成本 | 指标须来自实际用户或明确实验，不编造 |

## 10. 一条可执行的学习计划

1. 第一天画出高层数据流，并用一个消息从导入追到 Canonical Store。
2. 第二天分别跑通关键词、语义、结构化和上下文工具，记录各自输入、Scope 与结果状态。
3. 第三天追一次标准查询和一次计划查询，画出 Router、Planner、Runtime、Tool Round 的时序。
4. 第四天手工构造一个合法引用、一个越权引用和一个不存在引用，理解 Finalizer 为什么接受或拒绝。
5. 第五天读取一条 Trace 和一条 Evaluation Case，把同一失败归因到具体阶段。
6. 第六天复盘两个 benchmark 根因，解释为什么修测量层不能冒充提升系统质量。
7. 第七天只看 `面经-Trivae.md` 的题目作答，再回源码补证据薄弱点。
