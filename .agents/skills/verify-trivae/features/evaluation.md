# Evaluation 合同

用户可以检查版本化 Case，执行受控查询，并追查失败运行与证据质量。

## Sub-features

- `case-validate` 校验 `evaluation/cases/` 顶层的 Seed Case 并列出 identity。
- `evaluation-trace` 通过 Application 执行受控查询，记录运行条件与 Trace。
- `evaluation-failure` 持久化异常并继续向调用方抛出。
- `evaluation-citation` 将无效或降级的引用与通过状态区分。

## How to get to it (user POV)

用 `trivae eval cases validate` 检查 Case 合同。正式实验的用户入口是 `trivae eval run`，已有历史 Benchmark 与指标工具见 [评测索引](../../../../evaluation/README.md)。

## Driving it with CLI and pytest

前提是已完成 Skill 的 Launch。用 `verify.sh` 创建空 dotenv 后，实际执行 `trivae eval --env-file "$scratch/verify.env" cases validate evaluation/cases`，要求退出 0，JSON 状态为 `valid` 且返回 Case identity。

- 运行 `tests/test_evaluation.py::ApplicationEvaluationTests::test_forced_standard_bypasses_router_and_trace_keeps_override`，核对单个合成 Case 进入 Application Query，Trace 保留路由覆盖，Evaluation 与 Canonical 分库。
- 运行同文件 `EvaluationRunnerTests` 的 `test_runner_exception_is_persisted_and_re_raised`，核对异常、类型和 Trace ID 已保存，调用方仍收到错误。
- 运行 `test_invalid_citation_is_a_hard_deterministic_failure` 与 `test_degraded_artifact_is_deliverable_but_not_grounded_pass`，核对 `citation_provenance` 分别为 `failed` 与 `degraded`。

## Gotchas

- Case 格式通过只证明合同有效。目录校验只读顶层 JSON。默认流程不执行 `eval run`、Benchmark、Judge 或 LangSmith 同步。
- 仓库已有 `trivae eval benchmark retrieval-score` 对照检索指标，依赖匹配的环境清单、数据索引和标注 Case。合成检索回归不需要准备这些材料。
- 真数据实验使用 [正式 Evaluation 的工作库流程](../../../../docs/evaluation.md#本地验证入口)，每次运行独立使用 APFS 写时复制工作库。
