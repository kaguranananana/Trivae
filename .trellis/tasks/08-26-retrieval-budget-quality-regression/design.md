# Technical Design

## Root Cause

`DEFAULT_RESULT_LIMIT=100` 当前同时渗透到 lexical provider 默认值、trusted scope、canonical Tool Result message 容量与 context expansion 上限。它曾通过统一提升旧的多个 20 条限制修复了 `31/20 truncated`，但现在也把 broad lexical inventory 固定在 100；若把同一个常量改为 1000，又会错误放大 semantic result、SQL/member 工具、context expansion 和 structured transport。

因此根因不是单一数值过小，而是 candidate、expansion、transport 与 model-visible token 四种不同资源共享了同一个预算概念。

## Budget Model

| Budget | Default | Hard cap | Meaning |
| --- | ---: | ---: | --- |
| Lexical candidate | 1000 | 5000 | FTS 命中候选，服务 inventory/broad recall |
| Semantic result | 10 | 20 | 最终语义 direct-hit evidence 数量 |
| Semantic ANN pool | 40 | 1000（现有内部边界） | `dense_top_k`/内部候选池，不等于最终 result |
| Automatic context source hits | 20 | 20 | 最多对多少 direct hits 读取邻居 |
| Expanded messages | 100 | 100 | semantic/显式上下文最终消息容量 |
| Structured/value transport | 100 | 100 | 非 message JSON 容量，避免被 lexical 放大 |
| Model-visible Tool Result | 16k tokens | 16k tokens | 固定 projection budget，独立于 candidate count |

`ExecutionScope.max_results` 保留现有公开字段以避免跨层破坏，但其默认值调整为 5000，仅作为 trusted umbrella ceiling。每个 Capability/provider 必须计算自己的有效上限：

- lexical：`min(scope.max_results, 5000)`；
- semantic：`min(scope.max_results, 20)`；
- SQL/member/structured：`min(scope.max_results, 100)` 或现有更严边界。

Provider schema 负责让模型看到正确 maximum；Capability 层再次验证，schema 不能替代 Host enforcement。

## Data Flow

```text
model limit
  -> provider schema tool-specific maximum
  -> typed input
  -> capability tool-specific validation + trusted scope
  -> retrieval candidate/direct hits
  -> bounded context expansion (direct hits first)
  -> canonical ToolResultRecord
  -> bounded model projection (16k)
  -> visible source handles
  -> citation validation + Trace
```

## Lexical Retrieval

`SearchMessagesInput.limit` 与 `LexicalQuery.limit` 使用 lexical 默认 1000。SQLite 查询始终携带 bounded `LIMIT`，hard cap 5000。inventory guidance 继续要求模型为明确的 all/所有/完整列表/尽可能找全请求选择足够大的 trusted limit，并使用 `context_before=0/context_after=0`。

这不是靠 Prompt 保证边界：即使模型传入更大数字，provider schema 与 Capability 都会拒绝。

## Semantic Retrieval

`SemanticSearchInput.limit`、`SemanticQuery.limit` 与 provider schema 使用默认 10、hard cap 20。`dense_top_k=40` 保持独立；当前内部候选池逻辑 `min(max(dense_top_k, limit * 4), 1000)` 继续存在，避免把最终 Top-K 误当 ANN recall pool。

本任务不改变 embedding、Parent/Child、排序或 coverage 算法，除非测试揭示与 budget 解耦直接相关的回归。

## Context Expansion

ContextExpander 先确定稳定 direct-hit 顺序，并保证所有 direct hits 优先于 context：

1. 若 direct hit 已达到最终 message limit，直接返回命中，不读取邻居。
2. 若仍有容量，只对前 20 个 direct hits 读取 before/after。
3. 去重并追加邻居，达到最终 message limit 后停止。
4. metadata 记录 expansion source count/budget 与 context count。

这同时修复 `100 hits × before2/after2` 的无收益 N+1 查询；不会牺牲 direct hits。1000-hit inventory 默认 context=0，不进入扩展路径。

## Canonical Record and Model Projection

canonical ToolResultRecord 与给 LLM 的 projection 分开：

- canonical message payload 接受最多 5000 条 bounded lexical candidate，供 Evidence/Trace 保真；
- structured/value payload 仍限制 100，避免 unrelated contract 被放大；
- projection 以 16k estimated tokens 为硬边界。

Projection 使用确定性收缩顺序：

1. 序列化并估算；预算内则不改。
2. 删除非 direct-hit context，并记录 projection truncated。
3. 按现有规则缩短 message content，同时保留标识、时间、sender、match/provenance。
4. 若仍超预算，从稳定排序尾部省略 direct hits，逐步/批量重估到预算内。
5. 同步过滤 model-visible source handles，只暴露实际可见来源。
6. 输出 `estimated_tokens`、`truncated`、`omitted_hit_messages` 等明确字段；Trace 记录最终值。
7. 最小合法记录仍超限时抛出 `ToolResultProjectionError`。

16k 是本任务有意保留的 fixed budget：它约为 32k context 的 50%、64k 的 25%、128k 的 12.5%。当前 Runtime 只有 provider/model 标识，没有可靠 context-window registry；引入 registry 会扩大范围。

## Prompt and Evaluation Contracts

通用 Prompt contract 加入事实强度约束，不写四条 query 的关键词特例：

- mention/share/self-promotion/recommendation/usage review 分开；
- intent/request-to-test 不等于 completed actual use；
- review of output 不等于 personal install/run；
- hit count 不等于 unique entity count；
- partial/truncated retrieval 或 projection 禁止强穷尽和强否定。

Evaluation 默认 axes 使用 snake_case：

- `retrieval_recall`
- `evidence_coverage`
- `citation_validity`
- `claim_evidence_entailment`
- `enumeration_completeness`
- `overclaim_unsupported_inference`
- `user_facing_readability`

Failure labels 作为显式词表/contract 提供，不编写基于关键词的自动打标器；真实 run 由人工/LLM review 依据 evidence 判定。

## Trace Contract

保留并验证现有语义等价字段：

- retrieval：`total_hits`、`returned_messages`/returned hits、`partial`、`truncated`、semantic coverage、`dense_top_k`；
- Tool Result：`tool_result_estimated_tokens`、projection truncated count、omitted direct hits；
- Provider/final：input tokens、output tokens；
- Citation：citation count、unresolved count；
- execution：tool sequence、tool calls、tool rounds、Trace ID。

## Performance Rationale

真实 archive 约 473,236 messages。已完成的只读基线显示：

- `Agent`：100/300/689 hits 的 median DB duration 约 107.7/107.5/111.0 ms；
- `https`：1000/2779/2779 hits 的 median DB duration 约 131.3/146.0/144.6 ms；
- context 2/2：100 hits 约 15.5 s，300 hits 约 45.3 s。

因此 lexical default 1000 与 hard cap 5000 对纯 FTS 是合理 bounded 取值；真正瓶颈是逐 hit context expansion，所以扩展来源需单独限为 20，而不是把 lexical limit 随意调低。

候选提升后的分层实测（同一真实 archive，warm median）如下：

| query / limit | retrieval（含 context） | evidence build + model projection | estimated tokens | projection 状态 |
| --- | ---: | ---: | ---: | --- |
| `Agent` / 100 | 100.6 ms | build 0.2 ms + projection 2.5 ms | 12,162 | complete |
| `Agent` / 300 | 102.7 ms | build 0.6 ms + projection 38.6 ms | 15,873 | truncated，省略 169 hits |
| `Agent` / 1000（689 hits，20 source hits） | 2,215.8 ms | build 1.7 ms + projection 97.4 ms | 15,854 | truncated，省略 80 context、559 hits |
| `https` / 100 | 116.1 ms | build 0.2 ms + projection 2.7 ms | 13,049 | complete |
| `https` / 300 | 118.8 ms | build 0.8 ms + projection 41.6 ms | 15,830 | truncated，省略 178 hits |
| `https` / 1000 | 131.7 ms | build 2.6 ms + projection 151.0 ms | 15,914 | truncated，省略 878 hits |

`Agent` 1000 的 retrieval 时间主要来自最多 20 个 source hit 的真实 context I/O；它不再随 689 个 direct hit 做逐条扩展。初版 projection 在 1000-hit 下因逐条尾部删除和重复 JSON 序列化达到约 2–4.6 秒；这是可复现的实现瓶颈，不是通过缩小 lexical budget 掩盖。改为按单调性二分尾部省略后，`https` 1000 projection 降至约 154 ms，且 `truncated`、省略数和可见 source handle 保持一致。

## Compatibility and Migration

- 删除统一 `DEFAULT_RESULT_LIMIT`，让调用点必须选择正确预算，避免 alias 继续隐藏耦合。
- `ExecutionScope.max_results` 字段名暂不改，减少公开 contract 迁移；通过 tool-specific cap 重新定义其 umbrella 语义。
- 不改变 short `source_id` 与 citation JSON。
- 已修复的 31/31、partial=false、truncated=false 场景必须有回归覆盖。

## Risks

- canonical 5000 messages 会增加 Trace/serialization 体积；projection 仍 bounded，benchmark 必须分别记录 evidence build、serialization 与 Trace size。
- 模型即使获得足够 evidence 仍可能 overclaim；这是 Claim Grounding Failure，不得用继续扩大 retrieval 掩盖。
- 固定 16k 对 32k 模型偏高，对 128k 偏保守；context-aware budget 延后到 Runtime 能可靠提供 context window 的独立任务。
- 四条真实 run 依赖外部模型/provider，可能有非确定性；必须保存 Trace 和逐项人工依据，不能只比较总分。
