# M7 Evaluation / Regression

## Goal

把 Stage 1.10 Evaluation 与 Stage 1.11 Application Architecture 的已确认契约落成第一版可运行闭环：固定 Case、Snapshot、Data Access Scope 和 Controlled Variant，重复调用生产 `TrivaeApplication.query()`，保留 Answer Artifact / Trace reference，执行确定性检查，持久化 Run / Review / Comparison / Diagnosis，并把真实 Failure 提升为 Regression Case。

用户价值是能够回答“同一个问题、同一份数据和权限条件下，Prompt / Router / Planner / Retrieval / Model 的改动是否改变了真实结果”，且能沿 Trace 区分质量变化与 diagnosability / operational 变化。

## Confirmed facts and constraints

- 当前 `main` 已包含完整 M6，含 `639eac5 fix: stabilize DeepSeek tool provenance`；M7 分支从该提交所在的 `main` 创建。
- `TrivaeApplication.query()` 是当前唯一生产 Query application entry；它进入同一个 `QueryOrchestrator`，再进入 Router / optional Planner / Agent Runtime / Tool / Retrieval / Evidence / Conversation commit。
- M6 Trace 是 append-only canonical facts；Evaluation 只能读取和关联，不能修改、补造或用 Diagnosis 覆盖 Trace。
- M5 Evidence/Citation Finalizer 已拥有 current-run provenance、scope 校验和 invalid citation 显式失败语义；M7 不新增 Citation Validator、Evidence Agent 或 repair/fallback。
- 当前 Canonical Store 是 SQLite，Conversation Store 与 Trace Store 已有独立 ownership；Evaluation Store 必须使用独立 SQLite 文件和连接。
- 项目要求根因优先、错误透明、最小修复；禁止为单个 Case 加特判、静默吞错、无依据 retry/fallback、哈希/SHA256 和隐藏 reasoning。
- ChatLab 只作为 seed/scenario 参考，不继承固定 24 Case、expectedRoute、关键词 Judge、经验参数或 Router accuracy 作为最终质量标准。

## In scope

1. `src/trivae/evaluation/` 中实现 typed、可序列化、可版本化的 Case Bundle、Reference Finding/Evidence、三态 annotation completeness、Dataset Snapshot、Controlled Variant、Suite、Run、Result、Review、Paired Comparison、Failure Diagnosis。
2. 在 `QueryRequest` 增加显式 `ExecutionOverride`：`None` 保持生产路由；`standard_execution` 绕过 Router 但进入同一 Runtime；`planned_execution` 绕过 Router 后进入同一 Planner/Runtime。override 必须出现在 Query Trace、Run metadata 和 Variant identity。
3. 实现 local-first `EvaluationStore`：独立 SQLite 持久化 runs、results、reviews、comparisons、failure diagnoses；支持 close/reopen；不写入 Canonical Chat Store。
4. 实现 `EvaluationRunner`：单 Case、Suite、`repetitions > 1`，只编排输入/Variant/读取结果/Trace/Checks，不复制业务执行逻辑；Query failure 原样保留。
5. 实现 Deterministic Checks，至少覆盖 Case/Snapshot/Scope/Variant identity、terminal/finalization/Answer Artifact、Citation/provenance outcome、Trace existence/completeness/terminal consistency、partial/truncated/coverage、forced override 记录和 replay identity。
6. 实现 Human review packet 的导出/结构化导入；提供可注入 fake/deterministic `JudgeAdapter`，不让 Judge 进入在线 Query 主链，也不让 Judge 修改 QueryResult。
7. 实现 blind paired comparison 的身份/条件校验、A/B 随机顺序和 randomization identity；保存每个单次 Run，不只保存平均值。
8. 提供第一批小型 Design/Seed 与 Failure Regression case metadata，覆盖用户要求的 retrieval、scope、context、no-result、insufficient/partial、evidence/citation、standard/planned 和 M6 Failure A/B/C 映射；不把不存在的能力标为必过。
9. 提供最小 `trivae eval` CLI，保持 CLI → Application/Evaluation Service → Runner → `TrivaeApplication.query()` 链路。
10. 使用临时数据副本完成真实数据 Calibration、pinned last-stable baseline、至少一组 forced-standard vs forced-planned paired experiment，以及 repeated-run smoke；不提交原始聊天、真实姓名、QQ 号、secret 或完整回答正文。

## Out of scope

- 第二套 EvalRouter、EvalPlanner、EvalRuntime、EvalRetrieval、Evidence Agent 或自动修正链路。
- Distributed queue、Celery/Kafka/Kubernetes、scheduler、外部 observability、Dashboard、HTTP/UI、在线 Judge、自动 Prompt Optimizer、自动 Retry Policy。
- 单一总分、无真实证据的质量 promotion threshold、固定 repetitions、统计显著性平台或声称“最优 baseline”。
- 复制完整 Canonical 数据库正文到 Evaluation Store；Evaluation Store 只保存 identity、bounded metadata、结果/评审/诊断引用。
- 为旧 Failure 增加 clamp、猜测 locator、混合 provenance 兼容、静默降级或为了通过 Regression 改写生产错误。

## Acceptance criteria

- [x] Case Bundle round-trip、版本和 reference relationship validation 通过；`exhaustive / partial / unknown` 语义与 Review/Recall 限制可见。
- [x] Snapshot identity 能从 Canonical SQLite manifest 稳定重建，不依赖漂移路径；不同数据条件不同；`invalid/restricted/unavailable` 不可被 Runner 假装为可用。
- [x] Controlled Variant fingerprint 对相同 normalized config 稳定、对配置变化改变，并拒绝 secrets；Baseline 是 pinned `last_stable`，Candidate 有显式 diff。
- [x] `forced_route=None` 继续走正常 Router；两种 forced route 都通过同一个 QueryOrchestrator/Runtime；override 不伪装为 Router decision。
- [x] Runner 的集成测试证明它调用生产 `QueryOrchestrator`，不复制 Runtime；Query failure、Trace reference、partial/truncated 和 terminal mismatch 原样进入 Run/Checks。
- [x] Evaluation Store close/reopen 后可恢复 Run、Result、Review、Comparison、Diagnosis，且不污染 Canonical Chat DB。
- [x] Deterministic hard gates 拒绝 invalid citation、scope violation、mixed provenance、critical known regression、identity/snapshot mismatch；Trace incomplete 只降低 diagnosability，不自动判 Answer wrong。
- [x] Human review contract、blind paired comparison、failure diagnosis 和 fake Judge contract 可用；没有 model Judge 时不阻塞真实 Query/Evaluation。
- [x] M6 trusted-limit Failure A 与 mixed-locator Failure B 的合法/非法边界 regression 通过；Failure C 映射可从报告查看。
- [x] 完成真实数据 Calibration、scripted integration baseline、一次 paired experiment 和 repetitions smoke；结果区分 measured facts、quality review、operational metrics、Trace diagnosis 和 known limitations，并明确真实 Provider blocked。
- [x] `PYTHONPATH=src ./.venv/bin/pytest -q`、`./.venv/bin/ruff check src tests`、`./.venv/bin/mypy`、`git diff --check` 及 Trellis validation 通过；commit/push 后工作树 clean。

## Resolved scope decisions

- 第一版使用独立 SQLite Evaluation Store；Case/Suite 使用仓库内 human-readable JSON，Run/Review/Comparison/Diagnosis 使用 SQLite。
- Snapshot 的 deterministic fingerprint 使用 canonical manifest（schema/source/import/count/time/index facts），不做全库复制或密码学 hash；该边界和不可识别的内容突变会记录为 limitation。
- quality axes 只保存 Finding Correctness、Evidence Completeness、Groundedness/Entailment、Uncertainty Calibration、Answer Relevance；Diagnosability 和 latency/token/tool/coverage/termination 独立保存。
- Planner Utility 先比较同 Case/Snapshot/Scope/Model/Prompt/Tool/Retrieval/Budget 下的 forced standard 与 forced planned；Router Utility 只在其后对照评估，不把 expectedRoute 当 Gate。

## Blocking open questions

无。实现细节均限制在已确认 ADR 和现有代码 contract 内；真实 Provider 可用性若受外部环境影响，保留 deterministic/scripted calibration 并在 validation 明确 blocked，不伪造真实结果。
