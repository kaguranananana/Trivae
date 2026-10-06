# C18 contract / semantic diff

- Removed/Moved/Reworded：无Prompt变化，Base未单独声明semantic.limit机械句。
- Added：semantic_search.limit Field(strict=True, ge=1)、9项SDK/Host tests。
- Unchanged high-risk policy：routing、query/filter、context2/2、dense40、limit默认10/算法；production Base逐字不动。

复现5 failed/4 passed；SDK转换原始非法类型，Host原有正整数/上界规则保持。真实scope5/limit6在semantic search之前拒绝，未加载embedding。Schema/description/strict flag与V01 baseline生产scope合同相等；仅解析执行改变。static262 passed in2.45s，Ruff/mypy116通过，0新API。default在小scope的已知矛盾留C19，不混入本轮。
