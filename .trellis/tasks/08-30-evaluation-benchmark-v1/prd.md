# Evaluation Benchmark: resume-benchmark-v1 固定快照消融评测体系

## Goal

在固定真实群聊 Snapshot（`resume-benchmark-v1`）上建立一套**可复现、可解释、可产出简历硬指标**的 Evaluation Benchmark。复用现有 Evaluation 架构（Case/Suite/Snapshot/Variant/Runner/Checks/Store/Review/Comparison/Diagnosis），不新增平行框架。通过受控 Ablation（Lexical / +Semantic / +Context Expansion / Full）回答六个问题：

1. Lexical vs Semantic Retrieval 各自的召回收益
2. Context Expansion 是否提高完整证据恢复能力
3. Temporal / Broad Query 能否正确识别 complete / partial / truncated coverage
4. Evidence / Citation 能否保证回答有真实聊天记录支撑
5. Retrieval/Tool 失败时系统是否错误声称「范围内没有结果」
6. 完整 Trivae 相比受控 Baseline 的提升幅度

## Requirements

### R1 固定 Snapshot
- Materialize 并固化 `resume-benchmark-v1` Snapshot manifest；所有 Variant 基于同一 Snapshot
- Snapshot 记录：source identity、message count、session count、时间范围、index identity（lexical + semantic）、schema version、创建时间；禁止把私有 source metadata 原文提交进仓库
- Runner 已有的 Snapshot 漂移拒绝机制作为唯一绑定方式

### R2 Benchmark Case 数据集（质量优先）
- v1 目标 40~60 条高质量 case（上限 100），全部人工 review 后 `adjudicated=true`
- 至少覆盖六类：exact_lexical、semantic_paraphrase、context_recovery、temporal_overview、citation_evidence、zero_result
- Case 来源优先级：真实 dogfooding 问题 > 已归档 Failure Case > 数据自然可提出的问题 > 人工设计
- 已知 Failure Case（2699/100 覆盖误判、CJK 0-hit、虚假 COVERAGE_MISMATCH、合法空窗被拒等）进 development set 作回归
- 拆分：约 60~70% development / 30~40% holdout；holdout 必须包含新的真实问题
- **Holdout 冻结纪律**：case pool 人工审核完成后立即冻结 dev/holdout 归属；开发阶段只允许看 dev；系统与参数冻结后才允许跑 holdout；若跑 holdout 后因查看 Trace 修复问题，该 case 降级为 development 并从预留池补入新 case；最终简历优先报告 holdout 结果
- Semantic paraphrase 类的 query 与 GT 原文表达必须有明显差异，不得构造只对 semantic 有利的人工题
- GT 通过 ReferenceFinding criterion 约定表达（relevant / required_context / expected_coverage / expected_zero_result），绑 canonical message ID
- exact_lexical 与 semantic_paraphrase 的 GT 应尽量做到 `annotation_completeness=exhaustive`（用确定性 SQL/FTS 全库扫描证明枚举完备），这是 corpus-bound Recall 的前提

### R3 Ablation Variants（同 Snapshot、同 provider/model/prompt/temperature/scope/budget）
- A：lexical-only，无 context expansion
- B：lexical + semantic，无 context expansion
- C：lexical + semantic + context expansion（含 get_message_context）
- D：完整七工具 + 当前 coverage/evidence 行为
- Context expansion 关闭通过 `ExecutionOverride` 最小扩展实现（已确认现有 `context_expansion_configuration` 只是 variant 元数据、不贯穿生产 Runtime，见 research/evaluation-audit.md 确认 1；evaluation-only 钳制，默认 None 行为不变，Trace 可验证 override 生效）
- 禁止为实验在生产代码引入旧行为或针对单题的特殊逻辑

### R4 指标引擎（新增，读取现有 Run projections + Artifact + GT）
**两档指标，显式分离：**
- **Tier 1 Deterministic（简历优先）**：Recall@5/10、MRR、Hit@K、Evidence Recall、Context Recovery Success Rate、Coverage Status Accuracy、Complete Answer Rate、False Zero-Result Rate、Verified Zero-Result Accuracy、latency / tool calls / tokens（诊断轴）
- **Tier 2 LLM-assisted provisional（人工抽查后升级 adjudicated）**：Grounded Claim Rate、Citation Correctness（entailment）、answer quality axes

**GT 完备度决定指标可用性（硬规则）：**
- `annotation_completeness=exhaustive` 的 case → corpus Recall@K / Hit@K / MRR（scope=corpus）
- `partial` → 仅 pool-relative 指标（scope=pool）或 unavailable
- `unknown` → Recall 显式 unavailable
- 报告中每个指标必须带 scope（corpus / pool）与 GT completeness 说明

**Baseline 策略（不制造 Baseline）：**
- Ablation 只用于干净的单变量实验：A vs B（semantic 收益）、B vs C（context expansion 收益）
- Coverage / Zero-result / Evidence 类指标以固定 benchmark 上的绝对正确率呈现（如 `Coverage Status Accuracy = n/N`），不实现 legacy broken mode 来制造 before/after
- 历史真实 Failure Case 的 before/after 引用归档 Trace 证据（如 2699/100），不重放伪造
- D vs A 可作为 overall 汇总对比，但必须显式标注为多变量差异

**其他硬规则：**
- Provider failure / runtime failure 不混入 Retrieval 指标分母；incomplete coverage 不算正确；citation 存在 ≠ citation 正确
- 运行中期数据漂移由现有机制显式失败（Runner 每 case 重解析 Snapshot；semantic identity 失配显式 stale）
- 私有正文/source metadata 不进仓库

### R5 Comparison Report
- 机器可读 JSON + 人可读 Markdown：metric × variant 矩阵，按 category 拆分，区分 full benchmark 与 holdout
- 不构造无解释价值的综合总分

### R6 Failure Diagnosis
- 每个失败 case 保留：case_id、variant、expected、actual、retrieved message IDs、tool calls、coverage、citations、trace_id、failure category（区分 retrieval miss / ranking failure / semantic miss / context missing / router-tool selection error / coverage error / citation mismatch / answer generation error / provider failure）

### R7 测试与真实运行
- Unit tests：指标计算（Recall@K、MRR、coverage accuracy、zero-result、citation metrics、GT 加载、variant config）
- Integration tests：固定 snapshot + 固定 case + deterministic retrieval + comparison report + failure artifact 持久化
- Real smoke：真实 dataset snapshot + 真实检索索引 + 真实 semantic model + 真实 LLM provider；不能只用 fixture 宣称完成
- 最终数字只能来自真实运行，绝对禁止预设/伪造/估算

### R8 交付物
1. Evaluation 现状审计（已在会话完成，沉淀进 design.md）
2. Benchmark Schema 说明
3. Benchmark 数据集统计（总数、分类、dev/holdout、审核状态）
4. Ablation Matrix 说明
5. 真实 Benchmark Result（无数据写 not measured）
6. Failure Analysis（最差 case + root cause）
7. 简历候选指标 2~4 个（含 baseline/current/absolute/relative/样本量/dev or holdout）
8. `.trellis/spec/project/interview-defense.md` 新增事实索引章节

## Constraints

- 复用现有 Evaluation 架构；contract 无法承载时才最小扩展并说明原因
- 不为 benchmark 修改生产逻辑（ExecutionOverride 扩展除外，evaluation-only）
- 不修改 Ground Truth 迁就系统输出；LLM 生成内容不是唯一 GT
- 私有聊天正文/source metadata 不进仓库（遵循现有 .gitignore 边界：`data/evaluation/` 本地、`evaluation/` 只进无正文 artifact）
- 引擎原则遵循 `.trellis/spec/project/engineering-principles.md` §5 与 temporal-overview/zero-result 相关 spec

## Acceptance Criteria

- [ ] `resume-benchmark-v1` snapshot manifest 存在且所有 benchmark case 绑定其 snapshot_id；Runner 漂移拒绝验证通过
- [ ] ≥40 条人工 adjudicated benchmark case，六类覆盖齐全，dev/holdout 拆分明确
- [ ] 四个 Ablation Variant 定义完成且 diff 可追溯；context expansion 钳制在 Trace 中可验证
- [ ] 指标引擎 + report 生成器实现，unit/integration 测试通过，`pytest -q` 全绿
- [ ] 真实 benchmark 全量跑完（1 rep），结果 JSON + Markdown report 生成，holdout 单独报告
- [ ] 每个 metric 均可从 Evaluation Artifact + Trace 复查；失败 case 有 failure artifact
- [ ] interview-defense.md 新增章节；简历候选指标基于真实 holdout/全量结果
- [ ] 无任何伪造数字；provisional 与 human_verified 状态在报告中显式区分
