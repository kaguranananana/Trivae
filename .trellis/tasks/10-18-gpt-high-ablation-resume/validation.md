# 验证记录

- 原ledger从1继续，第2次真实诊断复现原MALFORMED_STREAM，完整wire后续有completed；未把诊断当有效答案或Baseline。
- 新metadata测试先2 failed/5 passed，根因是合法扩展被SDK联合类型拒绝；修复后相关68 passed（2.68s）。旧缺字段反例继续MALFORMED_STREAM并明确missing，新未知tag断言仍拒绝。
- static：Ruff、mypy128 source files通过；415 passed（9.27s）；0推理。
- 生产Prompt未改；当前真实预算2/120。
