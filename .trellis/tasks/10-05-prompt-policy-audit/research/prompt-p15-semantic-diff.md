# P15 semantic diff

Parent=P14；production原文不动。

- Removed：`, writes, or DDL`（16字符，P39:write_ddl）。
- Moved：Base候选→已有SQLite authorizer/read-only connection与Tool description。
- Reworded：无；Added：2项真实SDK执行检查；Runtime变化=无。
- Unchanged high-risk policy：原句read-only事实、WHERE/ATTACH/PRAGMA/内部表/scope、LIMIT、truncated、错误停止；discussion/negative/time/stop/routing不改。

已有authorizer拒绝写入及DDL action，SQLite连接mode=ro并query_only。DELETE和CREATE TABLE经过正式SDK均SQL_READ_ONLY_VIOLATION，错误透明；消息仍8条，额外直接读取fixture sqlite_master证明injected表不存在，不能拿隐藏未知表的public schema投影证明DDL未执行。原Stage C全面写入/DDL检查继续执行。

Static239 passed in2.08s；Ruff/mypy116通过；Provider=0、tokens=0、cost=0。累计候选19,776字符，只接受确定性/L0，不宣称模型调用或答案行为等价。最初commentary Rule编号P44经真实定位纠正P39，manifest定位测试通过。
