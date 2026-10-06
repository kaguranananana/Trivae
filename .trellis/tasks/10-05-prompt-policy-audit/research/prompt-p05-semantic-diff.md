# P05 semantic diff

Parent=P04；production保持原文。

- Removed：`For
semantic_search, query must be one non-empty string.
`（57字符）。P03已经独立迁移同句dense_top_k片段，本轮只移剩余query约束。
- Moved：Base候选→semantic_search.query字段description/minLength/strict与原typed input。
- Reworded：无；Added：一个query Field、中文注释及6项真实SDK检查。
- Unchanged high-risk policy：semantic-first/lexical-first语义选择、概念查询措辞、limit/context/dense默认、discussion/negative/temporal/stop逐字不动。

复现2失败/4通过，根因为Schema缺minLength；空串原Host已经拒绝，现在SDK提前拒绝。非字符串仍拒绝、空白串仍返回Host INVALID_ARGUMENT，registry零调用。合法概念文本保留原strip规范化。不添加regex或其他查询改写。

static=123 passed in2.05s、Ruff/mypy116通过；Provider=0；候选20,150字符。接受L0，尚未证明真实模型路由/答案等价，不替换production。
