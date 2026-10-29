# Trivae Evaluation Catalog

> **历史评测目录**：本文件保留版本化 Case/Variant、旧 benchmark 与实验操作记录。带日期的 Provider、baseline、Trellis task 状态和命令不是当前默认配置或当前入口；当前评测方法、正式工作库生命周期和质量边界见 [docs/evaluation.md](../docs/evaluation.md)，当前项目进度见 [docs/PROJECT_STATUS.md](../docs/PROJECT_STATUS.md)。

这里保存 version-controlled 的 Case、Suite 和 Controlled Variant 定义，不保存聊天正文、完整 Trace 或运行结果。

Capability Suite v2 的清单、隐私边界、证据审核与真实试运行见 [capability-evaluation-v2.md](../docs/capability-evaluation-v2.md)。其原始题目和参考消息保留在本机私有评测目录，不能从公开目录推断其已人工审核。

## Planner Evaluation 最终工程收口快照（2026-10-03）

该次 P1 canonical Planner 使用官方 DeepSeek `deepseek-flash` / `none`，Router 与共享 Runtime 保持独立 `low`。source_id/mN-K 与 canonical message_id 契约已在真实 SDK schema/prompt 明确；真实日期关系失败保留于 `regressions/archify-temporal-relation.json`，复用既有 Judge 时间投影。

限定八条已暴露Development Case完成16次Standard/Planned E2E、54实际HTTP，无额外repeat。结论为限制使用、保留架构、production routing继续保守，Jev shadow未变；不是答案质量全通过。low/none研究与本轮engineering validation closed，不安排新的付费Planner实验。旧runner/命令属于历史记录，不能据此自动扩样。完整证据见[report.md](../.trellis/tasks/10-02-planner-engineering-closure/report.md)与[ADR](../.trellis/spec/project/technical-decisions/planner-engineering-closure.md)。

## 历史 Provider migration boundary（2026-09-11）

该次迁移期的新执行身份是官方 DeepSeek：`deepseek / deepseek-flash`，base URL 为
`https://api.deepseek.com`，配置使用 generic `TRIVAE_MODEL_*` 变量；本地 key 只放在被 `.gitignore`
忽略的 `.env`。旧的 `opencode-go / deepseek-v4-flash` 仍是历史 benchmark 的身份和元数据，不把新结果
追加到旧目录或旧 Variant。

旧 benchmark 的 185 条 Development runs、v1 holdout 90/90 `SettingsError` 封存事实和 v2 recovery 均保持
原样；v1 holdout 不重跑。新的 DeepSeek Evaluation 必须先建立新的 model/provider identity、environment
manifest、freeze/registration 和独立 output/database，并在执行 worktree 显式传入 `--env-file`。

Provider migration 的能力/传输审计、reasoning_content 回放回归和 A–E bounded smoke 纪律见
[Trellis Provider Migration ADR](../.trellis/spec/project/technical-decisions/provider-migration-deepseek-official.md)。

`cases/seed-*.json` 是第一版 Design / Seed contract 样例。它们故意使用 `unavailable` 的占位 Snapshot：真实数据 Case 必须由当前 Canonical Store 建立 Snapshot 后显式 materialize，不能把漂移数据静默绑定到旧 Case。

`variants/last-stable.json` pin 到 M6 完成后的 `cce944d`，表示生成该文件时选定的 stable reference，不代表当前 main 或最优方案。`forced-standard.json` 与 `forced-planned.json` 只改变显式 execution override，供同 Case 的 Planner Utility 实验使用。

`variants/deepseek-json-budget-m7.json` 是 M7 provider-boundary candidate `deepseek-json-budget-m7-v2`：只增加显式 JSON completion budget，不能与 `last-stable-m6` 混称为同一 Variant。

运行结果、Review、Comparison 和 Failure Diagnosis 写入独立 SQLite Evaluation Store，不写入 Canonical Chat Store。

## `resume-benchmark-v1` 最终状态（2026-09-25）

`resume-benchmark-v1` 的 Gate 4 文档收口已完成，Task 已按 Trellis 流程归档到 `.trellis/tasks/archive/2026-09/08-30-evaluation-benchmark-v1/`。GT 为 47/47 adjudicated（Development 37、Calibration 10），另有 Gate 3 冻结后确认的 Holdout 18；Calibration 不进入 headline denominator。历史 Development quality baseline 固定为 `7bac928` 的 37×5×1=185 runs。Gate 3 的 `8805aa2` Development candidate 是独立候选验收，不替换该 baseline。

v1 Holdout 已按一次性 contract 执行并 sealed：90/90 在设置校验时以 `SettingsError` 结束，原因是冻结临时 worktree 未显式注入主仓库 `.env`。它没有发出 Provider 请求或生成 Answer，因此 holdout quality unavailable；v1 claim、raw/Evaluation/Trace 和报告均保持原样。后续独立 v2 recovery 使用相同 18 个已暴露 Case/GT，90 runs 中 52 completed、38 failed；它只能称为 known/reused holdout recovery validation，不能称 blind、unseen 或 independent generalization。

- Gate 3 candidate Development 已在候选 commit `8805aa2` 的干净 worktree 完成新的 37×5=185 次真实运行；Environment gate 4/4、Gate 2 freeze verification 12/12、Development Case/Variant coverage 185/185 passed。结果写入 `data/evaluation/benchmark/gate3-final-development-real/` 与独立 `data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3`，并已写入 `data/evaluation/benchmark/gate3-final-freeze.json`。
- Gate 3 D-only Tier 2 Judge 写入 `data/evaluation/benchmark/gate3-review/gate3-final-development-judge-d.json`：21 judged、5 skipped、11 failed，状态为 partial；所有成功判定保持 `llm_assisted_provisional`。人工答案 packet `data/evaluation/benchmark/gate3-review/review.md`（12 条、六类各两条）记录了核验结果，但它不等于 claim-level Judge adjudication；生成的 `packet.json` 仍显示 `pending_human_review`。
- Gate 3 人工核验已完成：6 条 `confirmed/confirmed_with_notes`、2 条内容 `fail`、4 条无答案的系统失败；结论只用于诊断，不把失败条目改写成通过。
- Stage 4.0 候选 packet 是 `data/evaluation/benchmark/holdout/review.md`，18 条、六类各 3 条；用户已逐条确认（18/18 confirmed），Case JSON、Suite 和 retrieval query 均在同一目录，正文只存在本地 review packet。

- [最终事实索引](reports/resume-benchmark-v1-fact-index.md)：benchmark 生命周期、Development baseline、v1 sealed Holdout、v2 recovery、可引用数字和限制。
- [归档任务验收记录](../.trellis/tasks/archive/2026-09/08-30-evaluation-benchmark-v1/validation.md)：真实运行、Gate 4 审计和工程检查。
- 本地人工核验：`data/evaluation/benchmark/closure-review/review.md`（历史 D 答案诊断抽样）、`data/evaluation/benchmark/gate3-review/review.md`（候选 Development 的 12 条诊断抽样，已完成核验）和 `data/evaluation/benchmark/holdout/review.md`（18 条冻结后 holdout，18/18 confirmed）。这些材料与最终运行产物分开保存；本次 holdout 没有可用于质量率的已完成答案。

Gate 4 结论：文档与证据收口通过，遗留限制明确保留为 v1 holdout quality unavailable、Tier 2 judge-human agreement 未建立。`full_available=true` 只说明 split identity 可合并，不说明 holdout 质量可用。`stage3-final-real` 仍绑定历史 `7bac928`；所有运行产物保持原样。后续要测 fresh holdout generalization，须另开 Trellis task 并建立新的冻结身份。

2026-09-07 旧 key 的单条 Judge smoke 曾返回 `401 / CreditsError / Insufficient balance`；换 key 后，带 OpenCode Go session header 的独立短请求返回 `OK`（98 tokens）。首次 Judge smoke 暴露了 `finish_reason=length`，根因是 Judge 误用 Router/Planner 的 2048 completion budget；现改用独立的 final output budget 后，同一条 smoke 已完成（1 条、9 个 atomic claims，Grounded Claim Rate 0.667、Citation Correctness 0.000），仍保持 `llm_assisted_provisional`，不能当作人工结论。精确余额/配额不由当前兼容 API 暴露，不能据此反推旧的 29 条 Judge 失败原因。Judge 批次包含失败时输出 `status=partial`、`failed` 计数并返回非零退出码，每条保留错误原因；证据读取失败不再用空正文继续评分，已有结果文件损坏时显式拒绝覆盖。人工确认只升级实际检查过的条目。

2026-09-08 候选 `8805aa2` 的真实 provider smoke（D、1 条 Development case）完成，1 条 raw / 1 条 Trace，随后 Judge 11 个 factual atomic claims 全部得到 provisional 支持；完整 Development 185 条已结束，raw / Evaluation SQLite / Trace 均对齐。当前候选报告的 47 条 failed run 和 126 条 failure artifact 保留 provider、召回、排序、context、coverage、答案生成与 zero-result 事实；Gate 3 人工核验已完成，这些结果仍不能当作 holdout 或最终质量结论。

2026-09-08 Gate 3 freeze 后，`scripts/generate_holdout_candidates.py` 从未使用 GT 消息池构造 18 条 candidate（六类各 3 条），并写入 `data/evaluation/benchmark/holdout/`。Case contract、消息级 split 隔离、holdout 内部 GT 消息不重复和 temporal/zero-result 确定性校验均通过；用户复核 18/18 confirmed 后，`scripts/apply_holdout_adjudication.py` 将 18 条 GT provenance 标为 adjudicated，`seal-holdout` 生成 `data/evaluation/benchmark/holdout-registration.json`。正式运行生成 `data/evaluation/benchmark/holdout-run/` 和 `data/evaluation/benchmark/gate3-final-freeze-holdout-run.json`：90/90 run 为 `exception`，异常类型为 `SettingsError`，没有 provider 请求、答案或质量指标。该事实已按 v1 一次性运行纪律封存，未删除 claim、未换目录重跑。

2026-09-08 final merge：`data/evaluation/benchmark/final-report/` 已生成，raw 记录 275 条（Development 185 + holdout 90），五个 Variant 各 55 条，`full_available=true` 仅表示两 split 的冻结 Environment/Variant identity 一致；holdout split 的质量矩阵为空，不能把 full 的结构性合并当作 holdout 质量结论。holdout 的直接根因是运行命令从冻结临时 worktree 启动，CLI 默认只在当前目录寻找 `.env`，而该 worktree 没有 `.env`；主仓库 `.env` 存在，但一次性 claim 已 terminal，按设计不允许补注入后重跑 v1。

2026-09-08 holdout v2 recovery validation：用户明确要求复用原 18 条 holdout Case、GT 和 18/18 人工核验结果。为避免覆盖 v1 claim，使用独立的 `gate3-final-freeze-v2-recovery.json`、`holdout-registration-v2-recovery.json`、`holdout-v2-recovery-run/` 和 `holdout-v2-recovery-evaluation.sqlite3`，在同一冻结 commit `8805aa2` 上通过显式 `--env-file` 完成新的 90 次运行。raw / Evaluation SQLite / Trace 均为 90 条；52 条 completed、38 条 failed，failure artifact 58 条。`final-report-v2-recovery/` 的 `full_available=true` 只表示 Development/Recovery split identity 一致；这轮是已暴露 Case 的 recovery validation，不是全新 blind/generalization holdout，v1 产物保持不变。

Gate 3 收尾 CLI 记录如下；这组流程已经执行完毕。若用于新一轮实验，必须先在实际执行 worktree 显式注入 provider 配置，并创建新的冻结/登记身份；不得对当前 v1 claim 重跑：

```bash
# 在候选最终代码的干净 worktree 中捕获 Environment。
python -m trivae eval benchmark capture-environment \
  --database data/trivae.sqlite3 \
  --benchmark resume-benchmark-v1 \
  --output data/evaluation/benchmark/gate3-candidate-environment.json

# 使用独立 Evaluation SQLite 完整验收 37×5 Development；不要写入历史 baseline 目录。
# 如果命令从冻结 worktree 启动，--env-file 必须指向 worktree 外可读取的主工作区 `.env`。
python -m trivae eval --env-file /path/to/main-repository/.env benchmark run \
  --database data/trivae.sqlite3 \
  --evaluation-database data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3 \
  --manifest data/evaluation/benchmark/gate3-candidate-environment.json \
  --suite evaluation/suites/resume-benchmark-dev-v1.json \
  --cases-dir evaluation/cases/benchmark/dev \
  --variant evaluation/variants/bench-lexical-only-v1.json \
  --variant evaluation/variants/bench-lexical-semantic-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-tool-v1.json \
  --variant evaluation/variants/bench-full-system-v1.json \
  --output-dir data/evaluation/benchmark/gate3-final-development-real

# 完整 Development 验收与人工 review 通过后生成 Gate 3 freeze；当前冻结文件已存在。
python -m trivae eval benchmark freeze-final \
  --database data/trivae.sqlite3 \
  --manifest data/evaluation/benchmark/gate3-candidate-environment.json \
  --suite evaluation/suites/resume-benchmark-dev-v1.json \
  --cases-dir evaluation/cases/benchmark/dev \
  --variant evaluation/variants/bench-lexical-only-v1.json \
  --variant evaluation/variants/bench-lexical-semantic-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-tool-v1.json \
  --variant evaluation/variants/bench-full-system-v1.json \
  --development-dir data/evaluation/benchmark/gate3-final-development-real \
  --gate2-freeze evaluation/snapshots/resume-benchmark-v1-freeze.json \
  --output data/evaluation/benchmark/gate3-final-freeze.json

python -m trivae eval benchmark seal-holdout \
  --freeze data/evaluation/benchmark/gate3-final-freeze.json \
  --suite data/evaluation/benchmark/holdout/resume-benchmark-holdout-v1.json \
  --cases-dir data/evaluation/benchmark/holdout/cases \
  --output data/evaluation/benchmark/holdout-registration.json

# 冻结 worktree 同样显式注入 Provider 配置，避免把缺少 `.env` 误判成 Provider/网络失败。
python -m trivae eval --env-file /path/to/main-repository/.env benchmark run-holdout \
  --database data/trivae.sqlite3 \
  --evaluation-database data/evaluation/benchmark/holdout-evaluation.sqlite3 \
  --manifest data/evaluation/benchmark/gate3-candidate-environment.json \
  --freeze data/evaluation/benchmark/gate3-final-freeze.json \
  --registration data/evaluation/benchmark/holdout-registration.json \
  --suite data/evaluation/benchmark/holdout/resume-benchmark-holdout-v1.json \
  --cases-dir data/evaluation/benchmark/holdout/cases \
  --variant evaluation/variants/bench-lexical-only-v1.json \
  --variant evaluation/variants/bench-lexical-semantic-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-v1.json \
  --variant evaluation/variants/bench-semantic-ctx-tool-v1.json \
  --variant evaluation/variants/bench-full-system-v1.json \
  --output-dir data/evaluation/benchmark/holdout-run

python -m trivae eval benchmark merge-report \
  --development-dir data/evaluation/benchmark/gate3-final-development-real \
  --holdout-dir data/evaluation/benchmark/holdout-run \
  --freeze data/evaluation/benchmark/gate3-final-freeze.json \
  --output-dir data/evaluation/benchmark/final-report
```

只有 `run-holdout` 返回 completed 且 claim 为 completed，`merge-report` 才会进入；本轮 claim 为 completed，但 90 条 holdout run 均是 `SettingsError` exception，故报告只保留这一封存事实。环境或 Variant identity 不一致时保留两个 split，并把 `full` 标成 unavailable。

当前 benchmark CLI 会在 `run` / `run-holdout` 创建 Application 前预检 Provider 配置；从冻结 worktree 启动时必须把 `--env-file` 放在 `eval` 后、`benchmark` 前，并指向 worktree 外的可读配置文件。缺少配置会在首个 Case 前显式失败，不会生成逐 Case 的重复异常记录。

## Stage A Agent Tool Selection

`diagnostics/agent-tool-selection-stage-a-v1.json` 是新增的 Agent Retrieval Behavior diagnostic
catalog。它把 lexical-dominant、semantic-dominant、weak-result continuation、no-result 和
semantic unavailable/stale 分成可追踪 Case category，并明确 preferred tool 只是
`diagnostic_contract_expectation`，不是自动 `human_verified` ground truth。

现有 `EvaluationRunner` 的每次 Run 继续通过生产 Query 链路执行，并在 Evaluation Store 的
bounded projection 中记录 `available_capabilities`、`first_selected_tool`、完整
`tool_sequence`、`tool_call_count`、`tool_rounds`、tool errors、latency、usage 和 Trace
completeness。paired lexical-vs-semantic retrieval evaluation 保持独立；两者都不保存真实聊天
正文或 hidden chain-of-thought。

## Stage C Structured SQL Tool Behavior

`diagnostics/agent-tool-selection-stage-c-v1.json` 是 Stage C 的 structured retrieval diagnostic
catalog。它覆盖 deterministic count、GROUP BY/sender aggregation、time range、schema→SQL、zero
rows/SQL error 和 scope enforcement。`get_schema` 与 `execute_sql` 的 preferred sequence 只表示
version-controlled contract expectation；实际 Agent sequence、tool rounds、returned rows、
truncation、coverage、errors、Evidence/Citation、latency 和 usage 由同一 Evaluation projection
记录，不能自动标成 `human_verified` 或自然语言质量结论。

`get_schema` 返回 public physical canonical schema；`execute_sql` 只执行一条 bounded read-only
statement。trusted `ExecutionScope` 在 adapter/SQLite driver boundary 强制，不由模型 SQL 的
`WHERE` 决定；zero rows 是正常结果，超过 `max_rows` 保留 `truncated`。SQL structured evidence
通过现有 `ToolResultRecord`/`StructuredSource` finalizer 校验，不能拼接 message citation。

## Six-tool comprehensive Agent diagnostic

`diagnostics/agent-tool-selection-comprehensive-v1.json` 是六个 canonical Agent-facing Tool 同时
暴露时的综合 diagnostic catalog，包含 14 个 case，覆盖 lexical/semantic、context deepening、成员
候选、COUNT/GROUP BY、mixed retrieval + SQL、no-result、zero rows 和 scope-sensitive execution。
`search_messages` 只在 catalog 的 compatibility metadata 中出现，不进入 `available_tools`。

这个 catalog 的 `preferred_first_tools`、`allowed_sequences` 和 `deterministic_contract` 是
version-controlled diagnostic expectation，不是唯一正确序列，也不生成 `human_verified`。自然
语言答案正确性、证据充分性和“是否需要下一次 Tool call”继续交给 LLM-assisted 或人工 review。

综合 Run 仍使用现有 Query → Runtime → CapabilityRegistry → ToolResultRecord → Evidence/Citation
→ Finalizer → Trace → Evaluation 链路。Evaluation 的 bounded operational projection 额外保存
`tool_result_facts`、`evidence_count`、`citation_count`、`citation_state`、`finalization_state` 和
`scope_enforcement`；它只从公开 Trace terminal facts 派生，不复制原始 Trace、聊天正文、SQL rows
或 hidden chain-of-thought。

Deterministic regression 入口：

```bash
.venv/bin/pytest -q tests/test_comprehensive_tool_diagnostics.py
.venv/bin/pytest -q
```

真实 Provider smoke 只保存 case category、实际 Tool sequence、call/round、bounded result facts、
Evidence/Citation/Finalizer 状态、Trace ID、latency、usage 和 Failure Case。单次重复 Tool call、
Provider transport error 或 Finalizer rejection 都先进入诊断记录，不自动升级为 Runtime blocker，
也不通过 fallback 或 citation repair 掩盖。

Stage C 的最小验证入口：

```bash
.venv/bin/pytest -q tests/test_stage_c_tools.py
.venv/bin/pytest -q
```

真实 Provider smoke 只保存 query category、tool sequence、Trace/usage/latency 元数据；真实
聊天正文、完整 SQL 结果和 credentials 不进入仓库。

## Real snapshot and semantic smoke

当前 Canonical Store 可以通过 Application facade materialize 为不含聊天正文的 Snapshot manifest：

```bash
python -m trivae eval snapshot \
  --database data/trivae.sqlite3 \
  --output evaluation/snapshots/<snapshot-name>.json
```

该 manifest 记录 schema、source metadata、消息数量、时间范围和 lexical index presence；它不替代人工 Finding annotation。若 Snapshot 需要进入长期 Core / Calibration Suite，应在固定 Snapshot 上补充逐 Finding 的 reference evidence，并显式记录 annotation completeness 与 provenance。真实 Snapshot 只应保留在受控本地/评测环境，不把私有 source metadata 或聊天正文提交到仓库。

Semantic derived index 的状态和 rebuild 不隐式发生：

```bash
python -m trivae semantic status --database data/trivae.sqlite3
python -m trivae semantic rebuild --database data/trivae.sqlite3
python -m trivae semantic smoke \
  --database data/trivae.sqlite3 \
  --query "大家为什么觉得一些 Agent 框架太重？"
```

`semantic smoke` 默认只输出 candidate locator、score、coverage、latency 和 index identity，不输出消息正文；`--rebuild` 可显式把 rebuild 与一次 query 放在同一 smoke 中。索引缺失、stale、模型加载失败和 retrieval partial 都保持可见，不改写成 lexical success。

`semantic status`、`rebuild` 和 `smoke` 的 index projection 还包含 `operational_guidance`：missing/stale/failed/partial 指向显式 rebuild，building 指向 status polling，completed 指向 bounded smoke；CLI 不会自动执行建议命令。

## Retrieval relevance annotation

真实 lexical/semantic module comparison 使用固定 query set 与两个 retrieval-only Controlled Variant：

```bash
trivae eval retrieval-packet \
  --database data/trivae.sqlite3 \
  --queries evaluation/retrieval/semantic-vs-lexical-provisional-v1.json \
  --lexical-variant evaluation/variants/lexical-only-retrieval-control-v1.json \
  --semantic-variant evaluation/variants/semantic-only-retrieval-candidate-v1.json \
  --output-dir data/evaluation/semantic-vs-lexical-provisional-v1
```

输出目录已由 `.gitignore` 排除。`blind-packet.json` 含真实候选正文和 bounded context，但隐藏 retrieval source、rank、score 与 variant；`sealed-metadata.json` 保存 canonical identity、两种方法的 rank/score、expanded IDs 和运行诊断。两者都不得 commit 或 push。

配置好现有 OpenAI-compatible 模型环境后，可进行 LLM-assisted 初筛：

```bash
trivae eval retrieval-annotate \
  --packet data/evaluation/semantic-vs-lexical-provisional-v1/blind-packet.json \
  --sealed data/evaluation/semantic-vs-lexical-provisional-v1/sealed-metadata.json \
  --output-dir data/evaluation/semantic-vs-lexical-provisional-v1
```

`annotations.json` 中的每条自动标签固定为 `llm_assisted_provisional`，并带 confidence/notes；它不是 human ground truth。`audit-queue.json` 优先列出 uncertain、低 confidence、partial relevance、单方法前排、排名冲突和影响质量指标的 positive label。人工复核时同时查看 blind packet 和 audit queue，修改标签/notes，并仅把真实检查过的条目标记为 `human_verified`。只复核部分条目时把 annotation set 的 `annotator_type` 改为 `mixed`；全部条目复核且全部 verification status 都是 `human_verified` 后，才改为 `human`。

指标入口为：

```bash
trivae eval retrieval-metrics \
  --sealed data/evaluation/semantic-vs-lexical-provisional-v1/sealed-metadata.json \
  --annotations data/evaluation/semantic-vs-lexical-provisional-v1/annotations.json \
  --output data/evaluation/semantic-vs-lexical-provisional-v1/metrics.json
```

报告支持 Precision@k、merged-candidate-pool Recall@k、MRR、Top-k hit/success、relevant message coverage 与独立 partial relevant coverage。missing/uncertain label 会令依赖它的指标 `unavailable`，不会被当作 negative；没有 corpus-exhaustive reference 时 corpus Recall 始终 unavailable。由自动标签产生的所有数字都明确标记为 `llm_assisted_provisional`，不能作为 production gate。

## Router Jev paired diagnostic

Router Jev 是独立于 Planner / Runtime 主模型的实验 Provider。Router 的确定性 Rule 先运行；只有 ambiguous case 才会调用现有 LLM、Jev 或两者并行。默认 `shadow` 保留现有 LLM 作为唯一主决定，Jev 只产生隔离的诊断结果。

实验配置只从环境变量读取：

```dotenv
OPENROUTER_API_KEY=
TRIVIAE_ROUTER_JEV_ENABLED=true
TRIVIAE_ROUTER_JEV_MODEL=typesafe/jev-1.13
TRIVIAE_ROUTER_JEV_ENDPOINT=https://openrouter.ai/api/alpha/decisions
TRIVIAE_ROUTER_JEV_MODE=shadow
```

这些变量不改写 `TRIVIAE_MODEL_*`；后者仍供 Planner、Runtime 和 Answer Generation 使用。Router 评估命令在同一 Router context 上配对调用现有 LLM 与 Jev，只将 route、confidence、probabilities、usage/cost、latency、错误码和 case metadata 写入 create-only 报告，不保存 query、密钥或原始 Provider response：

```bash
uv run trivae eval --env-file .env router-jev \
  --cases evaluation/router-jev/cases-v1.json \
  --repeat 3 \
  --output data/evaluation/router-jev/after-key-rotation.json
```

当前 versioned diagnostic 集包含 16 个候选 Case，其中 13 个通过 Rule gate 进入 ambiguous Provider 分支，3 个由确定性 Rule 处理；16 个 route hypothesis 后来均经人工裁决，最终 8 standard / 8 planned。它用于发现分歧和失败模式，其 route 标签不是答案 GT。即使 Provider route accuracy 较高，也不能单独说明 Planner 带来了端到端收益。当前实现与 route 实验见 [Router Jev provider experiment](../.trellis/spec/project/technical-decisions/router-jev-provider-experiment.md) 和 [Jev 任务报告](../.trellis/tasks/archive/2026-09/09-25-openrouter-jev-router/experiment-report.md)。

## Planner Utility Development experiment

本轮 forced-path 实验使用 [standard Variant](variants/planner-utility-standard-20260925.json) 和 [planned Variant](variants/planner-utility-planned-20260925.json)。两份配置仅 `execution_override.forced_route` 不同，均 pin 冻结执行 commit、官方 DeepSeek、当前生产 Tool/Runtime/Retrieval、Snapshot、Evidence/Citation 与 Evaluation identity。旧 `forced-standard.json` / `forced-planned.json` 属于旧 M6 身份，不能代替本轮 Variant。

运行前从实际 execution worktree 显式传 `--env-file` 指向主仓库 `.env`，校验 Provider、数据库、Snapshot/索引、scope、Tool 与输出/Evaluation DB create-only。`--paired-by-case` 让同一 Case 的 standard→planned 紧邻运行；它不改变 Suite/Variant 身份，也不提供重试。独立 smoke 4×2 不进入正式分母；正式 37×2×1 的 raw、Evaluation 和 Trace 各 74；选定 6 Case 的 targeted repeat 共 24 run，放在另一组输出与 Evaluation DB，不并入主统计。私有 query、答案与 review packet 只保存在被 Git 忽略的本地 `data/evaluation/planner-utility/`。

Development 自动指标给出 paired better 6 / same 26 / worse 5；context recovery 0/3→2/3、evidence recall 48/67→57/67，同时 valid answer 36/37→34/37、verified zero 3/4→0/4；planned 平均端到端多 8.54 秒、实测 token 多 33.62%，货币 cost unavailable。`same` 只表示可比自动指标相同，不能证明答案等价；Judge 未执行，答案差异待人工裁决。16 条 Router 诊断 Case 没有绑定答案 GT，不能直接证明它们的 8 个 planned 标签有 utility。详见 [Planner Utility 报告](../.trellis/tasks/archive/2026-09/09-25-planner-utility-evaluation/experiment-report.md)。生产 Router 保持 `shadow`。

## Planner-specific Utility → Router Utility Development（2026-09-26）

新增 [Planner Utility Suite](suites/planner-utility-development-v1.json) 与 [Case/裁决说明](planner-utility/README.md)：15 条已暴露 Development Case 包括 4 条新建 CaseBundle，覆盖 dependent/context recovery 候选、verified zero 与 direct/lexical/semantic/count/ranking/aggregation/summary/large-window 控制例。新结构化 GT 是固定 Snapshot 上的确定性 SQL 事实，人工答案和 treatment utility 尚未完成裁决；不得把 workload candidate 直接写成 expected route。

`dev-zero-empty-3` 的三次旧 Trace 显示 Planned 已获得 complete/zero 的时间窗结果，却继续 SQL 聚合；Host 把零计数统计行当候选事实，拒绝 `no_result`。版本化 [Failure Case](regressions/planner-zero-result-v1.json) 及 [根因记录](../.trellis/spec/project/problems/planner-zero-result.md) 区分此 Evidence qualification 问题与 `dev-zero-empty-1/2` 的 SQL-first / 缺少 retrieval 正证明。当前代码进行了最小修复，历史结果未改写。

针对性新实验已执行 5 对 `dev-zero-empty-3`：第一冻结版本 Planned 2/3 verified-zero，唯一失败为 SQL-first 缺少完整空检索；第二冻结版本 Planned 2/2 verified-zero，但其中一次 Planner `provider_length` 截断并降级，只有一次成功 Plan 的有效观察。因此聚合统计行误拒已修，SQL-first 风险的稳定消失尚未证实。`dev-context-archify` 新两对为 planned worse/same 的自动指标方向，与历史 better/better/same 冲突；它仍只是待人工裁决的 conditional utility candidate。详见[本轮任务报告](../.trellis/tasks/archive/2026-09/09-26-planner-router-utility-closure/experiment-report.md)，不据此提升 Jev。

Benchmark 的 `--paired-order counterbalanced` 以 AB/BA 交替次序运行同 Case 两路，顺序及 unit 序列在首个请求前保存至 create-only `execution-order.json`，Suite/Case identity 不变；默认 `fixed` 仍是旧 standard→planned 顺序。`scripts/run_router_utility_jev.py` 只执行 Rule gate 与 Jev route，`scripts/analyze_router_utility.py` 离线连接 forced treatment、Evaluation DB、Jev route 和人工 utility 裁决，分别报告两种误路由与质量维度。当前所有 utility 标签均 pending；生产 Jev 继续 `shadow`。大规模正式实验只准备，不在本轮成本预算内自动运行。

本轮针对性实测 7 对 forced treatment、2 次 Jev Decisions，共 47 次付费 Provider invocation；14 条 raw/Evaluation/Trace 身份对齐，Jev 两次均可用且返回 standard。两份 Router Utility 结果均成功生成，但人工 treatment label 仍为 pending，direction 保持 `unadjudicated`。完整账本及 Provider 真实 usage 保存在 ignored 本地实验目录；缺失的 DeepSeek cost 不推算。15 Case 全 Suite 若各跑 1 对并各做 1 次 Jev route，按两路各最多 8 个 Runtime turn、Planned 1 个 Planner request 和每 Case 最多 1 个 Jev request，理论上限为 **270 次**，不在本轮 60 次 ceiling 内。

### 2026-09-27 后续状态

上文保留的是 2026-09-26 归档阶段的测量状态。随后 15 道人工 review 已完成：6 道当前 v2 Case 按真实 Snapshot、Variant 与 run ID 正式裁决，9 道旧 Variant 只记历史判断。当前 v2 为 `planned_beneficial=0`、`standard_preferable=2`、`indifferent=4`、`uncertain=0`；跨版本 15 道人工观察为 `0 / 4 / 11 / 0`，不能当成单一 v2 统计。四个新增 Case 的 GT applicability 均人工 Accept。

后续 targeted v2 共 16 条当前 raw run，与 16 条 Evaluation run、16 条 Evaluation result 和 16 条 canonical Trace 对齐；覆盖 6 道 Case 的 8 组 paired observation。本地 9 份 raw batch 共 22 条 run。按 Trace request-start 和两条 Jev Decisions observation 重新构建的累计账本为 74 次 invocation：Planner 11、Runtime 61、Existing Router LLM 0、Jev 2。Jev 实际 returned cost 为 0.000050904；DeepSeek cost unavailable。账本事件内容与 ignored 本地 `provider-ledger-final-after-all-pu.json` 一致。

截至 v2 冻结时，`Jev` production 为 `shadow`，没有 Holdout 实验或 `planned_beneficial`；当时的下一阶段计划是先查 dependent 与 `dev-context-archify` Trace，再执行 targeted v3，不启动 15 Case 全量运行。该 v3 后续状态见下。

### 2026-09-27 Planner Utility v3 closeout

v3 已在 pin `70593fd` 上完成 6 组 paired observation、12 个 run；Environment gate、唯一 forced-route Variant diff 与 Snapshot identity 均通过，raw/Evaluation/result/Trace 身份 12/12/12/12 对齐。实际调用为 44/102（Planner 6、Runtime 38、Jev 0）；v3 DeepSeek monetary cost unavailable。相比 v2 冻结时 ledger 74 次，本地累计为 118 次。

assistant review 在 `dev-context-archify` 两组重复中均发现 Planned 恢复关键使用反馈；dependent 两组仍由 Standard 给出更完整 firsthand context；aggregation 与 zero-result controls 无退化。这形成一个狭窄的 case-level Router Classification supervision candidate，不支持 treatment-wide utility 或 generalization。正式 v2 adjudication 保持不变，Jev 仍为 `shadow`，未访问 Holdout。详见 [Planner Utility v3 validation](../.trellis/tasks/archive/2026-09/09-27-planner-retrieval-degradation-v3/validation.md)。

## CJK bigram v2 单变量检索实验（2026-10-20）

[独立实验报告](experiments/cjk-bigram-v1/report.md)使用809,850条canonical及13,985条forward occurrence、64个固定字面查询，对照原文unicode61与当前v2。44条中文/混排查询的全深度micro覆盖2,853/89,346→89,340/89,346，Recall@10 macro10.166%→14.676%；同时记录339个mixed字面额外匹配、3条前十退化、单字限制和性能开销。LIKE/NUL Oracle修订前结果保留但不用于claim。真实Flash为7完整配对及1中断，不能宣称稳定Agent质量提升。详见报告的分母、Oracle和HTTP计数限制。
