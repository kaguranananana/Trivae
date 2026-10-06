# 已验证的参数契约迁移

production SYSTEM_PROMPT仍是原20,450字符。P01–P09只生成累计开发候选；最新20,025字符，425字符仅作精确diff事实，不是质量/成本KPI。模型语义与最终release gate均未验证。当前真实Provider预算0，不运行整套真实AB。

## 字段与真实执行owner

| Rule | Iteration | 机械约束 | 实际执行 | 保留的模型判断 |
| --- | --- | --- | --- | --- |
| P56 | P01 | lexical/legacy limit正整数与trusted上界 | SDK strict/ge=1；Capability上界 | 清单选择最大值、何时继续检索 |
| P57 | P02 | lexical/legacy context非负整数 | SDK strict/ge=0；typed input | 默认2不改；讨论20/40、选窗与停止 |
| P58 | P03 | semantic dense_top_k正整数 | SDK strict/ge=1；typed input | 默认40不改；召回策略 |
| P62 | P04 | member query非空字符串 | SDK strict/minLength=1；typed input非空白 | identity消歧、canonical ID |
| P58 | P05 | semantic query非空字符串 | SDK strict/minLength=1；typed input非空白 | semantic-first语义选择 |
| P64 | P06 | get_schema不接收参数 | strict空Schema+SDK入口检查 | SQL选择与schema调查时机 |
| P55 | P07 | lexical/legacy keyword单字符串 | 原SDK string/typed input；本轮无实现改动 | 关键词/实体锚点选择 |
| P55 | P08 | lexical三种filter不能空数组 | SDK minItems=1；原typed input | unused filter选择、scope与canonical语义 |
| P62 | P09 | member session_ids不能空数组 | SDK minItems=1；原typed input | session选择/identity消歧 |

P06保留SDK原有空对象/空字符串合法形式；额外字段在SDK忽略前失败，JSON解析保留异常链。省略/null的filter沿原scope继承。没有fallback、retry、正则ID或额外单侧窗口上界。

## 检查方式与已知限制

- 参数测试在真实FunctionTool解析/typed input之后才允许recording registry；非法输入必须registry零调用，合法输入保留同样参数。真实检索、scope、projection与Finalizer由原有fixture和全量工程测试覆盖。
- 精确候选manifest按production→前一候选逐步删一个片段，其他字节/空白/顺序相等。mapping定位用实际片段和最小源码行范围；不能按旧审计行号机械取行。A01已经更正P41–P71附近错位，P04 Rule是P62。
- P48–P51为近似重复，当前不标完整literal duplication，不去重。Discussion/Negative/Temporal/Stop/Routing全部保持原文。
- 最新793全量测试、176相关static、Ruff/mypy116通过；0真实Provider/0新增tokens/0cost。L0与synthetic不证明真实模型语义等价。
- 历史6个frozen baseline保存旧SDK合同，新lexical/semantic/member/get_schema合同有差异；当前candidate-only/targeted预检显式拒绝，不能改写历史条件或自动付费刷新。

完整逐条matrix位于同任务目录prompt-responsibility-matrix.md；它超过自动注入上限，需按真实Rule ID手工读取相关部分，并在修改前核对实际prompt.py。实现位于openai_tools.py；检查位于test_prompt_parameter_contracts.py和test_prompt_screening.py。全文上下文不要依赖截断后的尾部。
