# Design: resume-benchmark-v1 Measurement Substrate + Benchmark

前置阅读：`research/evaluation-audit.md`（现状审计 + 两项确认的代码证据）。

## 0. 设计原则

1. 复用现有 Evaluation 架构；本设计不新增平行框架，所有新模块消费现有 contract 的产出物。
2. Measurement Substrate 先行：没有可靠的逐层 ID 追溯，Case 数量再多也跑不出可信数字。
3. 两档指标：Deterministic（Tier 1）与 LLM-assisted provisional（Tier 2，可升级 adjudicated）。
4. 不制造 Baseline：ablation 只做干净单变量；绝对正确率 + 归档 Trace before/after 承载其余叙事。
5. Holdout 纪律是流程契约，不是数据结构：冻结后不可逆。

## 1. 架构总览

```
现有（复用，不改语义）
  DatasetSnapshot / EvaluationCaseBundle / EvaluationSuite / ControlledVariant
  EvaluationRunner / checks / store / review / PairedComparison / FailureDiagnosis
  RetrievalQuerySet → 盲标 packet → annotation → retrieval metrics（module-level 通道）

新增（evaluation 层）
  benchmark/gt.py          GT criterion 约定解析器（ReferenceFinding → 结构化 GT 视图）
  benchmark/snapshot.py    resume-benchmark-v1 materializer（manifest 追加 semantic_index，
                           redact 私有 source metadata → 提交版 / 本地完整版）
  benchmark/retrieval.py   module-level benchmark runner（复用 tool facade 调用模式，
                           产出 direct/expanded 分层 ranked IDs；GT 直接评分）
  benchmark/metrics.py     Tier 1 deterministic 指标引擎（输入：Case GT + Run projection
                           + Artifact 投影；输出：per-case/per-variant/per-category metrics）
  benchmark/judge.py       Tier 2 entailment judge（复用 JudgeAdapter + ReviewPacket，
                           LLM-assisted provisional；含人工抽查升级路径）
  benchmark/report.py      JSON + Markdown comparison report（metric × variant × category，
                           full/holdout 分列）
  benchmark/failures.py    failure artifact 生成（expected/actual/IDs/trace/category）
  benchmark/orchestrator.py benchmark 编排：pre-run gate（snapshot+index identity）→
                           按 variant × case 执行 → 落盘 → 报告

生产契约最小扩展（唯一一处，已确认必要性）
  ExecutionOverride.context_window_limit: int | None = None（evaluation-only 钳制通道）
```

## 2. Benchmark Snapshot（resume-benchmark-v1）

- 以 `DatasetSnapshot.from_database(data/trivae.sqlite3)` 为基底（其 snapshot_id 已含 message count / 时间范围 / sources 数 / lexical 状态，当前 DB 与 provisional query set 的 snapshot_id 一致）。
- Benchmark materializer 在其 manifest 上 `dataclasses.replace()` 追加：
  - `semantic_index`: `SemanticIndexIdentity` 全量（database_identity、embedding model/dim/pooling/normalized/query_instruction、chunker version/config）——来自 `semantic status` 的 derived meta，即生产检索 per-query 校验的同一 identity
  - `session_count`
  - `benchmark`: `{"name": "resume-benchmark-v1", "git_commit": <HEAD>, "created_at": ...}`
- 隐私双版本：
  - 本地完整版（含 sources file_name/external_chat_id）→ `data/evaluation/benchmark/snapshot-resume-benchmark-v1.json`（gitignored，是 Runner 绑定的权威文件）
  - 提交版（source identity redact 为 `source-01..N` 匿名占位 + 保留 counts/时间范围/fingerprint 结构）→ `evaluation/snapshots/resume-benchmark-v1.json`，供仓库内复现说明；提交版不用于 Runner 绑定
- 所有 benchmark case 的 `dataset_snapshot.snapshot_id` 必须等于该 snapshot_id；Runner 现有漂移拒绝是唯一绑定机制。
- Pre-run gate：编排器启动时验证 (a) live DB snapshot_id == pinned；(b) live semantic identity == manifest.semantic_index；(c) lexical FTS count == canonical count。任一不满足 → 整个 benchmark 显式失败，不跑任何 variant。

## 3. Ground Truth Schema（复用 ReferenceFinding，零 schema bump）

GT 全部表达为 Case 的 `reference_findings`，通过 `finding_id`/`criterion` 前缀约定解析（`benchmark/gt.py` 是唯一解析点）：

| GT 语义 | ReferenceFinding 表达 |
|---|---|
| 相关消息（direct） | `criterion="gt.relevant"`，每条消息一个 `ReferenceEvidence(relation="supports", source_type="message", locator={"internal_message_id": ...})`；finding 的 `annotation_completeness` 声明枚举完备度 |
| 必需上下文（expansion 应恢复） | `criterion="gt.required_context"`，`relation="context"` |
| 期望 coverage | `criterion="gt.expected_coverage"`，`expected_semantics` 固定词表 `complete|partial|truncated|no_result` |
| 期望 zero-result | `criterion="gt.expected_zero_result"`，`expected_semantics` = `true|false` |
| 期望事实（Complete Answer Rate 用） | `criterion="gt.expected_fact"`，`expected_semantics` = 事实短语（如 repo 名），`reference_evidence` 绑其出处消息 |

- 每个 finding 的 `provenance.adjudicated=true` 仅在人工逐条审核后置位；`source`/`method` 记录构造流程（如 `llm-assisted-candidate + human-review`）。
- `expected_zero_result=true` 的 case 不得有 `gt.relevant` finding；`expected_coverage` 与 zero-result 约束在 `gt.py` 做一致性校验。
- Category 与 dev/holdout 通过 `suite_tags` 表达：`category:<name>`、`benchmark:development` / `benchmark:holdout`。Case 本体中立，归属由 Suite 引用 + tag 双重固定。

## 4. Measurement Substrate

### 4.1 Run projection 扩展（`checks.py`，evaluation 层）

`query_result_snapshot` 新增 `retrieval_calls`（不改变现有字段）：

```json
{
  "retrieval_calls": [
    {
      "tool_call_id": "...",
      "tool_name": "lexical_search",
      "strategy": "lexical",
      "status": "ok",
      "total_hits": 31,
      "direct_hits": [{"rank": 1, "internal_message_id": "..."}],   // is_hit=true，按工具返回顺序
      "direct_hit_count": 31,
      "expanded_ids": ["..."],                                       // is_hit=false
      "expanded_count": 12,
      "coverage_status": "complete",
      "recorded_depth": 50
    }
  ]
}
```

- 边界：每 call `direct_hits` 记录前 50、`expanded_ids` 前 50（数组 ≤ `MAX_EVALUATION_ITEMS=200` 合规）；`recorded_depth` 显式声明截断深度；超出部分以 count 表达。
- 数据链（可追溯）：
  ```
  Query → retrieval_calls.direct_hits(+rank) / expanded_ids
        → AnswerArtifact.evidence_items.sources → evidence message IDs
        → citation_bindings（content_block_id ↔ evidence_id）
  ```
  每层独立落盘，Retrieval Recall 只看 direct_hits，Evidence Recall / Context Recovery 看 evidence 层，互不混合。
- Evidence 层投影：`query_result_snapshot` 增加 `evidence_sources`（bounded：evidence_id → source message IDs / structured locator kinds），供指标引擎免开 conversation store 复算。

### 4.2 Tier 1 指标定义（`benchmark/metrics.py`）

统一前置：`terminal_status != completed`（provider/runtime failure、aborted）的 run 不进入任何质量指标分母，单列为 `provider_failures`。

| 指标 | 定义 | 输入 |
|---|---|---|
| Recall@K / Hit@K / MRR | 命中 `gt.relevant` 消息的比例 / 是否命中任一 / 1/first-hit-rank。scope 由 GT completeness 决定：exhaustive→corpus，partial→pool（分母=已枚举 GT），unknown→unavailable | retrieval_calls.direct_hits（module-level 通道为完整 ranking，无 recorded_depth 截断） |
| Evidence Recall | `|evidence_message_ids ∩ (gt.relevant ∪ gt.required_context)| / |gt.relevant ∪ gt.required_context|` | evidence_sources + GT |
| Context Recovery Success Rate | case 级布尔：`gt.required_context ⊆ evidence_message_ids`；无 required_context 的 case not_applicable | 同上 |
| Coverage Status Accuracy | `artifact.retrieval_coverage.status`（+ no_result artifact 映射为 `no_result`）与 `gt.expected_coverage` 的一致率；expected=complete 但 answer 为 no_result → 不一致 | artifact 投影 + GT |
| Complete Answer Rate | 仅 expected=complete 的 case：coverage 一致 ∧ terminal completed ∧ 非 no_result ∧ 每个 `gt.expected_fact` 出现在 answer_text 或 evidence 源内容（规范化子串匹配，大小写/空白归一） | artifact + GT |
| False Zero-Result Rate | GT 存在相关消息（expected_zero_result=false）∧ terminal completed 的 case 中，最终 artifact 为 no_result 形态（单 answer block + 无 evidence/citation，由 Host contract 决定）的比例 | artifact 投影 + GT |
| Verified Zero-Result Accuracy | expected_zero_result=true 的 case 中，terminal completed ∧ artifact 为 no_result 形态的比例（production finalizer 的 positive-proof gate 保证此时 zero-result 已被验证） | 同上 |
| latency / tool calls / tokens | P50/P95 latency_ms、tool_call_count、usage tokens；诊断轴，不进质量分母 | operational_measurements |

聚合：per-case → per-category → per-variant → per-split（development / holdout / full）。每级输出 `n`（分母）、命中数、比率、unavailable 原因清单。LLM 相关随机性：本 v1 全量 1 rep；`repetitions>1` 时输出 mean/方差（Runner 已支持，报告层聚合）。

### 4.3 module-level 检索通道（`benchmark/retrieval.py`）

Type A/B（exact_lexical / semantic_paraphrase）的 Recall/MRR/Hit 走确定性 module-level 执行，不调 LLM：
- 复用 `retrieval_evaluation.RetrievalAnnotationWorkflow` 的同一调用模式（Application tool facade + query-set-controlled context 参数），产出完整 ranking（无 recorded_depth 截断）+ `RetrievalRunRecord`。
- Variant 映射：strategy=lexical 跑 lexical tool；strategy=semantic 跑 semantic tool；两者分列统计 + 汇总对比，直接回答「各自贡献多少召回收益」。
- Context ablation 在 module 层 = context_before/after 由 benchmark query set 显式控制（0 vs 生产默认），`expanded_message_ids` 独立记录 → Context Recovery 的 retrieval 侧版本。
- GT 评分直接基于 `gt.relevant` 消息 ID，不走盲标标签（盲标通道保留给未来无 GT 场景，不复用混淆）。

### 4.4 ExecutionOverride 扩展（唯一生产契约变更）

```python
@dataclass(frozen=True)
class ExecutionOverride:
    forced_route: ForcedRoute | None = None
    context_window_limit: int | None = None   # 新增；None=生产默认
```

- 校验：非 None 时必须 `>= 0`；`to_dict()`/`from_dict()` 同步扩展（旧 JSON 缺字段 → None，向后兼容）。
- 贯通：`QueryRequest.to_runtime_request()` → `AgentRunRequest.context_window_limit`（新可选字段）→ `RuntimeContext.context_window_limit` → runtime 构造 `lexical_search` / `semantic_search` / `search_messages` 输入时钳制 `context_before`/`context_after`（`get_recent_messages` 无 context 参数不受影响；`get_message_context` 不钳制——显式 deepening tool，Variant A/B 本就不暴露）。
- Trace 可验证：`query.received` 已记录 `execution_override.to_dict()`（新字段自动进入）；tool 完成事件 payload 追加 `context_window_applied`（生效钳制值），`checks.py` 的 `tool_result_facts` 复制字段清单同步加入 → deterministic check `context_expansion_override`：variant 声明 limit=0 时，所有 retrieval call 的 applied 必须 =0。
- Variant 映射：Variant JSON 的 `execution_override.context_window_limit` 是生效通道；`context_expansion_configuration` 保留为描述性元数据并注明生效通道。
- 变更范围：`query/contracts.py`、`query/runtime/contracts.py`、`query/runtime/openai_tools.py`（3 个工具的输入构造点）、`evaluation/checks.py`；默认 None 时行为逐字节不变（现有测试兜底）。

## 5. Variants（Ablation Matrix）

| Variant | available_tools | context_window_limit | 目的 |
|---|---|---|---|
| A `bench-lexical-only-v1`（role=minimal_control） | lexical_search | 0 | 单变量基线 |
| B `bench-lexical-semantic-v1` | lexical_search, semantic_search | 0 | semantic 收益（B−A） |
| C `bench-context-expansion-v1` | lexical, semantic, get_message_context | None（生产默认） | expansion 收益（C−B） |
| D `bench-full-system-v1`（role=candidate） | 七工具 | None | 当前完整系统 |

共同固定：同一 snapshot_id、同一 provider/model（deepseek-v4-flash via opencode-go）、temperature/prompt 为生产默认并记入 fingerprint、case 的 scope、工具 budget 为生产默认。`variant_diff` 自动记录 A/B/C/D 两两差异。`index_identity` pin 真实 semantic serialized identity + lexical identity。

## 6. Tier 2 Judge（`benchmark/judge.py`，第二批实现）

- 输入：复用 `build_review_packet`（answer_text + selected_sources 含 message excerpt snapshot + relation）。
- Grounded Claim Rate：claim 单位 = content block；deterministic 部分 =「有 citation binding 的 block 视为 factual claim」（无 binding 的 block 由 judge 判定是否为需要证据的事实陈述）；entailment 判定由 LLM judge 给 `llm_assisted_provisional`。
- Citation Correctness：分母 = 所有 citation binding（block→evidence_ids）；judge 逐条判定 evidence 是否支持该 block 陈述（supports/contradicts/insufficient）。
- 输出 artifact 带 `verification_status`；人工抽查（audit queue 沿用 `build_retrieval_audit_queue` 模式）后整组升级 `adjudicated`。报告分区展示 provisional 与 adjudicated。

## 7. Comparison Report（`benchmark/report.py`）

- JSON（机器可读，全量指标+分母+unavailable reasons）+ Markdown（人可读矩阵）。
- 结构：header（benchmark/snapshot/variant fingerprints/case counts/split counts）→ overall 矩阵（metric × A/B/C/D，分 full / development / holdout 三列组）→ per-category 矩阵（exact_lexical / semantic_paraphrase / context_recovery / temporal_overview / citation_evidence / zero_result）→ failure summary。
- 无综合总分。holdout 与 full 并列但明确标注；简历引用以 holdout 优先。

## 8. Failure Artifact（`benchmark/failures.py`）

- 触发：case 级任一 Tier 1 指标未达 1.0（且该指标 available），或 terminal 异常。
- 内容：case_id / variant / expected（GT 摘要）/ actual（coverage、no_result 与否、evidence 命中）/ direct+expanded IDs / tool 序列 / citations / trace_id / failure_category。
- failure_category 判定规则（顺序）：
  provider_failure（terminal 异常）→ retrieval_miss（GT 消息未出现在任何 direct_hits）→ ranking_failure（出现在 direct_hits 但排名 > K）→ semantic_miss（lexical 命中而 semantic 未命中，仅 B/C/D）→ context_missing（direct 命中但 required_context 未进 evidence）→ coverage_error（coverage 状态不一致）→ citation_mismatch（binding 指向不支持的 evidence，Tier 2）→ answer_generation_error（其余）→ router_tool_selection_error（tool 序列与 diagnostic_expectations 明显背离，交人工确认）。
- 落盘：`data/evaluation/benchmark/failures/`（本地，含正文引用）；聚合统计进提交版报告（无正文）。

## 9. GT 构造流程（`evaluation/cases/benchmark/` + 编排脚本）

```
真实消息数据
  → candidate question 生成（LLM 辅助，来源：dogfooding 问题清单 / 归档 failure trace / 数据挖掘）
  → lexical + semantic + SQL 三路检索候选证据
  → 确定性完备性证明：exact_lexical 类对候选实体跑 FTS+LIKE 全库扫描，证明 relevant 枚举 exhaustive
  → provisional Case JSON（adjudicated=false, verification=llm_assisted_provisional）
  → 人工 review（按 case 生成 review markdown：query + 候选消息摘要 + 建议标签 + 修改槽）
  → adjudicated=true 入库 → 冻结 dev/holdout 归属
```

- Case 文件位置：`evaluation/cases/benchmark/*.json`（无正文；`why_relevant` 只写简短依据，最长 200 字符）。
- Suite：`evaluation/suites/resume-benchmark-dev-v1.json`、`resume-benchmark-holdout-v1.json`、`resume-benchmark-v1.json`（全集）。预留池（reserve）≥ holdout 数量的 30%，供降级补位。
- 私有候选正文/中间产物进 `data/evaluation/benchmark/`（gitignored）。

## 10. 兼容性与回滚

- `ExecutionOverride` 新字段默认 None：所有现有 JSON/测试/调用方零改动即可通过（旧 variant JSON from_dict 缺字段 → None）。
- `query_result_snapshot` 新增字段为 additive；EvaluationRun.from_dict 旧记录无此字段 → 读侧可选。
- benchmark 模块全部为 evaluation 层新增文件 + 编排脚本，不进入生产 query 链路；回滚 = 删除模块与 orchestrator 入口。
- 指标引擎对 unavailable 的处理沿用 `RetrievalMetric` 语义：显式 unavailable + reason，绝不伪零。

## 11. 文件布局（新增/修改）

```
src/trivae/evaluation/benchmark/__init__.py
src/trivae/evaluation/benchmark/gt.py            新增
src/trivae/evaluation/benchmark/snapshot.py      新增
src/trivae/evaluation/benchmark/retrieval.py     新增
src/trivae/evaluation/benchmark/metrics.py       新增
src/trivae/evaluation/benchmark/judge.py         新增（第二批）
src/trivae/evaluation/benchmark/report.py        新增
src/trivae/evaluation/benchmark/failures.py      新增
src/trivae/evaluation/benchmark/orchestrator.py  新增
src/trivae/evaluation/checks.py                  修改（retrieval_calls / evidence_sources / context_window_applied / 新 deterministic check）
src/trivae/query/contracts.py                    修改（ExecutionOverride.context_window_limit）
src/trivae/query/runtime/contracts.py            修改（AgentRunRequest.context_window_limit）
src/trivae/query/runtime/openai_tools.py         修改（3 工具钳制点 + applied 事实）
src/trivae/interfaces/cli.py                     修改（eval benchmark 编排子命令）
evaluation/snapshots/resume-benchmark-v1.json    新增（redacted 提交版）
evaluation/variants/bench-*.json × 4             新增
evaluation/cases/benchmark/*.json                新增（人工审核后）
evaluation/suites/resume-benchmark-*.json × 3    新增
tests/test_benchmark_*.py                        新增
```
