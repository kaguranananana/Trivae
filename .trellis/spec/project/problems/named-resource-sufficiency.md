# 工具发现中的证据充分性与候选否决

## Problem

当前冻结快照重放历史 `dev-lexical-resume-miner`，生产Query完成，却只取得相关方法建议和无名Skill，没能交付满足用途的具名工具。另有Case来源真实、引用合法，但内容与附带来源之间仍有话题误归或过强概括。

## Evidence

本轮Baseline8题、21次Flash HTTP，8/8交付；19个固定target中Tool returned/model-visible12、final Evidence11。目标工具题四个已知target在完整Host结果中均未取得，投影没有省略。正式词法离线诊断证明原有上限内可达，不能归成底层FTS必然漏召回或Host裁剪。

完整脱敏审计与逐题报告位于`interview-docs/Evaluation历史失败审计-20261020.md`和`Evaluation端到端质量实验-20261020.md`；私有Artifact、Trace和评审来源保留ignored实验目录。

## Root Cause

首个偏离在工具选择/充分性判断：把用途相关建议当成工具发现问题的足够结果，没有完成聚焦的具名资源核验。与“已召回后未引用”“引用可解析但不支持结论”是不同层。reply投影与自动扩展cap另有缺口，本批未证实它们是该坏答案的原因。

## Options

- 增大Top-K/轮次或全局上下文：没有本轮因果证据，不采用。
- 增加自动检索状态机、按关键词强制工具或Case特判：超出最小边界，不采用。
- 在现有Prompt澄清具名资源的充分性：有真实失败支撑，作为单变量候选验证。

## Decision / Why

候选未获接受。`53a5155`增加通用充分性说明，执行冻结于`3d9cc0e`，预算和其余条件未变。Development显示目标仍未闭合，Evidence11/19→8/19，另一个讨论题遗漏相反立场，Token增加；因此恢复原生产Prompt，保留完整失败。

## Result / Trade-off

本轮取得了复现与归因证据，没有取得可信的端到端质量提升。Prompt澄清可以改变工具行为，但不保证构造有效查询或准确绑定事实；更多调用/链接不构成质量收益。Provider非确定性与单次样本限制结论，后续冻结验证和复测单独报告，不并入正式开发分母。

## Regression / Evolution

保留`evaluation/regressions/named-resource-sufficiency-v1.json`，复用既有GT/Case/Runner/Tier1/ReviewPacket；新增实验发送计数与条件冻结回归，历史Prompt实验测试绑定原冻结源码。后续重新考虑检索/查询策略须另有真实失败与可隔离验证，不能继续叠加提示句或改写本次负结果。未完成人工审核的答案维度保持pending。
