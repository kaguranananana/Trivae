# P14 semantic diff

Parent=P13；production原文不动。

- Removed：`add a second statement or `（26字符）。
- Moved：Base候选→既有SQLite connection.execute单语句限制、SQLMalformedError、Tool description。
- Reworded：无；Added：3项真实SDK/SQLite contract tests；Runtime变化=无。
- Unchanged high-risk policy：hidden schema指导、SQL routing/error stopping、discussion/negative/time/stop/retrieval routing逐字不动。

两个SELECT及SELECT后接DELETE经正式SDK/Capability/SQLite均明确SQL_MALFORMED，保留driver的one statement at a time信息。失败后fixture仍8条消息。字面量分号、结尾分号和注释合法，未新增SQL拆分/过滤或重写。不能仅凭SQL字符串类型断言单语句；这次实际执行证明已有driver承接。

Static237 passed in2.14s；Ruff/mypy116通过。Provider=0、tokens=0、cost=0；候选19,792字符，仅L0接受，不发布production。
