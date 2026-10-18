# 继续 GPT High 原消融实验

修复真实 response.metadata / union_tag_invalid，核实 SDK/Provider 合同并保留严格终态、工具、Usage、Reasoning与错误分类。允许验证后升级SDK或局部适配，禁止吞未知事件。生成与当前 chunker 匹配的独立 semantic snapshot，不改旧snapshot/GT/Holdout。

复用原 A/B/C 目标、人工 Development Case 和 Application.query；固定 chatgpt-plan/gpt-6.1-sol/high、Standard route。原 ledger `data/evaluation/gpt-high-ablation-20261018/total-budget.json` 当前1/120；所有真实推理含诊断共享此门禁，不清零、不扩充。真实验证后逐组删冗余与行为策略，质量退化拒绝，最终门禁不通过保留生产Prompt。隐私结果ignored、中文报告脱敏、提交并推送main。
