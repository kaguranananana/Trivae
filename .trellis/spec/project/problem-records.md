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

当前没有需要单独升级为长期 Problem 文件的 `real failure`；M5a 的结构性 regression cases、设计取舍和 live smoke 说明集中记录在 [M5a validation.md](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/validation.md)。后续若真实运行复现 provider/model 组合、scope、persistence 或 citation composition failure，再按本索引建立独立 Problem Record。
