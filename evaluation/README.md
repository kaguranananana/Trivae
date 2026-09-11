# Trivae Evaluation Catalog

这里保存 version-controlled 的 Case、Suite 和 Controlled Variant 定义，不保存聊天正文、完整 Trace 或运行结果。

## Provider migration boundary（2026-09-11）

当前新执行身份是官方 DeepSeek：`deepseek / deepseek-flash`，base URL 为
`https://api.deepseek.com`，配置使用 generic `TRIVAE_MODEL_*` 变量；本地 key 只放在被 `.gitignore`
忽略的 `.env`。旧的 `opencode-go / deepseek-v4-flash` 仍是历史 benchmark 的身份和元数据，不把新结果
追加到旧目录或旧 Variant。

旧 benchmark 的 185 条 Development runs、v1 holdout 90/90 `SettingsError` 封存事实和 v2 recovery 均保持
原样；v1 holdout 不重跑。新的 DeepSeek Evaluation 必须先建立新的 model/provider identity、environment
manifest、freeze/registration 和独立 output/database，并在执行 worktree 显式传入 `--env-file`。

Provider migration 的能力/传输审计、reasoning_content 回放回归和 A–E bounded smoke 纪律见
[Trellis Provider Migration ADR](../.trellis/spec/project/technical-decisions/provider-migration-deepseek-official.md)。

`cases/seed-*.json` 是第一版 Design / Seed contract 样例。它们故意使用 `unavailable` 的占位 Snapshot：真实数据 Case 必须由当前 Canonical Store 建立 Snapshot 后显式 materialize，不能把漂移数据静默绑定到旧 Case。

`variants/last-stable.json` pin 到 M6 完成后的 `cce944d`，表示当前 stable reference，不表示最优方案。`forced-standard.json` 与 `forced-planned.json` 只改变显式 execution override，供同 Case 的 Planner Utility 实验使用。

`variants/deepseek-json-budget-m7.json` 是 M7 provider-boundary candidate `deepseek-json-budget-m7-v2`：只增加显式 JSON completion budget，不能与 `last-stable-m6` 混称为同一 Variant。

运行结果、Review、Comparison 和 Failure Diagnosis 写入独立 SQLite Evaluation Store，不写入 Canonical Chat Store。

## Benchmark 当前状态与收尾入口

`resume-benchmark-v1` 已完成 Development Stage 3：47 条人工裁决 GT，其中 Development 37 条、Calibration 10 条；五 Variant 的历史 Development baseline 共 185 次真实运行。Calibration 不计入正式分母；Gate 3 已冻结候选 commit `8805aa2`，冻结后 18 条 holdout 已全部人工确认、登记并完成一次性运行，随后生成了最终合并报告。该次运行因从冻结临时 worktree 启动时未注入主仓库 `.env`，90 个 holdout run 全部在 Query 设置校验阶段以 `SettingsError` 结束；因此 holdout 质量指标不可用，不能据此宣称 v1 的 holdout 质量。

- Gate 3 candidate Development 已在候选 commit `8805aa2` 的干净 worktree 完成新的 37×5=185 次真实运行；Environment gate 4/4、Gate 2 freeze verification 12/12、Development Case/Variant coverage 185/185 passed。结果写入 `data/evaluation/benchmark/gate3-final-development-real/` 与独立 `data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3`，并已写入 `data/evaluation/benchmark/gate3-final-freeze.json`。
- 本轮 D-only Tier 2 Judge 写入 `data/evaluation/benchmark/gate3-review/gate3-final-development-judge-d.json`：21 judged、5 skipped、11 failed，状态为 partial；所有成功判定保持 `llm_assisted_provisional`。人工 packet `data/evaluation/benchmark/gate3-review/review.md`（12 条、六类各两条）已完成核验。
- Gate 3 人工核验已完成：6 条 `confirmed/confirmed_with_notes`、2 条内容 `fail`、4 条无答案的系统失败；结论只用于诊断，不把失败条目改写成通过。
- Stage 4.0 候选 packet 是 `data/evaluation/benchmark/holdout/review.md`，18 条、六类各 3 条；用户已逐条确认（18/18 confirmed），Case JSON、Suite 和 retrieval query 均在同一目录，正文只存在本地 review packet。

- [历史事实索引](reports/resume-benchmark-v1-fact-index.md)：baseline、post-fix measurement validation 与可引用数字的边界。
- [任务验收记录](../.trellis/tasks/08-30-evaluation-benchmark-v1/validation.md)：真实运行、工程检查和当前停止点。
- 本地人工核验：`data/evaluation/benchmark/closure-review/review.md`（历史 D 答案诊断抽样）、`data/evaluation/benchmark/gate3-review/review.md`（候选 Development 的 12 条诊断抽样，已完成核验）和 `data/evaluation/benchmark/holdout/review.md`（18 条冻结后 holdout，18/18 confirmed）。这些材料与最终运行产物分开保存；本次 holdout 没有可用于质量率的已完成答案。

当前收尾状态：人工审核、adjudication、`seal-holdout`、同一冻结 commit 的一次性运行和同版本合并均已完成。历史结果保持原样；登记、holdout 运行和 final report 使用独立输出目录。`stage3-final-real` 绑定历史 `7bac928`，禁止直接拿它与冻结后的 holdout 合并。

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
