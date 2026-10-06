# P04 semantic diff

Parent=P03；production仍原文。

- Removed：`query must be one
non-empty string; `（36字符）。
- Moved：Base候选→find_members.query的Schema minLength/description及原FindMembersInput。
- Reworded：无；Added：仅query字段strict/min_length=1及中文注释、6项测试。
- Unchanged high-risk policy：identity消歧、canonical user_id、filter和limit、discussion/negative/temporal/stop/retrieval原文及顺序不动。

复现2失败/4通过：空串本来在Host返回INVALID_ARGUMENT，Schema缺minLength；非字符串本来已经在SDK拒绝。本轮补公开Schema与SDK空串约束，不虚称修复新的字符串转换问题。空白串仍由原typed input拒绝，registry零调用；不额外引入正则或normalize算法。合法名称继续原strip规范化。

static=117 passed in1.95s，Ruff/mypy116通过。Provider=0；候选20,207字符。只有L0接受，不等于模型行为等价或release。
