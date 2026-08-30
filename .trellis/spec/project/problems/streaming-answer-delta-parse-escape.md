# Streaming answer delta 解析异常逃逸 query 边界

## 状态

- 发现时间：2026-08-30
- 发现渠道：resume-benchmark-v1 校准 pilot 与 dev 全量运行（`eval benchmark run`）
- 严重级别：High（单次 provider 行为异常即可终止整个 benchmark variant；生产交互链路同样暴露）
- 当前状态：**未修复**（记录于 benchmark 运行期间；修复排入下一迭代，修复前 benchmark 如实把该异常计为 provider_failure）

## Failure

真实 provider（opencode-go / deepseek-v4-flash）在流式最终回答阶段产生无法解析的
answer delta 时，`trivae.query.streaming.AnswerDeltaParseError` 以未分类异常形式从
`TrivaeApplication.query()` 逃逸：

```text
File "src/trivae/query/streaming.py", line 429, in _feed_object
    raise AnswerDeltaParseError("answer JSON object expected a string key")
```

Benchmark 侧证据：`evaluation_runs` 中出现 `terminal_status=exception` 的 run，
`exception_type` 为 `AnswerDeltaParseError` 的直接传播（run 已由 Runner 落盘，
异常继续向调用方暴露）。

## Root Cause

`QueryResult` 的契约是"已分类的终态"：runtime/finalization 失败都应折叠为
`terminal_status=failed` + `RuntimeErrorInfo`，调用方不应收到裸异常。流式 answer
delta 的解析路径（`streaming.py`）在模型输出不符合 delta JSON 契约时直接 raise，
该异常没有被 runtime 归类为 `ModelBehaviorError` 终态，而是穿透 orchestrator 边界。

同类模型行为（invalid tool args、invalid final JSON）此前都已被归类为终态失败；
answer delta 解析是漏网路径——本质是错误分类边界不完整，而非解析逻辑本身错误。

## Fix

（待实施）在 runtime/adapter 边界把 `AnswerDeltaParseError` 归类为
`RUNTIME_ERROR / ModelBehaviorError` 终态（与其他 ModelBehaviorError 同一处理），
不新增 fallback、不重试、不静默吞掉；修复后以同一 case 的 before/after run 留证。

## Impact

- Benchmark：单 case 崩溃曾终止整个 variant（已在 benchmark 编排层隔离为
  per-case provider_failure；该隔离是测量层韧性，不是生产修复）。
- 生产：交互链路在相同 provider 行为下会把异常直接抛给 interface 层。

## Regression

（待修复后补充）用回放 delta 序列的 contract test 断言 query 边界只产出已分类终态。
