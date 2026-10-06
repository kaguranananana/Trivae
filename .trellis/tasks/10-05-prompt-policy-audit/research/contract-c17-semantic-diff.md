# C17 contract / semantic diff

- Removed：无Prompt删除。
- Moved：无；Base没有独立member.limit句，不能虚报职责迁移。
- Reworded：无。
- Added：find_members.limit的Field(strict=True, ge=1)、9项真实SDK/Host tests。
- Unchanged high-risk policy：完整production Base；identity消歧、candidate排序/canonical ID；默认limit、scope、查询和filter规则不改。

复现：5项实际SDK拒绝失败、3合法通过；另一个测试先错用repository方法find_members，按真实read_member_candidates修正。严格执行原Schema integer/minimum而不靠SDK转换后再验。scope5/request6在repository之前拒绝，省略值按scope5/default5保持；scope10/default10及合法1/10保持。

生产trusted scope下完整工具Schema/description/strict flag与V01 baseline实物相等；Provider看到的合同未变。本轮只修SDK执行，0API。static253 passed in2.54s，Ruff/mypy116通过。Accepted=deterministic执行，不是Prompt语义等价发布。
