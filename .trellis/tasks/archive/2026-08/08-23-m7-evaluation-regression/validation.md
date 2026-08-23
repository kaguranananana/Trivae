# M7 Validation

## Measured Facts

- Branch: `codex/m7-evaluation-regression`。
- Base: `cce944d`，包含 M6 的 `639eac5 fix: stabilize DeepSeek tool provenance`。
- 真实数据使用临时副本；Canonical raw data 没有写入。副本 Snapshot 为 `473236` 条消息，时间范围 `1753011800000..1786847688000`，14 个 source，FTS5 rebuild 后索引 `473236` 条。
- Version-controlled catalog 有 10 个 Design/Seed Case，4 个 Suite（Design/Seed、Core、Calibration Slice、Failure Regression）和 3 个 Variant 定义。Seed placeholder Snapshot 明确为 `unavailable`，不会静默绑定漂移数据。
- 临时真实数据 Calibration 建立 8 个代表性候选 Case：simple keyword、trusted session、context expansion、no result、insufficient evidence、partial retrieval、evidence-backed answer、Planner utility。
- Post-fix real-data deterministic rerun：8 个 baseline Run、2 个 repeated Run、4 组 forced-standard/forced-planned paired experiment（8 个 paired Run），共新增 18 个 Run。所有 Query terminal 为 `completed`，Trace completeness 为 `complete`，每次记录了 1 个 Tool call / 1 个 Tool round / 1 次 Retrieval；post-fix 没有 failed deterministic check。
- Scripted/fake model 的 usage 是测试 fixture 产生的零 token 计数，不能解释为 Provider 成本或真实模型 token。

## Deterministic Validation

- Case JSON round-trip、schema version、三态 annotation completeness、reference Snapshot/Scope relationship、Snapshot identity、Variant fingerprint/secret rejection、Suite reference 通过。
- Runner 默认 1 次并支持显式 repetitions；Query exception 原样重新抛出，同时保存单次 Run 和可用 Trace reference。
- forced standard bypasses Router；forced planned 调用已有 Planner；normal route 仍由生产 Router 决定。override 同时出现在 Query/Trace/Run/Variant identity。
- Deterministic checks 独立记录 quality 与 diagnosability；invalid citation、scope mismatch、terminal mismatch、missing Trace 和 hard identity failure 不会被包装成通过。
- Trace partial/truncated 以 canonical payload fact 做后验映射，不改写 append-only Trace。M7 校准初次发现并修复了 limitation mapping 误报，Failure Case 见 `evaluation/regressions/m7-limitation-preservation.json`。
- SQLite Evaluation Store close/reopen 后可读取 Run、Result、Review、Comparison、Diagnosis；Application 测试确认 `evaluation_runs` 不出现在 Canonical Chat DB。
- Review packet 只接受 Query、bounded Answer、selected Source 和 limitations；fake Judge 可注入，Judge 不进入在线 Query，也不接收完整 Trace。
- 另有 1 次基于同一临时真实 Snapshot 的 Evidence/Citation fixture smoke：生产 Finalizer 生成了 Answer Artifact，`answer_artifact_contract`、`finalization_state`、`citation_provenance` 和 `trace_completeness` 均通过；该 Run 仍标记为 `not_reviewed`，不构成质量结论。
- M6 Regression mapping 已落到 `evaluation/regressions/m6-failures.json`；Failure A 的 trusted max bound / illegal limit、Failure B 的 self-contained provenance / mixed locator rejection 由既有 capability/evidence tests 覆盖，Failure C 映射到 router/planner/tool/retrieval/citation/conversation/trace/privacy 分层回归。

## Real-data Calibration / Baseline

- `last-stable-m6` Variant 定义 pin 到 M6 code `cce944d`、`deepseek/deepseek-v4-flash`、M6 prompt/config/retrieval/budget；它是 stable reference，不是“最优 baseline”。
- 当前环境未配置 `DEEPSEEK_API_KEY`，因此没有伪造真实 DeepSeek baseline。实际跑过的是同一临时真实数据、同一生产 Application 链路上的 `scripted-fixture/m7-deterministic-fixture` baseline；它验证了 QueryOrchestrator、Tool、Retrieval、Finalizer、Conversation、Trace 和 Evaluation Store 的可运行性，不提供 Answer quality 结论。
- 由于 Reference findings 在这轮真实数据候选中仍是 `unknown`，没有给出 Finding Correctness、Evidence Completeness、Groundedness、Uncertainty Calibration 或 Relevance 的质量分数。

## Paired Experiment

- 在 4 个适合 Planner Utility 的真实数据 Case 上，只切换 `forced_standard` 与 `forced_planned`；Snapshot、Scope、Scripted model、Prompt identity、Tool、Retrieval、Budget 保持一致。
- 两路 Run 都 terminal `completed`、Trace `complete`、无 deterministic failure；paired comparison 保存了 A/B randomization seed/order、两个 Variant identity、显式 diff 和每个单次 Run reference。
- 本次 scripted answer 相同且没有人工质量 Review，因此不能判定 planned 更好或 Router 更好；这只证明了 paired infrastructure 和 Trace diagnosis 可回溯。

## Failure Regression

- M6 trusted limit：合法输入仍以 trusted maximum 为 schema boundary，非法超限输入仍 `INVALID_ARGUMENT`；没有新增 clamp。
- M6 mixed provenance：self-contained provenance 可进入 Finalizer，混合 Tool Result locator 仍 `UNRESOLVED_MESSAGE_SOURCE`；没有新增 source 猜测。
- M6 Router degraded、Planner failed/continue、Tool contract error、Retrieval partial/unavailable、Citation failure、Conversation commit failure、missing Trace terminal、Trace Store failure、privacy/redaction 均保留原有 owner mapping；不是所有项都升级成昂贵 LLM E2E。

## Known Limitations

- Real Provider baseline blocked by missing credential；model-assisted Judge 也未调用。Scripted model 不代表 DeepSeek 的质量、随机性或成本。
- Seed JSON 使用显式 unavailable Snapshot placeholder，真实执行必须先针对同一 Canonical Snapshot 建立并人工确认 Case；这避免数据漂移带来的伪回归。
- Snapshot 是 deterministic manifest identity，不是全库内容 hash；未识别的正文内容突变仍是已知边界。
- Reference findings 仍以 partial/unknown 为主，没有冻结 Recall/Precision 或 promotion threshold；没有单一总分。
- 当前 CLI 是 local-first 最小入口，没有 UI、队列、调度器、自动 Judge 或统计显著性平台。

## Deferred Work

- 真实 DeepSeek last-stable baseline、真实模型 repeated variance、人工 Review packet 导入和 Provider-backed paired quality review。
- Router Utility 的正式分析：必须先有真实 forced Planner Utility 的质量 Review，再比较正常 Router 是否把有收益 Case 送入 planned。
- 更大规模 Calibration、质量 promotion threshold、统计显著性、Dashboard/API 和远程 Evaluation Store。
