# M7 Evaluation / Regression 技术设计

## 1. Ownership 与运行边界

Evaluation 只拥有 Case、Suite、Variant、Runner、Review、Comparison、Diagnosis 和 Store 语义。它不拥有 Query 业务规则，也不创建第二套 Router、Planner、Runtime、Tool 或 Retrieval。

```text
Case/Suite JSON
  -> DatasetSnapshot + ExecutionScope + ControlledVariant
  -> EvaluationRunner
  -> QueryRequest(execution_override)
  -> TrivaeApplication.query()
  -> QueryOrchestrator -> Router/Planner -> shared Runtime/Tool/Retrieval
  -> QueryResult + canonical Trace reference
  -> deterministic checks -> review/result/comparison/diagnosis
```

`EvaluationRunner` 依赖 Application-level query executor 和 Trace reader 的最小 callable，不依赖 Application 私有 Runtime；Composition Root 负责把现有 `TrivaeApplication.query()`、`read_trace()`、`EvaluationStore` 装配在一起。

## 2. Package layout

```text
src/trivae/evaluation/
  __init__.py       # 对外导出稳定 contract
  contracts.py      # Case/Snapshot/Suite/Run/Result/Review/Comparison/Diagnosis
  variant.py        # ControlledVariant normalized identity 与显式 diff
  checks.py         # deterministic contract checks 与 operational projection
  store.py          # 独立 SQLite Evaluation Store
  runner.py         # Case/Suite 编排，调用 Application query
  review.py         # review packet、JudgeAdapter、blind pairing、诊断
evaluation/
  cases/*.json      # 不含聊天正文的 version-controlled seed/regression metadata
  suites/*.json     # 只引用 case_id + version，不复制 truth
```

文件按当前规模保持有限拆分；如果某个 contract 只服务一个模块，不再增加额外 ports/adapters/domain/usecases 层。

## 3. Core contracts

### Case / Reference

- `EvaluationCaseBundle` 为 frozen dataclass，包含稳定 `case_id`、正整数 `version`、scenario tags、`DatasetSnapshot`、现有 `ExecutionScope`、query、locale/time context、多个 `ReferenceFinding`、uncertainty/negative constraints、critical requirements、diagnostic expectations、`ReviewPolicy` 和 provenance。
- `ReferenceFinding` 以 `finding_id` 为 identity，记录 criterion、expected semantics、多个 `ReferenceEvidence`、finding-level `annotation_completeness`、reference provenance、known limitations、critical/optional。
- `ReferenceEvidence` 必须有 relation（`supports`/`contradicts`/`context`）、结构化 source locator、`why_relevant` 和 provenance；不只存 message ID。
- Case 校验 finding/evidence ID 唯一、evidence 关系合法、source locator 非空；Case 级 completeness 只做派生摘要。
- JSON codec 显式读写，不使用 `pickle` 或隐式 `asdict` 作为公共 schema。

### Dataset Snapshot / Scope

`DatasetSnapshot.from_database()` 使用独立只读 SQLite connection 读取 schema version、sources/import identity、message count、first/last timestamp、lexical index presence/count 和 status，形成 deterministic manifest。`snapshot_id` 基于 manifest 的稳定字段，不包含数据库路径，不复制正文，不做哈希。若 canonical schema/source 不可读则明确抛出 Snapshot error；声明为 `restricted`、`invalid` 或 `unavailable` 的 Snapshot 不能被 Runner resolve 为 available。

`ExecutionScope` 继续是生产 Tool 的 trusted scope。Evaluation 只对它做稳定 JSON identity（session IDs、时间边界、max_results），不另造授权实现；scope mismatch 是 hard check。

### ControlledVariant

`ControlledVariant` 保存 variant_id、code commit、provider/model、model parameters、prompt identity、Router/Planner/Runtime config、capability surface、retrieval/index/context config、Evidence/Citation version、budget、execution override 和其他明确的影响配置。所有 mapping 递归 canonicalize、排序键并拒绝敏感 key（API key、Authorization、access token、secret 等）；fingerprint 是 canonical normalized config 的稳定文本 identity，不保存 secret、不调用 secret 环境值、不生成 hash。

`last_stable` baseline 只是当前 M6 stable reference，必须同时 pin code commit、provider/model/config、snapshot 和 scope；报告不得将其称为最优。Candidate diff 使用递归 mapping diff，所有 changed fields 可追溯。

### Suite / Run / Result

- `EvaluationSuite` 有 suite_id/version/kind（Design/Seed、Core、Failure Regression、Calibration Slice）和 `CaseReference[]`；引用 case identity，不复制 Case truth。
- `EvaluationRun` 是单次执行事实，包含 run/case/suite/snapshot/scope/variant/query request identity、terminal status、QueryResult summary、answer artifact reference、trace_id、deterministic checks、operational measurements、时间和 exception summary。
- `EvaluationResult` 只聚合单次 Run 的 check outcome、质量轴 review reference、diagnosability 和 operational facts；不定义总分。
- `repetitions` 只由调用方显式传入，默认 1；每次 Run 独立存储。

## 4. Execution Override

在 `query/contracts.py` 增加 `ExecutionOverride`：

```text
forced_route = null | standard_execution | planned_execution
```

`None` 是默认生产行为。`QueryOrchestrator` 在收到 forced route 时创建 source=`evaluation_override` 的显式 `RouteDecision`，并写入 `router.bypassed`/`router.decision` Trace payload；它不调用 Router。`planned_execution` 仍只调用现有 Planner 一次并把 soft guidance 交给同一 Runtime。`standard_execution` 直接把同一 Runtime request 送入执行。

`RouteDecision.source` 扩展为允许 `evaluation_override`，以便类型上明确“不是真实 Router decision”。Query received 事件写入 safe scope identity 和 override identity；Run metadata 再保存同一份 override。

## 5. Deterministic Checks

每项 Check 都有 name、status（passed/failed/not_applicable/unknown）、severity、message、evidence references。第一版 hard gate 只对显式 contract failures 生效：

- identity：Case version、Snapshot、Scope、Variant、Query request 可解析；
- execution：Query terminal 与 Runtime/Trace terminal 一致，Answer Artifact 与 Finalizer 状态一致；
- provenance：invalid/unresolved citation、scope violation、mixed locator 不能通过；
- observability：Trace 存在且 trace_id 关联正确；incomplete 记录为 diagnosability failed/unknown，不直接改 quality；
- limitations：Tool partial、retrieval truncated、coverage unavailable/partial 在 Result/Trace 中可见；
- override：forced route 在 Query/Trace/Run 中一致，normal run 保持 Router evidence；
- replay：必要的 case/snapshot/scope/variant/query/trace identity 存在。

Operational projection 从 Trace/Runtime 读取 latency、usage、tool count、tool rounds、retrieval partial/truncated、coverage、termination、provider/model/cost（只有可靠时）并与 quality 分开。

## 6. Review / Comparison / Diagnosis

- `EvaluationReview` 支持 `human`、`model_assisted`；质量轴逐轴存档，可带 confidence、notes、disagreement、needs_adjudication。Review packet 只包含 Query、bounded Answer、selected evidence/source projection 和 rubric，不含完整 Trace、hidden reasoning、secret 或全库正文。
- `JudgeAdapter` 是最小 async/sync 可调用 contract；fake judge 可测试。Judge 异常只产出 review failure/needs_adjudication，不能修改 QueryResult 或重跑 Query。
- `PairedComparison` 建立前强制相同 Case version、Snapshot、Scope 和兼容运行条件；记录 Baseline/Candidate variant identity 与 explicit diff。质量 Review 使用随机 A/B label 和 randomization identity，持久化 blind mapping，但质量判断输入不含 baseline/candidate 标签；latency/token/cost 在质量判断后作为 operational diff 加入。
- `FailureDiagnosis` 要求 primary cause、contributing factors、evidence references、trace event references、confidence、status（confirmed/likely/unresolved）和 owner 分类。只有人工或充分结构化证据才能 confirmed；不能用关键词自动确定 root cause。

## 7. Store 与生命周期

`SQLiteEvaluationStore` 使用独立 connection 和 `evaluation_*` 表，至少包括 `evaluation_runs`、`evaluation_results`、`evaluation_reviews`、`evaluation_comparisons`、`evaluation_diagnoses`。表内保存 bounded JSON metadata/reference，不复制 Trace event rows；`trace_id` 是 reference。Store 明确 close 后拒绝读写，重新打开同一路径可恢复。

Composition Root 增加可注入 `evaluation_database_path` / `EvaluationStore`，默认路径与 canonical database 分离。Application close 顺序包含 Evaluation Store；Evaluation DB 创建失败显式暴露，不影响已有 Canonical/Trace ownership。

## 8. CLI / Seed / Calibration

CLI 只解析参数并调用 Application Evaluation facade：

```text
trivae eval cases validate --path ...
trivae eval run --suite ... --variant ... --repeat N --database ... --evaluation-database ...
trivae eval show <run-or-result-id> ...
trivae eval compare --baseline ... --candidate ...
trivae eval regression ...
```

第一批 JSON 只写 stable metadata 和 placeholder snapshot references，按 Design/Seed、Core、Failure Regression、Calibration Slice 分组；真实聊天 case 只在临时工作目录中生成，不进 Git。Calibration 使用临时数据库副本，建立 6–12 个（实际由可靠 Reference 决定）代表性 query；若无可靠 Ground Truth 标记 partial/unknown。

## 9. Risks / rollback

- 外部 Provider 不可用：保留 deterministic fake runtime integration 和真实 Provider blocked 事实，不伪造 baseline。
- 现有 `QueryRequest` 构造为 positional 的旧测试：新字段追加到末尾并保持默认，避免破坏现有调用；强制路径只通过新字段。
- 真实评测对 canonical DB 的只读读取/Conversation commit：先复制 DB 到临时目录；Evaluation Store 始终另一个文件。
- 发现 M1–M6 真实主链 Bug：先保存脱敏 Failure/Trace，最小修复和 regression；不在 Evaluation 中加 fallback。

## 10. Implementation facts

- 设计边界已落在 `src/trivae/evaluation/` 的七个有限模块中；Application 只装配一个 `EvaluationRunner`，Runner 依赖 `TrivaeApplication.query()` 和 `read_trace()` callable，不持有 Runtime/Router/Planner/Tool/Retrieval 实例。
- `TrivaeApplication` 默认创建与 Canonical DB 分离的 `*.evaluation.sqlite3`；测试确认 Evaluation 表不会写入 Canonical Chat DB，close/reopen 可恢复 typed records。
- 真实临时数据副本建立了 `473236` 条消息的 FTS5 Snapshot；8 个 Case、2 个 repeated Run、4 组 forced pair 走过同一生产 Application 链路。真实 Provider 因缺少 API credential 未执行，Scripted Model 结果只作为 integration fact。
- 初次真实校准暴露了一个后验 Check mapping bug：Trace payload 已有 `partial/truncated`，但 Check 只读 timeline limitations。修复保持 Trace append-only，只在 Evaluation analysis layer 读取 payload，并由回归测试和 post-fix calibration 验证。
- 额外 Evidence/Citation fixture smoke 通过了生产 Finalizer、Answer Artifact 和 provenance checks；质量轴仍保持 `not_reviewed`。
