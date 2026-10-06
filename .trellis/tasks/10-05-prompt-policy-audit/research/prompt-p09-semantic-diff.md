# P09 semantic diff

Parent=P08；production原文不改。

- Removed：` and do not send empty arrays`（29字符），仅find_members.session_ids指导；omit when unused保留。
- Moved：Base候选→member session_ids的Schema minItems/description与原FindMembersInput。
- Reworded：无；Added：单个Field约束/description、中文注释与6项SDK/typed input测试。
- Unchanged high-risk policy：member消歧、canonical user_id、query/limit、session scope继承、discussion/negative/temporal/stop/retrieval与其他文字逐字不动。

初次测试因漏导入FindMembersInput失败，先修测试构造后复现2失败/4通过：Host已经拒绝空数组，Schema缺minItems。本轮补字段公开并执行同一机械约束，空数组registry零调用。省略/null/正常数组三种形式沿原typed参数，不变更scope或多候选处理。

最终static176 passed，Ruff/mypy116通过；Provider=0；候选20,025字符。接受contract与L0候选；不宣称模型行为等价，不替换production。
