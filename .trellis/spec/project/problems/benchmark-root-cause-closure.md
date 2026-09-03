# Benchmark failure attribution 与 Provider lifecycle 根因收口

## Problem

`resume-benchmark-v1` Stage 3 的真实运行暴露了两个测量层问题：failure classifier 会把不同
retrieval call 的结果全局合并后重新排序，并把 context expansion call 当成 direct ranking；同时，
benchmark CLI 在同步 `Application` context 内对每个 Variant 分别调用 `asyncio.run`，导致异步
provider client 跨 event loop 使用，最终可能在 Application 关闭阶段抛出 `Event loop is closed`。

## Evidence

- 原始 failure 分类把一批“已在 recorded depth 内观察到、但 rank 超过 Hit@10”的结果记为
  `not_observed_within_recorded_depth`，并把 context-only observation 纳入 direct ranking。
- `data/evaluation/benchmark/stage3-root-cause-targeted/` 的真实 production Query path 复核了
  ranking、context、temporal 三类 failure；新的分类在 targeted run 中产生可解释的
  `ranking_failure`，没有影响 run/Trace 落盘。
- 生命周期问题在全量运行的请求与评分完成后暴露：`TrivaeApplication.close()` 在不同于 provider
  request loop 的 loop 中关闭 `AsyncOpenAI`，底层 HTTP stream 释放调用已关闭 loop 的 callback。
- 修复后的 post-fix clean run 位于 `data/evaluation/benchmark/stage3-root-cause-final-clean-real/`，
  独立 Evaluation SQLite 为 `data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`；
  raw / Evaluation / Trace 均为 185 条。

## Root Cause

1. `_recorded_direct_hits` 原来把所有 retrieval call 的 direct hits 合并成一个排序列表，丢失了
   每次工具调用的 rank 语义；context expansion 的消息也没有在分类边界排除。
2. `run_benchmark` 在 Variant 循环内部分别 `asyncio.run`，而 CLI 用同步 `with` 管理同一个
   `TrivaeApplication`。惰性创建的 provider client 因此跨 loop 使用，且关闭不在请求 loop 内。
3. post-fix clean run 中 C/C2/D 的大批量 terminal failure 是外部 provider availability window：
   Trace 记录为 `APITimeoutError` / `APIConnectionError`，并集中出现 `ROUTER_COMPLETION_TIMEOUT`；
   C2/D 的失败没有首个 model turn。它不是分类器或 context capability 的证据。

## Options

- 仅在 report 中改名或按样例补规则：不能恢复 per-call rank，也不能修复 provider client lifecycle。
- 给 provider 增加 retry、fallback 或把 timeout 视为 completed：会改变真实 failure 语义，违反
  benchmark 的错误透明边界。
- 将 benchmark 主入口改为 async，并让 CLI 在同一个 async context 中创建、运行和关闭
  Application；同时用 Trace 中可见的 per-call direct observation 做 failure 分类。

## Decision

- 新增 `run_benchmark_async` 作为 benchmark 主入口；CLI 使用 `async with create_application(...)`
  调用它，所有 Variant 共享同一个 event loop；保留显式同步包装入口供同步 caller 使用。
- failure classifier 按单次 direct retrieval call 保留 rank，排除 context call；只有在 top-K 观测确实
  不可见时才使用 `not_observed_within_recorded_depth`，观察到 rank > K 则记为 `ranking_failure`。
- provider timeout/connection、model contract、context、coverage 和 zero-result 仍分别按
  真实 Trace / QueryResult 记录，不引入 retry、fallback、静默吞错或单 case 特判。

## Why

该修复分别对准两个可复现的根因：分类需要保留工具调用边界，生命周期需要让异步资源始终在其
所属 loop 内关闭。它们不改 GT、不改 Retrieval 结果、不把外部 provider 波动包装成质量提升。

## Result

post-fix clean run 的 185 条数据完整落盘，failure artifact 146 条：

| Category | Count | Observation |
| --- | ---: | --- |
| provider_failure | 114 | A/B 少量，C/C2/D 集中为 timeout/connection window |
| retrieval_miss | 12 | completed direct retrieval 中没有 GT relevant hit |
| coverage_error | 7 | completed run 没有产出 GT 要求的 coverage status |
| context_missing | 4 | final evidence 缺少 required context |
| ranking_failure | 4 | direct relevant hit 已观察到，但 rank 为 14–29 |
| answer_generation_error | 2 | finalization contract failure |
| zero_result_error | 3 | GT 要求非空但模型给出 no-result signature |

`not_observed_within_recorded_depth=0`、`router_tool_selection_error=0`、
`evaluation_infrastructure=0`。A/B/C/C2/D 分别完成 31/37、35/37、5/37、0/37、0/37；
由于 C/C2/D 的 provider failure window，post-fix run 不被用作这些 Variant 的 ablation quality
结论。独立 recovery smoke 一条 D 成功、一条 C2 失败，保留 provider 的间歇性事实。

## Trade-off

- benchmark 现在需要 async caller 或同步包装入口；CLI lifecycle 代码略多，但资源归属清晰。
- ranking failure 分类依赖 Trace 的 bounded per-call projection；projection 不完整时宁可报告
  `not_observed`，不推断未记录的 rank。
- provider availability 仍会降低单次 full run 的可用质量分母；报告把它作为无条件 completion
  与独立 failure artifact 呈现，而不是在测量层重试掩盖。

## Regression

- `tests/test_benchmark.py` 覆盖 per-call rank、context-only observation、ranking failure 和
  zero-result wording；并保持所有旧 benchmark contract regression。
- `tests/test_cli.py` 的 lifecycle regression 断言 Application enter、benchmark runner 和
  Application exit 使用同一 event loop。
- post-fix clean audit 断言 raw / Evaluation SQLite / Trace 均 185、failure artifact 与 report
  一致、ranking failure 全部 rank > 10、holdout absent。
- 全量 `.venv/bin/pytest -q` 为 576 passed，ruff、mypy 和 `git diff --check` 均通过。
