# P01 semantic diff

基线 production `9256550`（文本同`460259d`）；独立候选`prompt-p01.txt`。

- Removed：只从Base候选移除下列104字符参数片段。
- Moved：Base → 现有lexical/legacy Tool description + SDK严格正整数解析 + Capability trusted maximum。不是新的检索策略。
- Reworded：无。原机械片段直接删除，其余全文相等；不顺手修标点、大小写、分段。
- Added：只在lexical/legacy limit加`Field(strict=True, ge=1)`；拒绝先前隐式转换的bool/string/float和非正整数。中文注释解释SDK/Host各自职责；无fallback、retry或新工具API。
- Unchanged high-risk policy：discussion/context展开20/40示例、negative、temporal、stop、retrieval routing/inventory最大limit策略全字节与顺序不变；默认limit/context不改。

删除的原文：

```text
limit must be a positive integer no greater than the trusted result limit
shown by the tool schema, and 
```

为什么不会丢失仍由模型负责的行为约束：同一条正整数/当前上限的工具description和字段description仍明确可见；真实SDK拒绝错误类型/非正值，Capability拒绝超过trusted upper bound，测试证明全部在retrieval前失败。模型负责的“清单选最大值、何时继续、展开多少”没有迁移。

原SDK的非严格int把`true`与`2.0`先转换成合法int，typed input无法再看到原类型；先修这个真实边界再生成删除候选。上限仍由Host真实执行，不误称修改JSON Schema的maximum就会拒绝输入。

Baseline 20,450字符，候选20,346；长度仅作为diff事实，不作为质量KPI。L0通过、真实Provider未运行；只接受开发候选，不替换production或声称semantic equivalence。当前生产Prompt继续20,450字符。
