# 实现边界

## 已证实的行为缺口

`pu-dependent-mattpocock` 两条 v2 Trace 的首个检索都以完整实体 `mattpocock` 返回 8 条命中。随后 Planned Runtime 把 follow-up query 改成类别词 `skills`，得到 244 条命中而本次仅返回 100 条，产生已标注的 `partial + truncated`。这比“Planner 没有提出 firsthand-use 目标”更早：Planned 的 captured plan 明确包含实体、同一讨论脉络、亲自使用表述和限制说明。

`dev-context-archify` 是另一种 Runtime 不稳定：直接 lexical 命中完整，但 Runtime 有时扩展最初分享邀请的上下文、有时扩展后续热度或插件公告，有时不做 context retrieval。单独这一 Case 不能证明自动扩大 context radius 或增加新检索机制的收益。

## 代码变更

只改 `src/trivae/query/runtime/prompt.py` 的共享 `SYSTEM_PROMPT`，增加一条通用 follow-up 选择原则：

1. 查询特定实体后继续追问时，保留该实体作为 lexical anchor，不要只换成泛类别词；
2. 需要回复、后续反应或 firsthand feedback 时，选择与该关系目标最相关的 direct hit 作为 context anchor；
3. 当用户问题本身是类别清单，或实体检索不足以覆盖另一项明确需求时，才补充不同候选集的检索。

该 prompt 对 Standard / Planned 两路相同生效，保持 Planner 为软指导，并要求 retrieval partial/truncated 边界继续如实披露。新增的 Python 注释使用简体中文解释以上三条约束与适用边界。

## 明确不改

- Planner prompt、Plan schema、Plan guidance renderer：实体和 firsthand-use 目标已存在于 Planned 输出。
- Lexical candidate limit、context expansion radius / budget、Capability / Tool contract：partial/truncated 在当前 Trace 中正确表达；Trivae 已自动扩展有限上下文。
- Evidence selection、citation validation、zero-result positive proof：失去的 firsthand source 在 Planned 候选结果中已缺失。
- 自动 continuation、requery loop、fallback、retry 或新 Agent/workflow：没有当前契约要求，也无证据证明应增加。
- `dev-context-archify` query 特例或任何 Case/query 字面量匹配。

## Deterministic regression

在 `tests/test_agent_tool_surface.py` 增加共享 Runtime prompt-contract regression，断言通用实体 anchor 保留、context anchor 与 follow-up 证据目标对齐，以及类别级查询可继续检索独立候选集。它锁定 Runtime 向模型表达的职责，不声称静态测试能够保证 Provider 对软指导的执行。既有 coverage/Tool projection 与 no-result regressions 覆盖 limit 元数据和 zero proof；代码本身不触及这两条链路。

## 验收边界

修复只有在 v3 targeted repeats 中呈现为可观察的 Tool args、候选集、Evidence 及答案差异，才能称为行为有效。Runtime prompt 的静态测试通过只证明契约文字存在。v3 小样本不能形成 treatment-wide、generalization 或 production rollout 结论。

## v3 实测结果

- `pu-dependent-mattpocock` 的 Planned 两次都没有复现 Standard 的 `matt skill` follow-up 查询，且两路都缺失同一个人工 required-context source。Planned 未在该 Case 上证明收益。
- `dev-context-archify` 的 Planned 两次都恢复了 `好用` 与安装/使用上下文；Standard 两次都遗漏该 required context。该单一 Development Case 出现重复方向一致的 Planned-beneficial 信号。
- aggregation 与 verified-zero 两组 controls 在两路均正确；完整运行、Evaluation result 与 Trace 各 12 条一一对齐。
- 该 Case-level v3 assistant review 不改写被冻结的 v2 adjudication。逐 pair 结果、失败记录、usage 与限制见 `validation.md`。
