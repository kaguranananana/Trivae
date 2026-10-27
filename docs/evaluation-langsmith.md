# Trivae 长期评测与 LangSmith

Trivae 负责执行、Snapshot 校验、确定性检查和本地记录；LangSmith 只用于查看外部导入的实验、独立评分和复核。正常查询与 `eval run` 不访问 LangSmith；只有显式执行 `langsmith-sync`、`langsmith-resolve` 或 `langsmith-review-sync` 才联网。OpenAI Agents SDK 原有的 tracing 禁用保持不变，诊断使用 Trivae 自己的 Trace。

官方参考：[导入外部实验](https://docs.langchain.com/langsmith/upload-existing-experiments)、[实验 Run 查询](https://reference.langchain.com/python/langsmith/_openapi_client/resources/datasets/experiment_runs/ExperimentRunsResource/query)、[Feedback](https://reference.langchain.com/python/langsmith/client/Client/create_feedback)。对照 `langsmith` 0.14.13 的 SDK 实际接口并用其回读验收；产品代码使用对应的官方 HTTP API 和已有 `httpx`，无需新增 SDK 依赖。没有引入 LangChain、LangGraph 或第二个运行时。

## 准备

```bash
uv sync
# 配置 LANGSMITH_API_KEY：已有 shell 环境或当前目录的 .env 均可；不要打印密钥。
# 可选 LANGSMITH_ENDPOINT，默认 https://api.smith.langchain.com。
trivae eval --help
```

导入按命令选择的题目、参考信息、答案、各维度评分及结构化 Trace 的阶段/操作/状态/耗时。`--metadata-only` 不上传问题、参考和答案；`--content` 可指定单独准备的文本 JSON。不会上传 `.env`、API Key、SQLite 文件或 Trace event 的原始 payload。只检查显式配置的密钥是否出现在导出内容中，不声称自动识别所有敏感文本。LangSmith 不可用只会使同步命令失败，不改变已经保存的本地评测结果。

## 两套集合和历史身份

- `regression-v1.json`：3 条 Development 题，基于已有直接回复遗漏、修复和验证证据。它不是全部历史问题的机械合集；低成本确定性回归仍在现有测试中。
- `capability-v1.json`：6 条已暴露 Development 题，覆盖跨群引用、时间窗、综合与错误推断。旧参考证据有人工裁定，但只适用于原 Snapshot，且不保证完整枚举。
- `curated-v1.json`：每题的目的、加入原因、历史证据和审核边界。

原 Development 37、Calibration 10 和已暴露 Holdout 18 保持原状；后者不是新的盲测。两套集合引用原 Case 版本，不改变原 benchmark 或旧实验。原题和当前数据 Snapshot 不一致时禁止直接重跑并冒充同一实验；应生成新候选、重新核验参考证据。

## 冻结真实数据及生成候选题

SQLite backup 保存 Canonical（包含词法索引）和独立语义索引的真实文件。两者分别备份后校验 Canonical、词法和语义修订号，以及语义索引的数据库身份；不一致即失败。必须保留整个主快照目录，后续实验使用工作副本：Application 会在工作库写入会话和 Trace，不能直接运行主快照。

```bash
# 输出目录必须不存在。语义索引应与所用 Canonical 同修订；仅词法实验可不传语义索引。
trivae eval freeze-data --database data/trivae.sqlite3 \
  --semantic-index data/trivae.semantic.sqlite3 --output-dir data/evaluation/frozen-new
trivae eval clone-data --manifest data/evaluation/frozen-new/freeze.json \
  --output-dir data/evaluation/work-baseline
trivae eval clone-data --manifest data/evaluation/frozen-new/freeze.json \
  --output-dir data/evaluation/work-candidate

# 在新快照上保留问题，但不把旧 Ground Truth 移花接木。
trivae eval suite-candidates --suite evaluation/suites/regression-v1.json \
  --cases-dir evaluation/cases/benchmark/dev --freeze-manifest data/evaluation/frozen-new/freeze.json \
  --output-dir data/evaluation/new-regression-candidates
trivae eval cases validate data/evaluation/new-regression-candidates/cases
```

候选 Case 有新的 `candidate-*` 身份，`review:pending`，参考 Findings 被清空；仍可做探索运行，但不能据此声称答案准确。能力集同样可将 `--suite` 换成 `capability-v1.json`。手工或 Agent 可以收集参考证据，记录来源与方法；只有实际完成核验的证据才可标记 `adjudicated=true`。把审核结果保存为新 Case 版本，再新建 Suite 版本引用它们，保留候选和旧 Suite。目录按用户需要放在 Git 忽略的 `data/evaluation/`，或经审阅后放进版本库；不要提交数据库文件。

```bash
trivae eval cases new-version --source data/evaluation/new-regression-candidates/cases/candidate-dev-context-archify.json \
  --output data/evaluation/reviewed-cases/candidate-dev-context-archify-v2.json
trivae eval cases validate data/evaluation/reviewed-cases
```

`new-version` 为创建型操作，不覆盖原文件，并将 Case provenance 标为待审核。若用 `--snapshot <freeze.json>` 直接创建新版本，旧参考证据会被清空。新增 Findings 时，Evidence/Finding 的 snapshot_id 和 scope_identity 必须与 Case 一致；原有 ReviewPolicy 和 ReferenceProvenance 契约见现存 Case JSON。人工核验后明确写入真实来源、核验方法和状态，不将模型生成内容称为人工 Ground Truth。将审核后的版本纳入新 Suite，并更新 `curated-v1.json` 的目的、来源、历史表现及状态；不修改已发布 Case 版本。

## 正式运行和比较

原 `trivae eval run` 仍可用于本地探索。要保留正式实验条件，使用两份来自同一冻结主库的工作副本、分别独立的 Evaluation 数据库、版本化 Suite/Case、显式 Variant 和实验目录：

```bash
trivae eval run --suite data/evaluation/new-regression-candidates/suite.json \
  --cases-dir data/evaluation/new-regression-candidates/cases \
  --variant data/evaluation/my-baseline-variant.json \
  --database data/evaluation/work-baseline/trivae.sqlite3 \
  --evaluation-database data/evaluation/baseline-runs.sqlite3 \
  --freeze-manifest data/evaluation/work-baseline/freeze.json \
  --record-dir data/evaluation/baseline-record --judge-version none
```

Candidate 用另一份工作副本、Evaluation 数据库、Variant 和 record 目录运行。Variant 的 `code_version` 必须匹配当前干净 Git commit，`provider`/`model` 必须匹配实际环境；其余声明的 Prompt、工具、检索和预算也应如实填写。配置按已有 `evaluation/variants/` 格式建立；版本需要改变时创建新 Variant 身份。`experiment.json` 记录 Suite、完整 Case 版本、冻结 ID、索引状态、Git commit、声明的 Variant、实际非密钥模型/Router设置、Python/SDK 和 Judge 版本。运行异常会保留已落盘的 Run 与失败状态。`--judge-version none` 表示未运行 Judge，不会生成 Judge 评分。

```bash
trivae eval compare-experiments \
  --baseline data/evaluation/baseline-record/experiment.json \
  --candidate data/evaluation/candidate-record/experiment.json
trivae eval report --evaluation-database data/evaluation/baseline-runs.sqlite3 \
  --output data/evaluation/baseline-report.json
```

比较要求相同 Suite、Case、冻结主库、数据与索引状态、Judge 版本、重复数及完整的逐题运行；不同模型、Prompt、工具或代码作为变化条件列出。能比较不代表质量已改善。报告分别统计运行失败、确定性检查失败、显式人工质量失败、未有本地人工 Review、Judge 失败；类别可能重叠。历史手工 packet 不会自动变成 Evaluation Store Review，所以“未有本地 Review”不否定独立历史人工记录。

人工或模型辅助 Review 以 `EvaluationReview` JSON 保存；质量轴逐项给 `label` 或 `score`，写清 `reviewer_type`、`rubric_version` 和 `needs_adjudication`。`review_id` 只能创建一次，修订另建 ID。

```bash
trivae eval review --evaluation-database data/evaluation/baseline-runs.sqlite3 --review data/evaluation/review.json
```

## 同步与追溯

```bash
# 正式运行的所有 Run 直接来自 experiment.json，不需手抄 ID。
trivae eval langsmith-sync --suite data/evaluation/new-regression-candidates/suite.json \
  --cases-dir data/evaluation/new-regression-candidates/cases \
  --evaluation-database data/evaluation/baseline-runs.sqlite3 \
  --trace-database data/evaluation/work-baseline/trivae.sqlite3 \
  --manifest data/evaluation/baseline-record/experiment.json --experiment my-baseline-20261028

# 已有 benchmark：按 Variant 从原始记录选择，不调用模型。
trivae eval langsmith-sync --suite evaluation/suites/resume-benchmark-dev-v1.json \
  --cases-dir evaluation/cases/benchmark/dev \
  --evaluation-database data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3 \
  --trace-database data/trivae.sqlite3 \
  --records data/evaluation/benchmark/gate3-final-development-real/raw-records.json \
  --variant-id bench-full-system-v1 --variant-file evaluation/variants/bench-full-system-v1.json \
  --judgments data/evaluation/benchmark/gate3-review/gate3-final-development-judge-d.json \
  --import-time --experiment my-history-full-system-20261028
```

也可用多个 `--run-id` 选择特定 Run；每个实验限同一 Variant、每题一个 Run，重复实验用不同名称。历史 benchmark 的 Runner 记录原本为 `single_case`，只有提供同 Run/Case/Variant 的 `--records` 才会关联到所选原 Suite，且导出中仍显示原始 `single_case`。历史 Variant 文件是声明配置，不冒称已独立核实。

```bash
trivae eval langsmith-resolve --experiment my-baseline-20261028
trivae eval langsmith-map --run-id '本地 Run ID'
trivae trace show '本地 Trace ID' --database data/evaluation/work-baseline/trivae.sqlite3
# 有新的本地 Review 时，解析映射后增量上传；重复执行不会重复添加已完成的评分。
trivae eval langsmith-review-sync --evaluation-database data/evaluation/baseline-runs.sqlite3 \
  --review-id '本地 Review ID' --experiment my-baseline-20261028
```

默认映射账本是 Git 忽略的 `data/evaluation/langsmith-external.sqlite3`；不同机器迁移时保留它。每次显式同步创建新 Experiment，同一 Suite/Case 版本复用 Dataset/Example。同步成功后远端可能仍在入库，`langsmith-resolve` 返回 `pending_ingestion` 时稍后显式再执行。网络中断的结果可能已经在远端生效，本地记录为 `unknown`，先检查远端及账本再选择新实验名，不自动重试或覆盖。LangSmith 上独立创建的人工批注不会自动回写本地；正式记录请在本地创建 Review 并用上述命令追加。

**历史时间边界。** 在当前服务上，官方外部实验接口对数周前的原始运行时间实际返回 404/500；SDK 普通 Run 接口对超过 24 小时的时间返回 422。`--import-time` 是显式导入模式：LangSmith 的时间及其显示的 latency 表示导入准备阶段，原始 `original_started_at`、`original_completed_at`、`original_duration_seconds` 保存在每条输出中，不能把平台 latency 当历史推理耗时。对能按原时间导入的新 Run 可不传此选项。外部接口对同一 Example 和完全相同的实验开始时间可能返回 409；本地账本会提前报错，原时间不被改写。可显式选择导入时间模式，不能把导入时间当执行时间。

## 本次真实验证与剩余边界

2026-10-28 使用本机 Key 创建了[历史 Development 对比 Dataset](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/d8a827c1-3e32-4d3d-8caa-793673432ddc)：1 条历史 Case 的词法、词法＋语义、完整系统结果以及一条导入修复验证。最初失败 Run 的本地状态虽为 `failed`，远端因缺少 error 被显示为 `SUCCESS`；旧导入保留，新建 `trivae-history-archify-semantic-failure-mapping-fixed-20261028` 后回读为 `ERROR`，三个结构化 Trace failure 及本地 Trace ID 保留。比较原始版本时请选修复后的失败实验，不使用旧错误导入的远端状态。完整系统的历史 Judge 为 `judge_failed`，Feedback 回读确认其失败状态，没有伪造得分。另以[合成测试 Dataset](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/dd750137-9845-46b1-bc30-56c892a46310)确认不同评分、失败 Trace、追加模型辅助 Review 和重复同步幂等。合成评分只是测试数据；没有额外模型调用。浏览器自动化未能完成页面直接观察，以上为实际服务的 API 回读，不冒称已目视验收 UI。

真实主快照及工作副本各含 864,615 条消息、206 来源，Canonical/词法/语义 revision 98835；它们只在本机 `data/evaluation/`，运行时不能上传 SQLite。旧 Snapshot 多为身份清单而非完整数据备份，因此不能推断旧实验可用当前冻结库精确重放。基于当前冻结库生成了 3 条回归候选、6 条能力候选，均待证据审核。使用明确标注为无模型调用的测试执行器，在真实工作副本上对 3 条回归候选各跑 Baseline/Candidate 一次；6 条模拟运行均保存为 `failed`，实验元数据记录与同条件比较通过。这只验证运行及记录流程，不是实际 Agent 质量结果。没有将候选宣称为新的人工确认 Ground Truth，也没有进行新的付费 Agent 运行。
