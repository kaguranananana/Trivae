# Design: resume-benchmark-v1 Measurement Substrate + Benchmark

> Revision 2：吸收 review 修正——Coverage 三轴分离、Environment/Snapshot 分离、A/B/C/C2/D 真单变量、holdout local-only 一次定稿、Target Recall 命名、Expected Fact Answer Coverage 收窄、atomic claim 单位、acceptance-condition failure、无条件指标伴随。
> 前置阅读：`research/evaluation-audit.md`。

## 0. 设计原则

1. 复用现有 Evaluation 架构；新模块只消费现有 contract 产出物；`benchmark/retrieval.py` 是薄 adapter 而非第二套 harness。
2. Measurement Substrate 先行；Stage 1 末尾用 8~12 个 dev pilot case 做校准 gate。
3. 两档指标：Tier 1 Deterministic；Tier 2 LLM-assisted provisional（逐条人工确认才升级，无整组升级）。
4. 不制造 Baseline：单变量 ablation 只有 B−A、C−B、C2−C；其余是绝对正确率或标注为多变量的 full-system 结果。
5. 指标可用性与命名如实声明 scope（corpus / pool / target / tool-returned），宁可 unavailable 不可虚标。

## 1. 架构总览

```
现有（复用，不改语义）
  DatasetSnapshot / EvaluationCaseBundle / EvaluationSuite / ControlledVariant
  EvaluationRunner / checks / store / review / PairedComparison / FailureDiagnosis
  RetrievalQuerySet → 盲标 packet → annotation → retrieval metrics（module-level 通道）

新增（evaluation 层）
  benchmark/gt.py          GT criterion 约定解析器（ReferenceFinding → 结构化 GT 视图 + 一致性校验）
  benchmark/environment.py BenchmarkEnvironmentManifest + pre-run gate
  benchmark/retrieval.py   薄 adapter：Case GT → RetrievalQuerySet → 现有
                           RetrievalAnnotationWorkflow 执行路径 → RetrievalRunRecord → GT 评分
                           （不重写 invocation/ranking/coverage projection）
  benchmark/metrics.py     Tier 1 deterministic 指标引擎
  benchmark/judge.py       Tier 2 judge（atomic claim 切分 + entailment；第二批实现）
  benchmark/report.py      JSON + Markdown comparison report
  benchmark/failures.py    acceptance-condition failure artifact
  benchmark/orchestrator.py 编排：pre-run gate → variant × case → 落盘 → 报告

生产契约最小扩展（唯一一处，必要性已确认）
  ExecutionOverride.context_window_limit: int | None = None
```

## 2. Snapshot 与 Environment 分离

- **`DatasetSnapshot` 保持原样**：`from_database` 产物不做任何 replace/追加。它只回答「canonical 数据是什么」。benchmark case 仍按现有机制绑定其 `snapshot_id`，Runner 漂移拒绝继续是唯一数据绑定通道。
- **BenchmarkEnvironmentManifest**（`benchmark/environment.py`，version-controlled 提交 redacted 版）：
  ```json
  {
    "benchmark": "resume-benchmark-v1",
    "canonical_snapshot_id": "snapshot-v1:messages=...:...",
    "lexical_index": {"present": true, "message_count": 473236, "strategy": "<derived meta>"},
    "semantic_index": "<SemanticIndexIdentity.serialized>",
    "git_commit": "<pinned at freeze>",
    "created_at": "..."
  }
  ```
  - local 完整版（含私有 source metadata 引用）→ `data/evaluation/benchmark/environment.json`（gitignored）
  - redacted 版 → `evaluation/snapshots/resume-benchmark-v1.json`（复现说明用，不用于绑定）
- **Pre-run gate**（每次 benchmark 编排启动时，及 Stage 3/4 每次重跑前）：
  1. live `DatasetSnapshot.from_database(db).snapshot_id == manifest.canonical_snapshot_id`
  2. live `SemanticIndexIdentity.serialized == manifest.semantic_index`
  3. live lexical FTS count == canonical message count（复用现有 staleness 语义）
  任一失败 → 整个 benchmark 显式失败，不跑任何 variant。
- 运行中期漂移由现有机制兜底：Runner 每 case 重解析 Snapshot；semantic 查询 identity 失配显式 `SemanticIndexStale`。
- v1 Environment Manifest **pin 单一 serving semantic index**。未来若评测 embedding/index variant（如 Qwen vs BGE 同轮 A/B），应扩展为 per-variant index identity 或独立 environment matrix；v1 不解决该问题，不提前设计。

## 3. Ground Truth Schema（复用 ReferenceFinding，零 schema bump）

`benchmark/gt.py` 是唯一解析点，按 `finding_id`/`criterion` 前缀约定解析：

| GT 语义 | ReferenceFinding 表达 | 备注 |
|---|---|---|
| 相关消息 | `criterion="gt.relevant"`，每条一个 `ReferenceEvidence(relation="supports", source_type="message", locator={"internal_message_id":...})` | finding 级 `annotation_completeness` 声明完备度 |
| 必需上下文 | `criterion="gt.required_context"`，`relation="context"` | |
| 期望 coverage 状态 | `criterion="gt.expected_coverage_status"`，`expected_semantics` ∈ `complete\|partial\|none\|unknown\|not_applicable`（**生产 CoverageStatus 词表**） | 只在 GT 可可靠预期时声明；无法预期则不声明该 finding |
| 期望 truncation | `criterion="gt.expected_truncated"`，`expected_semantics` = `true\|false` | 独立轴；如 broad query 预期 `partial ∧ truncated=true` |
| 期望 zero-result | `criterion="gt.expected_zero_result"`，`expected_semantics` = `true\|false` | **单向蕴含**（gt.py 校验）：`expected_zero_result=true ⇒ 禁止 gt.relevant`；`expected_zero_result=false 时通常应存在 gt.relevant`（False Zero-Result Rate 的正例正依赖此组合）。不做双向互斥 |
| 期望事实 | `criterion="gt.expected_fact"`，`expected_semantics` = 规范化 alias 列表（JSON 序列化），绑定出处消息 | 仅 extractive fact |

**完备度声明规则（硬性）：**
- `exhaustive` 仅当 question 等价于一个独立确定性 predicate（包含某 URL / 提及某精确 repo 名 / 某人发的某类消息），且构造时用 SQL/LIKE 全库扫描证明枚举完备。
- semantic_paraphrase / context_recovery / temporal_overview 类默认 `partial`（GT = 人工确认的 target 集合），对应指标 scope=target/pool。
- `unknown` 保留给 pilot 阶段未完成证明的 case；进入最终 dataset 前必须显式化为 partial 或 exhaustive。

## 4. Measurement Substrate

### 4.1 Run projection 扩展（`checks.py`，evaluation 层）

`query_result_snapshot` 新增 `retrieval_calls`：

```json
{
  "retrieval_calls": [
    {
      "tool_call_id": "...",
      "tool_name": "lexical_search",
      "strategy": "lexical",
      "status": "ok",
      "total_hits": 31,
      "direct_hits": [{"rank": 1, "internal_message_id": "..."}],
      "direct_hit_count": 31,
      "expanded_ids": ["..."],
      "expanded_count": 12,
      "coverage_status": "partial",
      "truncated": true,
      "recorded_depth": 50,
      "omitted_ids": 13
    }
  ],
  "retrieval_calls_total": 5,
  "retrieval_calls_omitted": 1,
  "evidence_sources": [{"evidence_id": "...", "message_ids": ["..."], "structured_locator_kinds": []}]
}
```

- 边界（防止多轮调用累计无界）：
  - 每 call：direct_hits 前 50（带 rank）、expanded_ids 前 50；`omitted_ids` 记录未落盘数量
  - 每 run：`retrieval_calls` 最多 8 条（超出按时间顺序保留前 8，`retrieval_calls_omitted` 计数）
  - 所有数组长度 ≤ `MAX_EVALUATION_ITEMS=200`
- **深度语义**：GT 消息不在 recorded 深度内时，只能判 `not_observed_within_recorded_depth`，不得直接判 `retrieval_miss`。corpus 级 Retrieval Recall/MRR 由 module-level 通道（完整 tool-returned ranking）承载。
- Evidence 层：`evidence_sources` bounded 投影（evidence_id → source message IDs / locator kinds），指标引擎免开 conversation store。
- 数据链（每层独立落盘，互不混合）：
  ```
  Query → retrieval_calls.direct_hits(+rank) / expanded_ids
        → AnswerArtifact.evidence_items → evidence_sources
        → citation_bindings（content_block_id ↔ evidence_id）
  ```
- `tool_result_facts` 复制清单加入 `context_window_applied`；新增 deterministic check `context_expansion_override`。

### 4.2 Tier 1 指标定义（`benchmark/metrics.py`）

**前置**：每个 run 先算无条件指标：
- `Execution Completion Rate` = terminal completed / 全部 run
- `Valid Answer Rate` = (valid|degraded artifact) / 全部 run
条件质量指标的分母剔除 provider/runtime failure，但**必须**与上述无条件指标并列呈现。

| 指标 | 定义 | 输入 / scope |
|---|---|---|
| Recall@K / Hit@K | 命中 `gt.relevant` 比例 / 是否命中 | scope=corpus（仅 exhaustive GT，module-level 完整 tool-returned ranking）；scope=target（partial GT，分母=target 集合，命名 `Target Recall@K`） |
| MRR@K | 1/first-hit-rank，**cutoff=K 显式**（默认 MRR@10） | 同上；不宣称全库排序 |
| Evidence Recall | `|evidence_message_ids ∩ (relevant ∪ required_context)| / |relevant ∪ required_context|` | evidence_sources + GT；scope 随 GT 声明 |
| Context Recovery Success Rate | case 级布尔：`gt.required_context ⊆ evidence_message_ids`；无 required_context → not_applicable | 同上 |
| Coverage Status Accuracy | GT `expected_coverage_status`（有声明时）vs actual。actual **只读 Host-owned `AnswerArtifact.retrieval_coverage`**（canonical actual，含既有的最大 covered_units 汇聚规则）；artifact coverage unavailable → 指标 unavailable + reason。**禁止 metrics.py 从 retrieval_calls 自行重算 production coverage**；no-result Artifact 若缺 coverage facts 属 Measurement Substrate 缺口，应补 projection 而非在 Evaluation 层推断 | 只比较 status，不混入 truncated |
| Truncation Accuracy | GT `expected_truncated`（有声明时）vs 实际 truncated 事实 | 独立轴 |
| Expected Fact Answer Coverage | 仅 extractive fact case：每个 `gt.expected_fact` 的规范化 alias 在 **answer_text** 中命中（大小写/空白归一）的比例；evidence 含有不算 | artifact.answer_text + GT；分母=声明了 expected_fact 的 case |
| False Zero-Result Rate | GT 存在 relevant（expected_zero_result=false）∧ terminal completed 的 case 中，artifact 为 no_result 形态（单 answer block + 无 evidence/citation，Host contract 形态）比例 | artifact 投影 + GT |
| Verified Zero-Result Accuracy | expected_zero_result=true 中 terminal completed ∧ no_result 形态的比例（production positive-proof gate 保证已验证） | 同上 |
| latency / tool calls / tokens | P50/P95 latency_ms、tool_call_count、usage tokens | operational_measurements；诊断轴 |

聚合：per-case → per-category → per-variant → per-split（development / holdout / full）。每级输出分母 n、命中数、比率、unavailable 原因。`repetitions>1` 时输出 mean/方差。**v1 全量 1 rep。**

### 4.3 module-level 检索通道（`benchmark/retrieval.py`，薄 adapter）

- **只做**：Case（query、scope、GT、context 参数）→ `RetrievalQuerySet` → 调用现有 `RetrievalAnnotationWorkflow` 执行路径（同一 tool facade、同一 RetrievalRunRecord 产出，含 ranked_candidate_ids / expanded_message_ids / coverage / index_identity）→ 用 `gt.relevant` 直接评分。
- **不做**：重写 invocation、ranking、coverage projection、盲标逻辑。
- lexical 与 semantic 分列统计（回答「各自召回收益」）；context ablation = query set 显式控制 context_before/after（0 vs 生产默认），expanded_message_ids 独立记录。
- 输出表述统一为「完整 tool-returned ranking」（semantic hard cap 有限，非全库排序）。

### 4.4 ExecutionOverride 扩展（唯一生产契约变更）

```python
@dataclass(frozen=True)
class ExecutionOverride:
    forced_route: ForcedRoute | None = None
    context_window_limit: int | None = None   # 新增；None=生产默认
```

- 校验：非 None 时 ≥0；to_dict/from_dict 同步（旧 JSON 缺字段 → None，向后兼容）。
- 贯通：`QueryRequest.to_runtime_request()` → `AgentRunRequest.context_window_limit` → `RuntimeContext.context_window_limit` → runtime 构造 lexical_search / semantic_search / search_messages 输入时钳制 context_before/after。
- 不钳制：`get_message_context`（显式 deepening tool，其有无由 available_tools 控制，即 C 与 C2 的差异轴）、`get_recent_messages`（无 context 参数）。
- Trace：`query.received` 自动携带新字段；tool 完成 payload 追加 `context_window_applied` → deterministic check `context_expansion_override`（声明 limit=0 ⇒ 所有 retrieval call applied=0）。
- 变更范围：`query/contracts.py`、`query/runtime/contracts.py`、`query/runtime/openai_tools.py`（3 个工具输入构造点）、`evaluation/checks.py`；默认 None 行为逐字节不变。

## 5. Variants（Ablation Matrix）

| Variant | available_tools | context_window_limit | 单变量语义 |
|---|---|---|---|
| A `bench-lexical-only-v1`（role=minimal_control） | lexical_search | 0 | 基线 |
| B `bench-lexical-semantic-v1` | lexical, semantic | 0 | B−A = semantic uplift |
| C `bench-semantic-ctx-v1` | lexical, semantic | None | C−B = 自动 expansion uplift（唯一差异） |
| C2 `bench-semantic-ctx-tool-v1` | lexical, semantic, get_message_context | None | C2−C = explicit context tool uplift |
| D `bench-full-system-v1`（role=candidate） | 七工具 | None | full-system；与 A~C2 均为多变量 |

共同固定：canonical snapshot + environment manifest、provider/model（deepseek-v4-flash via opencode-go）、temperature/prompt 生产默认并记入 fingerprint、case scope、工具 budget 生产默认、index identity pin 真实值。`variant_diff` 记录两两差异。`context_expansion_configuration` 保留为描述性元数据并注明生效通道是 execution_override。

## 6. Tier 2 Judge（`benchmark/judge.py`，第二批实现）

- **claim 单位 = atomic factual claim**：Judge 先把每个 content block 切分为原子事实声明（输出去重后的 claim 列表），再逐 claim 判 evidence 支持（supports/contradicts/insufficient）。
  - `Grounded Claim Rate` = 有有效 evidence 支持的 atomic claim / 全部 atomic claim
  - `Citation Correctness` = 实际支持对应内容的 citation / 全部 citation（citation 粒度 = binding→evidence 对）
  - 若实现不做 atomic 切分，指标必须改名 `Cited Content Block Support Rate`，不得混称 Grounded Claim Rate
- 输入复用 `build_review_packet`（answer_text + selected sources + relation）。
- **逐条 adjudication**：audit queue 列出低 confidence / 高影响项供人工检查；**只有被人工实际确认的 item** 才标 `adjudicated`（per-item flag），未确认项永远保持 `llm_assisted_provisional`。抽查产出 `judge_human_agreement` / `audit_pass_rate`，报告并列展示；无整组升级。

## 7. Comparison Report（`benchmark/report.py`）

- JSON（全量指标+分母+unavailable reasons）+ Markdown 矩阵。
- Header：benchmark 名、environment manifest（snapshot/lexical/semantic/git commit）、variant fingerprints、case counts（含审核状态、dev/holdout 数）。
- Overall 矩阵：metric × {A,B,C,C2,D}，分 full / development / holdout 三列组；**full 仅在同 commit 的 dev rerun + holdout 之间合并**（版本一致性断言，commit 不一致则 full 列显式 unavailable）。
- 条件指标旁强制列 Execution Completion Rate / Valid Answer Rate。
- Per-category 矩阵：exact_lexical / semantic_paraphrase / context_recovery / temporal_overview / citation_evidence / zero_result。
- 跨 Variant 归因段：semantic uplift（module-level 与 end-to-end 两视图）、context uplift、B−A/C−B/C2−C diff；`semantic_miss` 类归因在此层，不在单 Run artifact。
- 无综合总分；holdout 与 full 并列且明确标注；简历引用以 holdout 优先。

## 8. Failure Artifact（`benchmark/failures.py`）

- **触发 = case 显式 acceptance condition 违反**：
  - required_context miss（Context Recovery=false）
  - false zero-result（GT 有 relevant 而 artifact 为 no_result 形态）
  - coverage status mismatch / truncation mismatch（GT 有声明时）
  - target Hit@K miss（GT 声明 target 集且 K 内全 miss）
  - terminal failure（provider/runtime/aborted）
  低 MRR / Recall<1 是质量结果 → 进 diagnosis，不生成 failure artifact。
- 内容：case_id / variant / expected / actual / direct+expanded IDs（含 `not_observed_within_recorded_depth` 标注）/ tool 序列 / coverage 三轴 / citations / trace_id / failure_category。
- **单 Run observation category 判定链（顺序）**：
  `provider_failure`（terminal 异常）→ `zero_result_error`（no_result 形态与 GT 矛盾）→ `coverage_error`（status/truncated 不一致）→ `context_missing`（required_context 未进 evidence）→ `retrieval_miss | not_observed_within_recorded_depth`（GT 消息不在 direct_hits）→ `ranking_failure`（在 direct_hits 但 rank>K）→ `router_tool_selection_error`（tool 序列与 diagnostic_expectations 明显背离）→ `answer_generation_error`（其余）→ `evaluation_infrastructure`（projection/check 自身失败）。
  `semantic_miss`（lexical 命中而 semantic 未命中）需要跨 Variant 比较，**只在 Comparison/Diagnosis 层归因**。

## 9. GT 构造流程与隔离

```
真实消息数据
  → candidate question 生成（LLM 辅助；来源：dogfooding / 归档 failure / 数据挖掘）
  → lexical + semantic + SQL 三路候选证据
  → 确定性 exhaustive 证明（仅 predicate 可枚举类：FTS+LIKE 全库扫描）
  → provisional Case（adjudicated=false）
  → 人工逐条 review（review markdown：query + 候选摘要 + 建议 GT + 修改槽）
  → adjudicated=true
```

- **Calibration pilot**：批量审核前，先取 8~12 个 dev case 走完 Stage 1 全链路（GT parser → runner → projection → metrics → report），验证数据模型后再扩展到 40~60。
- **目录与隔离**：
  - `evaluation/cases/benchmark/dev/*.json`、`calibration/*.json` → version-controlled（无正文；`why_relevant` ≤200 字符）
  - **数量口径**：calibration 是 substrate 校准 slice，不计入最终 benchmark 分母与 headline metric；final split = development（当前 37）+ holdout（冻结后生成 16~23）= 53~60
  - **holdout 在 Gate 3 系统冻结之后才生成与人工审核（构造时序隔离，blind by construction）**：冻结前不存在任何 holdout 文件，不依赖「不可访问某目录」的纪律；gitignored 目录仅作本地存放位置，不声称技术不可见
  - Suite：`resume-benchmark-dev-v1.json`（提交）、`resume-benchmark-holdout-v1.json`（Gate 3 后创建，local）、`resume-benchmark-v1.json` full 清单（提交 dev 明细；holdout 计数在 Stage 4 回填，不含 holdout 明文）
- 冻结记录：冻结时间、Development Case 的有序版本身份与 canonical 配置（Gate 3 本地保存）；holdout 在 Stage 4 注册时保存同样的明文配置以逐项比对（仅本地）。

## 10. 兼容性与回滚

- `ExecutionOverride` 新字段默认 None：现有 JSON/测试/调用方零改动；`from_dict` 缺字段 → None。
- `query_result_snapshot` / `tool_result_facts` 新增字段均为 additive，旧记录读侧可选。
- DatasetSnapshot 零改动；environment manifest 为纯新增 artifact。
- benchmark 模块与 orchestrator 全部为 evaluation 层新增；回滚 = 删除模块与 CLI 入口；ExecutionOverride 扩展可独立回滚。

## 11. 文件布局（新增/修改）

```
src/trivae/evaluation/benchmark/__init__.py
src/trivae/evaluation/benchmark/gt.py            新增
src/trivae/evaluation/benchmark/environment.py   新增（manifest + pre-run gate）
src/trivae/evaluation/benchmark/retrieval.py     新增（薄 adapter）
src/trivae/evaluation/benchmark/metrics.py       新增
src/trivae/evaluation/benchmark/judge.py         新增（第二批）
src/trivae/evaluation/benchmark/report.py        新增
src/trivae/evaluation/benchmark/failures.py      新增
src/trivae/evaluation/benchmark/orchestrator.py  新增
src/trivae/evaluation/checks.py                  修改（retrieval_calls / evidence_sources / context_window_applied / 新 check）
src/trivae/query/contracts.py                    修改（ExecutionOverride.context_window_limit）
src/trivae/query/runtime/contracts.py            修改（AgentRunRequest.context_window_limit）
src/trivae/query/runtime/openai_tools.py         修改（3 工具钳制点 + applied 事实）
src/trivae/interfaces/cli.py                     修改（eval benchmark 子命令）
evaluation/snapshots/resume-benchmark-v1.json    新增（redacted environment manifest）
evaluation/variants/bench-*.json × 5             新增（A/B/C/C2/D）
evaluation/cases/benchmark/{dev,calibration}/*.json  新增（审核后）
evaluation/suites/resume-benchmark-dev-v1.json   新增
evaluation/suites/resume-benchmark-v1.json       新增（dev 明细 + holdout 计数）
data/evaluation/benchmark/                       本地（gitignored）：environment 完整版 / holdout cases+suite（Gate 3 后生成）/ 中间产物 / failure artifacts
tests/test_benchmark_*.py                        新增
```

## 12. 2026-09-07 最终验收接线

保留 Gate 2 freeze contract，在 Evaluation benchmark 层新增 Gate 3 finalization owner（可独立 closure.py），通过现有 CLI 暴露 freeze-final / seal-holdout / merge-report 操作。冻结先记录 environment、Development suite/case identities、五 Variant 的 canonical configuration text；不使用内容摘要算法。holdout 注册于冻结后，校验 adjudication、split 与 Development 不重叠并保存完整 case 配置用于漂移检查。正式 run 以冻结旁的固定登记文件记录 started/completed/failed，首次请求前登记；中断保留 started，禁止另换输出目录绕过首次运行约束。只复用现有 production-path orchestration 与 report aggregation。

报告合并读取两个 output directory 中的 report/raw-records/failures；逐项比较 environment 和 Variant 配置，然后以原始逐 run metrics 构建 full，不能平均两个已聚合比率。版本不一致时 full 显式 unavailable，独立 split 仍可读取。

Judge 改动限错误出口与 provider 边界：保留 exception 类型和原因链，证据读取错误阻止该条判定，已有 JSON 损坏拒绝覆盖；OpenCode Go 发送稳定 session header；Judge JSON 使用 final output budget，不引入新 provider 重试。

关键模块七问：职责是完成评测验收边界；问题是当前 run 固定未封存且合并无版本检查；归属 Evaluation，不改 Query；输入为既有 manifest/suite/case/variant/run artifact，输出冻结/封存记录与报告；现有 runner/report 可复用；只有数据漂移、重复正式运行、版本混合和 Judge 失因这些已确认问题需要校验；测试以首次执行、错版本、错误证据与既有回归证明行为。

文件边界：closure.py（最终验收契约）、orchestrator.py（运行登记与 Judge 错误出口）、report.py（full unavailable 展示）、judge.py（provider 原因）、cli.py（薄入口）、对应测试、evaluation/README.md。无生产检索行为重构。
