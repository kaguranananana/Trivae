# Prompt Optimization Log

当前唯一 baseline：production `9256550`（Prompt 与 `460259d` 相同）。旧失败候选留在 research，不覆盖。开发冻结结果使用完整 Prompt 原文 + commit / snapshot identity，不新增摘要算法。

## A00：当前责任与评估审计

- Commit：本节所属 `docs(prompt): map current responsibilities and low-cost validation gaps`。
- Changed rules / Responsibility moved：无；只读覆盖 P01–P92，动态事实 B01–B05。
- Static：位置覆盖 224/224、92 个 ID；已有 SDK/get_schema 实物核验。
- Synthetic / Real cases：无；Provider calls=0，tokens=0，cost=0。
- 当前 EvaluationRunner repetitions 默认 1，可冻结 snapshot；suite_tags 可复用但无 policy 命令；compare_evaluation_runs 可比较已存结果但没有完整 Prompt/snapshot/参数相等检查；没有 first-tool。
- 明确缺口：get_schema 多余参数未在 Schema 拒绝；非严格 int 会转换类型；cursor 重复未有跨轮 guard。
- Accepted：审计产物；不修改生产行为，不证明旧候选等价。

后续 H01/F01/P01 每轮单独补充；semantic diff 在提交前记录 Removed / Moved / Reworded / Added / Unchanged high-risk policy。
