# Problem Records

> 重要 Failure Case 与关键工程问题的长期沉淀。
> 规则：**只有重要问题才记录**；普通小 Bug 不制造文档。

---

## 记录位置

- 完整记录：`.trellis/spec/project/problems/<slug>.md`（或关联到对应 task 目录后在此建立摘要索引）。
- 本文件作为索引：每个重要问题在本文件追加一行摘要 + 链接。

## 记录模板

```
## Problem
出现了什么问题。

## Evidence
如何发现：对应 Failure Case、Trace、日志或指标。

## Root Cause
最终定位到哪一层，根本原因是什么。

## Options
考虑过哪些方案。

## Decision
最终选择什么方案。

## Why
为什么选择当前方案。

## Result
修改前后行为或指标变化。

## Trade-off
带来了哪些代价。

## Regression
增加了什么测试或机制防止复发。
```

## 适用场景

- 影响 Quality / Reliability / Latency / Token / Cost 的重要问题；
- 修复后需要防止复发的关键 Failure Case；
- 涉及模块归属判断（Failure Attribution）的典型错误。

## 当前记录

- [DeepSeek Tool/Provenance contract failure](./problems/deepseek-tool-provenance.md)：真实 Provider 曾产生越过 trusted `max_results` 的 `limit`，并把两个 Tool Result 的 locator 字段拼接为一个消息来源；已通过 provider-facing schema、self-contained provenance projection、Prompt 约束和 regression test 修复。
- [DeepSeek structured output budget failure](./problems/deepseek-structured-output-budget.md)：真实多轮 Run 在未固定最终 JSON 输出预算时产生 `INVALID_ANSWER_ARTIFACT`；已在同一 Provider Runtime boundary 固定 JSON mode、显式预算和紧凑 artifact 指令，严格 Finalizer 与 Planner degraded 事实保持不变。
