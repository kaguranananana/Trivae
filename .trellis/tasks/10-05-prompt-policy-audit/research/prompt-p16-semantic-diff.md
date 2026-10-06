# P16 semantic diff

Parent=P15；production原文不动。

- Removed：` and scope-enforced outside the SQL text`（40字符）。
- Moved：Base候选→既有Tool description/ExecuteSQLCapability/scoped SQLite adapter。
- Reworded：无；Added：1项真实SDK scope执行检查；Runtime变化=无。
- Unchanged high-risk policy：read-only事实、禁止扩大访问指导、WHERE/ATTACH/PRAGMA/内部表/LIMIT/停止；discussion/negative/temporal/stop/routing不改。

scope只来自RuntimeContext，Capability向repository传入ScopeFilters；未写WHERE的COUNT经SDK仅见qq:100固定范围3条，显式main.messages拒绝SQL_SCOPE_VIOLATION。原Stage C还覆盖session count/join/time scope；工具description仍公开trusted scope事实。原测试把物理row与SDK带source_id投影混用，按实际s1-1修正完整预期，count3及拒绝断言保持。

Static244 passed in2.45s；Ruff/mypy116通过；Provider=0、new tokens=0、cost=0。累计候选19,736字符，仅L0接受；V01测试的是P15，不能转嫁给P16或宣称发布通过。
