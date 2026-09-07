# Trivae Evaluation Catalog

这里保存 version-controlled 的 Case、Suite 和 Controlled Variant 定义，不保存聊天正文、完整 Trace 或运行结果。

`cases/seed-*.json` 是第一版 Design / Seed contract 样例。它们故意使用 `unavailable` 的占位 Snapshot：真实数据 Case 必须由当前 Canonical Store 建立 Snapshot 后显式 materialize，不能把漂移数据静默绑定到旧 Case。

`variants/last-stable.json` pin 到 M6 完成后的 `cce944d`，表示当前 stable reference，不表示最优方案。`forced-standard.json` 与 `forced-planned.json` 只改变显式 execution override，供同 Case 的 Planner Utility 实验使用。

`variants/deepseek-json-budget-m7.json` 是 M7 provider-boundary candidate `deepseek-json-budget-m7-v2`：只增加显式 JSON completion budget，不能与 `last-stable-m6` 混称为同一 Variant。

运行结果、Review、Comparison 和 Failure Diagnosis 写入独立 SQLite Evaluation Store，不写入 Canonical Chat Store。

## Benchmark 当前状态与收尾入口

`resume-benchmark-v1` 已完成 Development Stage 3：47 条人工裁决 GT，其中 Development 37 条、Calibration 10 条；五 Variant 的历史 Development baseline 共 185 次真实运行。Calibration 不计入正式分母，holdout 尚未生成。

- [历史事实索引](reports/resume-benchmark-v1-fact-index.md)：baseline、post-fix measurement validation 与可引用数字的边界。
- [任务验收记录](../.trellis/tasks/08-30-evaluation-benchmark-v1/validation.md)：真实运行、工程检查和当前停止点。
- 本地人工核验：`data/evaluation/benchmark/closure-review/review.md`（12 条历史 D 答案，六类各两条，优先失败）。它是诊断抽样，全部待人工确认，不能推算总体正确率。

收尾顺序：提交候选代码 → 在干净 worktree 捕获 Environment → provider smoke → 完整 Development 验收 → 人工答案核验与 Gate 3 review → `freeze-final` → 构造并人工审核 holdout → 一次正式运行 → 同版本合并报告。历史结果保持原样，新结果使用独立输出目录。`stage3-final-real` 绑定历史 `7bac928`，禁止直接拿它与冻结后的 holdout 合并。

2026-09-07 旧 key 的单条 Judge smoke 曾返回 `401 / CreditsError / Insufficient balance`；换 key 后，带 OpenCode Go session header 的独立短请求返回 `OK`（98 tokens）。首次 Judge smoke 暴露了 `finish_reason=length`，根因是 Judge 误用 Router/Planner 的 2048 completion budget；现改用独立的 final output budget 后，同一条 smoke 已完成（1 条、9 个 atomic claims，Grounded Claim Rate 0.667、Citation Correctness 0.000），仍保持 `llm_assisted_provisional`，不能当作人工结论。精确余额/配额不由当前兼容 API 暴露，不能据此反推旧的 29 条 Judge 失败原因。Judge 批次包含失败时输出 `status=partial`、`failed` 计数并返回非零退出码，每条保留错误原因；证据读取失败不再用空正文继续评分，已有结果文件损坏时显式拒绝覆盖。人工确认只升级实际检查过的条目。

Gate 3 当前候选版本的 CLI 顺序如下；命令必须在干净 worktree 中执行，每一步都使用独立的 local-only 输出目录，不覆盖历史结果：

```bash
# 在候选最终代码的干净 worktree 中捕获 Environment。
python -m trivae eval benchmark capture-environment \
  --database data/trivae.sqlite3 \
  --benchmark resume-benchmark-v1 \
  --output data/evaluation/benchmark/gate3-candidate-environment.json

# 使用独立 Evaluation SQLite 完整验收 37×5 Development；不要写入历史 baseline 目录。
python -m trivae eval benchmark run \
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

# 完整 Development 验收与人工 review 通过后，才生成 Gate 3 freeze。
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
  --gate2-freeze evaluation/snapshots/resume-benchmark-v1-freeze.json \
  --output data/evaluation/benchmark/gate3-final-freeze.json

python -m trivae eval benchmark seal-holdout \
  --freeze data/evaluation/benchmark/gate3-final-freeze.json \
  --suite data/evaluation/benchmark/holdout/resume-benchmark-holdout-v1.json \
  --cases-dir data/evaluation/benchmark/holdout/cases \
  --output data/evaluation/benchmark/holdout-registration.json

python -m trivae eval benchmark run-holdout \
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

只有 `run-holdout` 返回 completed 且 claim 为 completed，`merge-report` 才会进入；环境或 Variant identity 不一致时保留两个 split，并把 `full` 标成 unavailable。

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
