# Stage 1.3: Retrieval Architecture Decisions

> 状态：**Confirmed（Stage 1.3）**
> 记录 Stage 1.3 真正形成的 Retrieval 架构决策及 rationale。仅覆盖 Retrieval 内部能力与组合策略；Agent 可见的 Tool 暴露方式（Stage 1.4）、Evidence Judge（Stage 1.8）、Trace Schema、Vector Store / Chunk 参数 / Embedding 模型等技术选型不在此文档内决定。
> 参考 ChatLab 但不机械复制：所有参考仅作为 initial hypothesis / reference design，以 Trivae 的数据特点（高噪声技术群、短消息多、话题高速切换、多人插话严重）与业务目标为准。

---

## 1. Multi-strategy Retrieval：Retrieval Composition + 四个 Primitives

**Context**：Trivae 需要从大量高噪声群聊数据中找到"足够相关、足够完整、能够继续追溯"的候选信息。ChatLab 并非一个万能 `search()`，而是同时保留 Keyword Search、Semantic Search、只读 SQL 与 Evidence Retrieval 多条数据获取能力。

**Problem**：如果只提供单一检索能力，不同性质的问题（找明确关键词 vs 语义相关 vs 统计聚合）会被强制套进同一种搜索方式，命中率与可解释性都无法保证。

**Candidate Solutions**：
1. 单一万能 `search()` 入口，内部自动切换。
2. 一组可组合的 Retrieval Primitives + 一层 Composition。

**Decision**：Retrieval 由一层 **Retrieval Composition** 与四个 **Retrieval Primitives**（Structured / Lexical / Semantic / Context Expansion）组成。Composition 根据当前任务选择并组合底层原语，输出结构化 Candidate Set。

**Reason**：不同问题对应不同的最佳信息获取方式（明确关键词 → Lexical，同义表述 → Semantic，统计聚合 → Structured，命中上下文不足 → Context Expansion）。把能力拆成可组合的原语，让"选哪种方式"成为一个显式的组合决策，而不是被藏在一个黑盒里。

**Result**：`Retrieval Request → Composition → 原语召回 → Candidate Set → Context Expansion → Retrieval Result`。

**Trade-off**：多一层 Composition 需要定义组合语义与结果结构；换取每种问题都能走最合适的召回路径，且错误可归属到具体原语。

**Failure Case**：GroupMemory 曾因系统提前规定完整检索流程，Agent 失去根据任务选择信息获取方式的能力（见决策 8）。

## 2. Hybrid 是组合策略，不是底层搜索引擎

**Context**：RAG 社区常见的做法是 `query → BM25 + Vector → RRF → Reranker → LLM` 固定流水线，或演化出一个把所有问题都塞进去的 `hybrid_search()`。

**Problem**：把 Hybrid 当作一个底层搜索引擎，会形成越来越复杂的单一函数，难以定位召回来源、难以针对具体策略调优。

**Decision**：**Hybrid 属于 Retrieval Composition 层的组合策略，不单独成为一种底层搜索引擎。**

```text
Lexical Candidates + Semantic Candidates → Merge → Dedup → Candidate Selection
```

**Reason**：Hybrid 的本质是"多路候选的合并、去重与选择"，不是"一种更高级的向量搜索"。作为组合策略，它天然位于 Composition 层，与各原语解耦。

**Result**：不会出现通用 `hybrid_search()`；组合规则、合并/去重/选择算法与 Fusion 权重均作为 Composition 层的 Pending Evaluation 项。

**Trade-off**：Hybrid 何时启用、如何组合成为显式决策（交给 Query-specific strategy），需要 Evaluation 验证，不默认生效。

## 3. 确定性查询优先（Structured Retrieval）

**Context**：ChatLab 把统计、聚合、结构化筛选独立出来（member activity、time stats、conversation between、keyword frequency、只读 SQL）。

**Problem**：`过去半年一共有多少条 AI Agent 相关讨论？` 这类问题如果强行 Embedding → vector search → LLM 看几十条消息猜统计结论，可靠性差、成本高、无法追溯计算过程。

**Decision**：**能够由确定性查询计算的事实，优先使用 Structured Retrieval**，直接对 Canonical Store 执行 filter / aggregate / 确定性查询（具体查询接口由 Storage Architecture 决定，Pending）。

**Reason**：确定性查询可验证、可追溯、成本低；LLM 负责解释结果，不负责数数。

**Trade-off**：需要为结构化查询定义清晰的能力边界（哪些问题属于"数据库能确定计算"），避免把语义问题误判为可计算问题。

**Failure Case**：把可确定性计算的问题交给 Embedding + LLM 猜测，得到无法保证准确的结论且无法追溯。

## 4. Lexical Retrieval 保留

**Context**：大量问题是"我已经大概知道自己在找什么字面内容"（`有没有人提过 "LangGraph"？` `谁讨论过 DeepSeek V4？` `8 月 15 日有没有说过 "MCP"？`）。

**Decision**：保留 Lexical Retrieval 作为四个 Primitives 之一。目标词明确时，关键词检索精确、便宜、可解释，命中原因清楚（`match = "LangGraph"`）。

**Reason**：目标词明确的场景下关键词检索是最优路径，无需语义开销。

**Trade-off**：Lexical 单独使用有明确局限——群聊措辞随意，"Agent 框架太重"可能在聊天记录中完全不以该词出现（Keyword Recall = 0 但语义相关），因此不能作为唯一召回路径（见决策 5）。

## 5. Semantic Retrieval 保留，且索引单位为 Conversation Chunk

**Context**：用户表达的是一个意思，聊天记录可能使用完全不同措辞（`大家对重型 Agent 框架有什么意见？` ↔ `封装太厚` `调试困难` `LangGraph 太重` `自己写 loop 反而简单`）。

**Problem**：群聊大量单条消息语义残缺（`对` `确实` `哈哈哈` `这个可以` `我也是` `？`），真正的信息分布在多轮对话中。若 `Message → embedding` 逐条向量化，每条向量携带的信息不足以支撑语义召回。

**Decision**：保留 Semantic Retrieval；**Semantic 索引单位是 Conversation Chunk，不是单独 Message**。采用 **Time-aware Parent + Small Child** 架构：Parent 表示相对连续的讨论区域（时间 gap 划分），Child 是用于向量化的较小语义单元。

```text
Query → 命中 Child → 定位所属 Parent → Context Expansion
```

**Reason**：小 Chunk 保证定位准确，大 Parent 保证上下文完整；两者通过"命中 Child → 关联 Parent → 扩展上下文"衔接。

**Trade-off**：Chunk 边界会切分对话，存在 Chunk Boundary Error（关键上下文被切开）的可能，需要 Context Expansion 与 Evaluation 验证边界参数。

## 6. Time-aware Parent + Small Child 的架构确认、参数不复制

**Context**：ChatLab 的语义索引采用 Parent / Child 两层，默认策略 Parent 考虑约 30 分钟时间 gap，Child 以 120–360 有效字符、消息数、token 上限共同控制并保留少量 overlap。

**Decision**：Trivae 采用 **Time-aware Parent + Small Semantic Child + Context Expansion** 的架构；但 **不复制 ChatLab 的具体数字**（30 min / 360 chars / 12 messages / overlap 等）。Chunk 具体参数保持 **Tunable，由 Trivae 自己的 Evaluation Set 决定**。

**Reason**：ChatLab 的默认参数是其 Phase 1 策略，不构成 Trivae 的证据。Trivae 数据特点特殊（高噪声技术群、短消息多、代码/链接多、话题高速切换、多人插话），参数必须用真实数据与 Evaluation 校准。

**Result**：架构确定，参数 Pending Evaluation。不得以"ChatLab 如此"为由固定参数。

**Regression**：若现在固定参数，会重复"从参考项目抄默认值而无依据"的错误，后续难改且无法定位问题。

## 7. Context Expansion 是独立能力

**Context**：命中一条"我现在觉得 LangGraph 真有点重"，只把这条交给 LLM 信息远远不够；真正重要的是附近李四的追问、张三对状态和调试的解释、王五换 SDK 的后续。

**Decision**：**`retrieve` 与 `expand context` 是两个动作**。Context Expansion 是独立的第四个 Primitive，将命中扩展为完整的 Evidence Window（前后消息、回复链、同 Parent 范围等）。

**Reason**：命中与扩展的成功率、失败模式完全不同，必须分开观察和归因（Context Expansion Error 单独可定位）。

**Trade-off**：扩展需要定义范围边界（扩展多少、是否越界进入无关话题），由 Evaluation 校准。

**Failure Case**：只把单条命中交给 LLM → 信息不完整 → 答案缺关键论据，且无法区分是"没召回"还是"召回但上下文不完整"。

## 8. Query-specific strategy：不默认所有问题 Hybrid

**Context**：很多 RAG 项目让所有查询走同一条 `BM25 + Vector → RRF → Reranker → LLM` 固定流水线。

**Problem**：系统提前规定完整检索流程，Agent 失去根据任务选择信息获取方式的能力（GroupMemory 的旧问题）。不同问题需要的策略不同：明确关键词 → Lexical；同义表述 → Semantic；时间趋势 → 多轮 Semantic + Lexical verification + Structured 统计；计数类 → Evidence-oriented Hybrid。

**Decision**：**Retrieval Strategy 由任务决定，不默认所有 Query 执行同一个固定 Pipeline。**

| 问题示例 | 策略 |
| --- | --- |
| 有没有说过 LangGraph？ | Lexical |
| 大家为什么觉得一些 Agent 框架太重？ | Semantic |
| 过去半年 Agent 框架讨论发生了什么变化？ | 多轮 Semantic + Lexical verification + Structured 时间统计 |
| 今年到底有几次明确提到面试 OC？ | Evidence-oriented Hybrid |

**Reason**：让策略适配任务，而不是任务适配流水线；保留 Agent 选择信息获取方式的能力，避免回到"系统替 Agent 规定一切"的老路。

**Trade-off**：需要明确"谁来决定策略"（Agent 自主选择 vs 规则 / Router 引导）及其失败处理，该机制属于 Stage 1.4 / 1.10 边界，当前保持 Pending，不在此处提前实现。

## 9. Reranker 第一版不加（Pending Evaluation）

**Context**：做 Retrieval 常伴随"肯定要 Embedding + BM25 + RRF + Cross-Encoder Reranker"的冲动。但 ChatLab 当前语义检索核心仍为 `query embedding → dense candidate retrieval → time filter → Top K`，没有 Cross-Encoder Reranker。

**Problem**：目前没有证据证明 Trivae 需要 Reranker；提前引入增加复杂度且无基线对照。

**Decision**：**Reranker = Pending Evaluation**，第一版不引入。遵循 Stage 0 原则：先建立 baseline → 出现 Failure Case → 证明排序问题（Ranking Error 成为主导）→ 再评估 Reranker。

**Reason**：无依据的复杂度不可接受；排序问题应由 Evaluation 数据证明后触发。

**Trade-off**：第一版可能承担一定排序质量损失，换取简单可验证的 baseline。

## 10. 不提前设计复杂 Fusion Score；Candidate provenance 必须保留

**Context**：第一版 Hybrid 不采用 `0.45 * semantic + 0.35 * BM25 + 0.1 * recency + 0.1 * sender_authority` 这类带权打分——这些权重没有任何依据。

**Decision**：第一版 Candidate 保留来源 provenance：

```text
Candidate {
    source         # semantic | lexical | structured
    score
    message_range
    timestamp
    matched_terms
}
```

**Fusion 权重 = Pending Evaluation**，等 Evaluation 指出具体问题后再设计。

**Reason**：保留来源是归因与调优的前提；没有证据的权重只会掩盖问题（等 Evaluation 告诉我们哪里出了问题）。

**Trade-off**：第一版不做加权融合，Hybrid 结果可能不如"精心调权"的方案漂亮，但可解释、可归因。

## 11. Partial / Coverage 显式暴露 + Failure Attribution 分类

**Context**：如果 Semantic Index 尚未完整构建（ingestion 未完成、模型升级重建中），0 results 不代表不存在。

**Decision**：**不能"搜不到 = 不存在"**。Semantic Retrieval 必须显式暴露 `coverage` / `partial` / `truncated` 等完整性信息；当索引覆盖不足时，结论只能是"当前检索没有找到，但数据覆盖不足，无法确认不存在"。一次检索至少能区分以下 Failure 类型：

| Failure | 含义 |
| --- | --- |
| Lexical Miss | 关键词没有覆盖真实表达 |
| Semantic Miss | 向量没有召回相关讨论 |
| Chunk Boundary Error | 关键上下文被切开 |
| Filter Error | 时间 / 成员过滤错误 |
| Context Expansion Error | 命中了关键句，但上下文不完整 |
| Ranking Error | 召回了，但正确结果排得太后 |
| Coverage Error | Semantic Index 本身未完成 |
| Retrieval Budget Error | 候选太多被截断 |

**Reason**：Failure Attribution 是答案纠错的入口——不同 Failure 的根因与修复方式完全不同。

**Trade-off**：需要额外输出完整性字段，换取"0 结果 ≠ 不存在"的语义正确性与可归因性。

## 12. Evidence 判断不在 Retrieval 层硬编码

**Context**：ChatLab 的 `retrieve_chat_evidence` 用固定关键词（计划词 / 实际发生词）判断 `included / excluded / uncertain`。

**Problem**：Trivae 面向技术情报，不同问题的"证据成立条件"完全不同（`准备试一下` / `已经接进去了` / `昨天上线了` / `最后还是换回自己写`），固定关键词无法迁移。

**Decision**：**不复制固定关键词判断 Evidence Status 的方案**。Evidence Judge 围绕 **Question-specific Criteria** 设计，留到 Stage 1.8 Evidence / Citation 决定。

**Reason**：参考 ChatLab 但不机械复制；Trivae 的 Evidence 语义必须由自身业务目标决定。

**Regression**：若在 Retrieval 层硬编码证据判断，会与"Retrieval 输出候选、Evidence 层负责组织证据"的职责边界冲突，并在 Stage 1.8 被迫重构。

## 13. Retrieval Trace：只确定观察需求，不实现 Schema

**Context**：答案错误时，需要回答"到底是没召回，还是召回了但 Agent 没用？"——这两个 Failure Case 的根因完全不同。

**Decision**：本阶段只确定 **Retrieval 需要观察哪些信息及其目的**：

| 观察项 | 目的 |
| --- | --- |
| `query`、`strategy` | 知道本次检索任务与所选策略 |
| `filters`（session / time_range / member） | 定位 Filter Error |
| `lexical`（keywords / hit_count / latency） | 定位 Lexical Miss |
| `semantic`（rewritten_query / index_version / model / coverage / candidate_count / top_scores / latency） | 定位 Semantic Miss / Coverage Error |
| `context_expansion`（source_hits / expanded_ranges） | 定位 Context Expansion Error |
| `final_candidates`（ids / source / rank） | 核对 provenance / 定位 Ranking Error |

**不实现具体存储格式或 Trace Schema**：Trace Schema、事件模型、存储与采集方式保持 Pending（跨 Query Plane 的 Trace 整体尚未确认）。

**Reason**：先确定"观察什么、为什么观察"，把格式留给 Trace 架构阶段；避免在需求未验证前锁定存储格式。

**Trade-off**：观察需求先行、格式后定，需要实现阶段补一轮格式设计；换取不提前锁定 Schema。

## 14. Semantic Index 是 Derived Data（与 Stage 1.2 衔接）

**Context**：Stage 1.2 已确认 Canonical Store 为 Source of Truth、索引为 Derived Data 且可重建。

**Decision**：在 Retrieval 语境下重申：Semantic Index（Chunk + Embedding + Vector Index）与 Lexical Index 均属于 Derived Data，必须可基于 Canonical Store 重建。更换 Embedding 模型时只需重建派生数据，不需要重新导入原始聊天数据。

**Reason**：避免让搜索索引成为原始事实来源——换模型、重建索引不应对 Canonical Store 造成影响。

**Trade-off**：需要维护重建机制；换取模型升级成本可控（决策同 Stage 1.2 #6，此处落实到 Semantic / Lexical Index 具体范围）。

---

## Pending（本阶段不决策，随后续阶段解除）

- Reranker（Pending Evaluation，第一版不引入）
- Fusion 权重与 merge / dedup / candidate selection 具体算法（Pending Evaluation）
- Chunk 具体参数：时间 gap、有效字符数、消息数、token 上限、overlap（Pending Evaluation，不复制 ChatLab 默认值）
- Query-specific strategy 的决策机制：Agent 自主选择 vs 规则 / Router 引导（Stage 1.4 / 1.10 边界）
- Vector Store 实现、Embedding 模型、Indexing Pipeline 具体执行方式
- Semantic / Lexical Index 的具体存储、版本管理与重建执行方式
- Retrieval Trace Schema、事件模型、存储与采集方式（仅观察需求已确认）
- Tool / Capability Layer：Agent 看到哪些 Tool、如何命名与封装（Stage 1.4）
- Evidence Judge 设计（Question-specific Criteria，Stage 1.8）
- Candidate / Retrieval Result 的具体数据结构（与 Storage / Data Schema 联动）