# P06 semantic diff

Parent=P05；production不动。

- Removed：`For
get_schema, send no arguments. `（35字符）。
- Moved：Base候选→工具description/空对象Schema与SDK调用入口。
- Reworded：无；Added：仅get_schema strict Schema、公开无参数description与入口拒绝逻辑，4项测试。
- Unchanged high-risk policy：SQL选择/只读/错误停止、schema先验、其他工具参数以及discussion/negative/temporal/stop/retrieval全文与顺序不动。

3项预期失败证明额外table参数被SDK忽略并到达registry、Schema缺additionalProperties=false。实查SDK默认Pydantic extra=ignore；严格Schema只能公开约束，不能替代执行验证。因此入口在原SDK忽略字段之前要求空对象，非法参数显式ModelBehaviorError；原始JSON错误保留异常链。没有通用防御层、retry、降级或第二套Agent。

SDK既有空对象与空字符串形式在修改前均实际成功；本轮保持二者，不新增兼容路径。合法调用仍进入同一个typed input/scope/registry/evidence/trace链路。mypy曾指出callback需要ToolContext，按真实签名修复，没有cast掩盖。

static=127 passed in2.05s，Ruff/mypy116通过；Provider=0；候选20,115字符。仅L0接受，不宣称真实SQL路由或模型行为等价。
