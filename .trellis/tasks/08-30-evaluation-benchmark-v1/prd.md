# Evaluation Benchmark: resume-benchmark-v1 固定快照消融评测体系

> Revision 2（2026-08-30）：吸收外部 review 7 项实质修正 + P1 修正。变更摘要见文末。

## Goal

在固定真实群聊 Snapshot（`resume-benchmark-v1`）上建立一套**可复现、可解释、可产出简历硬指标**的 Evaluation Benchmark。复用现有 Evaluation 架构（Case/Suite/Snapshot/Variant/Runner/Checks/Store/Review/Comparison/Diagnosis），不新增平行框架。通过受控 Ablation 回答六个问题：

1. Lexical vs Semantic Retrieval 各自的召回收益
2. 自动 Context Expansion 与显式 context tool 各自是否提高完整证据恢复能力
3. Temporal / Broad Query 能否正确识别 coverage 状态
4. Evidence / Citation 能否保证回答有真实聊天记录支撑
5. 正常链路下系统是否会错误声称「范围内没有结果」
6. 完整 Trivae 相比受控 Baseline 的提升幅度

## Requirements

### R1 固定 Snapshot 与 Environment 分离
- `DatasetSnapshot` 保持现有契约原样：只描述 canonical dataset identity（snapshot_id/fingerprint 由 canonical manifest 推导），**不**塞入 semantic index identity、git commit、benchmark 元数据
- 新增薄的 **BenchmarkEnvironmentManifest**：记录 `canonical_snapshot_id + lexical index identity + semantic index serialized identity + benchmark name + git commit + created_at`；pre-run gate 逐项与 live 环境比对，任一不匹配则整体显式失败
- 模型/prompt/code version 归 `ControlledVariant`（现有字段），不进 DatasetSnapshot
- 私有 source metadata 不进仓库；禁止把同一数据因 semantic rebuild/commit 不同错误建模成不同 Dataset

### R2 Benchmark Case 数据集（质量优先）
- v1 目标 40~60 条高质量 case（上限 100），逐条人工 review 后 `adjudicated=true`
- 至少覆盖六类：exact_lexical、semantic_paraphrase、context_recovery、temporal_overview、citation_evidence、zero_result
- Case 来源优先级：真实 dogfooding 问题 > 已归档 Failure Case > 数据自然可提出的问题 > 人工设计
- 已知 Failure Case（2699/100 覆盖误判、CJK 0-hit、合法空窗等）进 development set 作回归
- **GT 完备度按 case 类型如实声明**：
  - 只有 question 可被独立确定性 predicate 枚举（如「包含某 URL 的消息」）的 case 才可标 `exhaustive`（用 SQL/LIKE 全库扫描证明）
  - semantic_paraphrase 类 GT 是人工确认的 target 集合，默认 `partial`，**不得声称 corpus Recall**（禁止用待评估的检索机制证明 GT 完备）
- 拆分：约 60~70% development / 30~40% holdout（holdout 部分在 Gate 3 冻结后构造）
- **Holdout 构造时序隔离 + 一次定稿**：
  - **holdout 在 Gate 3 系统冻结之后才生成与人工审核**（构造上 blind：冻结前不存在任何 holdout 文件，不依赖「不可访问某目录」的纪律）；存放于 `data/evaluation/benchmark/holdout/`（gitignored）
  - 第一次正式 holdout 运行即 `resume-benchmark-v1` 最终结果；结果无论好坏**封存照报**
  - 若暴露真实 Bug：v1 结果保留，修复进入 `resume-benchmark-v2`（届时生成全新 holdout）
  - 仅允许按**预先声明**的无效条目规则替换 holdout case：(a) GT 与 Snapshot 事实矛盾；(b) 与其他 case 重复；(c) 数据损坏。替换必须记录原因；**禁止因系统答错而替换**
- Semantic paraphrase 的 query 与 GT 原文表达必须有明显差异，不得构造只对 semantic 有利的人工题
- GT 通过 ReferenceFinding criterion 约定表达（见 design §3），绑 canonical message ID
- **v1 负例范围**：真实无结果窗口（SQL 证明为空）+ 正常链路 false no-result。tool failure / semantic unavailable / stale / timeout 等故障注入**不在 v1 验收范围**（无稳定注入机制前不宣称覆盖），相关行为由既有 production contract tests / failure regression 承载

### R3 Ablation Variants（同 Snapshot、同 Environment、同 provider/model/prompt/temperature/scope/budget）

| Variant | available_tools | context_window_limit | 单变量语义 |
|---|---|---|---|
| A `bench-lexical-only-v1`（minimal_control） | lexical_search | 0 | 基线 |
| B `bench-lexical-semantic-v1` | lexical + semantic | 0 | B−A = semantic uplift |
| C `bench-semantic-ctx-v1` | lexical + semantic | 生产默认 | **C−B = 自动 context expansion uplift（真单变量）** |
| C2 `bench-semantic-ctx-tool-v1` | lexical + semantic + get_message_context | 生产默认 | C2−C = 显式 deepening tool uplift |
| D `bench-full-system-v1` | 七工具 | 生产默认 | 与 A~C2 均为多变量差异，只作 full-system 结果 |

- Context expansion 关闭通过 `ExecutionOverride.context_window_limit` 最小扩展实现（已确认现有 `context_expansion_configuration` 只是 variant 元数据、不贯穿生产 Runtime，见 research/evaluation-audit.md 确认 1；默认 None 行为不变，Trace 可验证）
- 禁止为实验在生产代码引入旧行为或针对单题的特殊逻辑

### R4 指标引擎（新增，读取现有 Run projections + Artifact + GT）
**两档指标，显式分离：**
- **Tier 1 Deterministic（简历优先）**：Recall@K、Hit@K、MRR@K、Evidence Recall、Context Recovery Success Rate、Coverage Status Accuracy、Truncation Accuracy、Expected Fact Answer Coverage、False Zero-Result Rate、Verified Zero-Result Accuracy、Execution Completion Rate / Valid Answer Rate、latency / tool calls / tokens（诊断轴）
- **Tier 2 LLM-assisted provisional（逐条人工确认才升级）**：Grounded Claim Rate（atomic claim 单位）、Citation Correctness、answer quality axes

**指标可用性与命名硬规则：**
- `Recall@K / Hit@K` scope=corpus 仅限 `exhaustive` GT（可确定性枚举的 case）；target 集合 GT 一律报 `Target Recall@K`（scope=target/pool），并声明枚举边界
- MRR 一律带 cutoff（如 `MRR@10`）或显式声明 evaluation cutoff；module-level 的「完整 ranking」表述为「完整 tool-returned ranking」，不宣称全库排序
- **Coverage 三轴分离**（对齐生产 contract：`CoverageStatus = complete|partial|none|unknown|not_applicable`，`truncated` 为独立 flag，`no_result` 是答案形态）：
  - `expected_coverage_status` ∈ 生产 CoverageStatus 词表 → `Coverage Status Accuracy` 只比较它
  - `expected_truncated`（bool）→ `Truncation Accuracy` 单独比较
  - `expected_zero_result`（bool）→ zero-result 指标单独测；GT 单向蕴含：`=true ⇒ 无 gt.relevant`，`=false ⇒ 通常应有 gt.relevant`
- **Coverage actual 只读 Host-owned 事实**：`AnswerArtifact.retrieval_coverage` 为 canonical actual；unavailable → 指标 unavailable + reason；**禁止 metrics 层从 retrieval_calls 重算 production coverage**
- **Expected Fact Answer Coverage（替代原 Complete Answer Rate）**：仅限有明确规范化 alias 的 extractive fact，且必须命中 `answer_text`（evidence 包含不算——那是 Evidence Recall 的职责）；不作为所有 temporal/summary case 的通用完整率；一般性回答完整性归 Tier 2 / 人工 Review
- **Grounded Claim Rate 单位 = atomic factual claim**：Judge 先把 content block 切分为原子事实声明，再判 evidence 是否支持；若不做切分则指标改名 `Cited Content Block Support Rate`，不得混称
- **条件指标必须伴随无条件指标**：报告同时给出 `Execution Completion Rate`（terminal completed / 全部 run）与 `Valid Answer Rate`（valid/degraded artifact / 全部 run），防止「排除 provider failure 后条件正确率虚高」
- `unknown` GT → Recall 显式 unavailable；报告中每个指标带 scope 与 GT completeness 说明

**Baseline 策略（不制造 Baseline）：**
- Ablation 只做干净单变量：B−A、C−B、C2−C
- Coverage / Zero-result / Evidence 类指标以固定 benchmark 绝对正确率呈现；不实现 legacy broken mode
- 历史真实 Failure before/after 引归档 Trace 证据，不重放伪造
- D 与其他 Variant 的差异必须标注为多变量

**其他硬规则：**
- Provider failure / runtime failure 不混入 Retrieval 等条件指标分母，但无条件指标（completion rate）必须呈现
- incomplete coverage 不算正确；citation 存在 ≠ citation 正确；未逐条人工确认的 Tier 2 判定保持 `llm_assisted_provisional`（抽查产出 judge-human agreement / audit pass rate，不整组升级）
- 运行中期数据漂移由现有机制显式失败（Runner 每 case 重解析 Snapshot；semantic identity 失配显式 stale + pre-run gate）
- 私有正文/source metadata 不进仓库

### R5 Comparison Report
- 机器可读 JSON + 人可读 Markdown：metric × variant 矩阵，按 category 拆分，区分 full benchmark 与 holdout
- 条件指标旁必须列对应无条件指标（completion / valid answer rate）
- 跨 Variant 归因（如 semantic uplift/miss）在 Comparison/Diagnosis 层呈现，不写入单 Run artifact
- 不构造无解释价值的综合总分

### R6 Failure Diagnosis
- **Failure 判定基于 case 显式 acceptance condition**：required context miss、false zero-result、coverage status mismatch（GT 有声明时）、target Hit@K miss（GT 有 target 集时）、terminal failure。低 MRR / Recall<1 属质量结果，进 diagnosis 不自动成 failure
- 每个 failure artifact 保留：case_id、variant、expected、actual、direct/expanded message IDs（含 `not_observed_within_recorded_depth` 标注）、tool calls、coverage 三轴、citations、trace_id、failure category
- **单 Run 只记录 observation 类 category**：provider_failure / retrieval_miss（含 not_observed 变体）/ ranking_failure / context_missing / coverage_error / zero_result_error / answer_generation_error / evaluation_infrastructure；`semantic_miss` 等跨 Variant 归因放 Comparison/Diagnosis 层

### R7 测试、校准与版本一致性
- Unit tests：指标计算（各 scope 的 Recall/Hit/MRR@K、coverage 三轴、zero-result、Expected Fact Answer Coverage、GT 加载与一致性校验、variant config、environment manifest gate）
- Integration tests：固定 snapshot + fixed case + deterministic retrieval + comparison report + failure artifact 持久化 + holdout 目录隔离（gitignore 断言）
- **Calibration gate（人工审核 40~60 条之前）**：用 8~12 个 dev pilot case 端到端验证 GT parser、run projection、metrics、report 的数据模型，确认无误后再批量构造
- Real smoke：真实 dataset snapshot + 真实检索索引 + 真实 semantic model + 真实 LLM provider
- **版本一致性**：Gate 3 末次修复后必须在冻结 commit 上**完整重跑整个 dev suite**；holdout 在同一 commit、同一 variant fingerprint 下运行；只有同 commit 的 dev+holdout 才允许合并为 full
- 最终数字只能来自真实运行，绝对禁止预设/伪造/估算

### R8 交付物
1. Evaluation 现状审计（沉淀于 research/evaluation-audit.md）
2. Benchmark Schema 说明
3. Benchmark 数据集统计（总数、分类、dev/holdout、审核状态）
4. Ablation Matrix 说明（A/B/C/C2/D）
5. 真实 Benchmark Result（无数据写 not measured）
6. Failure Analysis（acceptance-condition failures + root cause）
7. 简历候选指标 2~4 个（holdout 优先，含 baseline/current/absolute/relative/样本量/scope）
8. `.trellis/spec/project/interview-defense.md` 新增事实索引章节

## Constraints

- 复用现有 Evaluation 架构；contract 无法承载时才最小扩展并说明原因
- 不为 benchmark 修改生产逻辑（`ExecutionOverride.context_window_limit` 除外，evaluation-only）
- `benchmark/retrieval.py` 只能是 Case GT → 现有 RetrievalQuerySet/Workflow 的薄 adapter，禁止重写 invocation/ranking/coverage projection
- 不修改 Ground Truth 迁就系统输出；LLM 生成内容不是唯一 GT
- 私有聊天正文/source metadata 不进仓库（`data/evaluation/` 本地、`evaluation/` 只进无正文 artifact）

## Acceptance Criteria

- [ ] `resume-benchmark-v1` canonical Snapshot + BenchmarkEnvironmentManifest 存在；pre-run gate 三查（snapshot/semantic identity/lexical count）通过；Runner 漂移拒绝验证
- [ ] ≥40 条人工 adjudicated dev case（六类齐全，含 calibration pilot）；holdout 在 Gate 3 冻结后生成并审核（构造时序隔离）
- [ ] A/B/C/C2/D 五 variant 定义完成且 diff 可追溯；context 钳制在 Trace 可验证；B−A / C−B / C2−C 构成真单变量
- [ ] Calibration pilot（8~12 case）通过后才进入批量审核；指标引擎 + report 测试全绿，`pytest -q` 全绿
- [ ] 真实 benchmark 跑完：冻结 commit 全 dev rerun + 同 commit holdout 一次性运行；结果 JSON + Markdown，holdout 单独封存报告
- [ ] 每个指标带 scope/GT completeness/无条件分母；失败 case 有 acceptance-condition failure artifact
- [ ] interview-defense.md 新增章节；简历候选指标基于真实 holdout 结果
- [ ] 无伪造数字；`llm_assisted_provisional` 与逐条 adjudicated 状态显式区分

## Revision 2 变更摘要

1. Coverage GT 拆为 `expected_coverage_status / expected_truncated / expected_zero_result` 三轴，对齐生产 `CoverageStatus` 词表与独立 truncated flag
2. Variant 矩阵改为 A/B/C/C2/D：C 只恢复自动 expansion，C2 才加 get_message_context，保证 B−C、C−C2 单变量
3. Holdout 改为 local-only 技术隔离 + v1 一次定稿；删除「失败降级 + reserve 补位重跑」流程，改为无效条目预声明规则 + 修复进 v2
4. `DatasetSnapshot` 恢复原职责；新增 BenchmarkEnvironmentManifest 承载 index identity / commit / gate
5. Semantic 类 GT 不再声称 exhaustive/corpus Recall；改 Target Recall@K；只有确定性可枚举 predicate 的 case 可 exhaustive
6. `Complete Answer Rate` 收窄改名 `Expected Fact Answer Coverage`（answer_text 命中、extractive fact 限定）；一般完整性归 Tier 2
7. Grounded Claim Rate 改 atomic claim 单位；Tier 2 逐条 adjudication，废除整组升级
8. Failure artifact 改 acceptance-condition 触发；单 Run 只记 observation category，跨 Variant 归因上移；`not_observed_within_recorded_depth` 语义
9. 报告强制携带 Execution Completion Rate / Valid Answer Rate 无条件指标
10. Gate 3 增加「冻结 commit 全 dev rerun」；MRR@K 显式 cutoff；`benchmark/retrieval.py` 定位为薄 adapter
