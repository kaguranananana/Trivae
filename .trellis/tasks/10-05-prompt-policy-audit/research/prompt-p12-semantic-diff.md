# P12 semantic diff

Parent=P11；production原文不动。

- Removed：`provide exactly one identity parameter. `（40字符）。
- Moved：Base候选→原get_message_context工具/字段description与SDK函数体内确定性Host guard。
- Reworded：无；Added：5项真实执行/projection检查；Runtime/Schema结构变化=无。
- Unchanged high-risk policy：source_id复制、canonical message_id的使用条件、相关讨论锚点、选窗/negative/temporal/stop/routing全文逐字保持。

零身份、显式双null、两个非null身份均被原函数体在resolver/registry之前拒绝，registry零调用。真实search projection的source_id/canonical message_id各自省略另一字段或显式null均成功；原Tool description继续Provide exactly one，两个字段仍公开never both。

形式化Schema仍为optional字段，未加oneOf，也不声称Schema会校验参数关系。规则的实际确定性owner是已测试的Host函数体，合法性不再依赖模型遵从Base；因此可生成P0开发迁移候选。没有为机械表达引入新的Schema结构、Tool API或Provider风险。

初次集成测试复用anchor的ToolContext call ID，导致duplicate source handle；按生产Runner逐call更新元信息后原断言通过，没有产品补丁。static=209 passed in2.37s，Ruff/mypy116通过；Provider=0、tokens=0、cost=0。累计候选19,863字符，仅L0接受，不发布production。
