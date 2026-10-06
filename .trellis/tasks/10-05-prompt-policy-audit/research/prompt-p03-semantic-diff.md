# P03 semantic diff

Parent=P02；唯一生产baseline原文不动。

- Removed：` and dense_top_k must be a positive integer`（43字符）。
- Moved：Base候选→SDK字段description/strict minimum=1 + 原有SemanticSearchInput正整数校验。
- Reworded：无；Added：仅dense_top_k的Field(strict=True, ge=1)及参数description、中文注释。
- Unchanged high-risk policy：semantic/lexical routing、limit策略、context窗口、query及filter字段、discussion/negative/temporal/stop全文与顺序不改；dense默认40不改。

7项真实SDK红灯、5项typed input已通过，定位为SDK在业务校验前转换bool/string/float以及Schema缺minimum。修复后非法原类型和非正值全部在registry前失败；合法1和省略默认40均到达原业务输入。description直接公开原先Base承担的正整数机械约束，没有新增候选规模选择策略、上界或检索算法。

static=111 passed in1.88s、Ruff通过、mypy116文件通过。Provider=0；候选20,243字符，单片段全文相等检查通过。仅接受L0；不自动发布或证明模型召回等价。
