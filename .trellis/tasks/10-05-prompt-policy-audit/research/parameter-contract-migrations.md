# 已验证的参数契约迁移

production SYSTEM_PROMPT仍是原20,450字符。P01–P16只生成累计开发候选；最新19,736字符，714字符仅作精确diff事实，不是质量/成本KPI。模型语义与最终release gate均未验证。后续确定性轮次真实Provider预算0，不运行整套真实AB。V01已发生2次首工具请求：结果inconclusive，baseline usage未知，candidate input8349/output115/total8464；累计tokens/费用未知，不据此发布。

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
| P66 | P10 | recent.limit严格正整数 | SDK strict/ge=1；Capability可信上界 | archive_latest默认两天、时间互斥、cursor |
| P61 | P11 | 显式context非负整数/共享总量 | SDK strict/ge=0；typed input总量上界 | 默认8/8、选窗20/40、讨论与停止 |
| P60 | P12 | 恰一身份参数 | 原SDK函数体Host guard，实测合法/非法 | 已知canonical ID/锚点相关性；Schema无oneOf |
| P63 | P13 | SQL单字符串/optional正整数cap | SDK/typed input；Capability可信上界 | SQL选择、schema调查、错误停止 |
| P63 | P14 | 不执行第二条SQL | 原SQLite execute/SQLMalformedError | hidden schema指导 |
| P39 | P15 | SQL写入/DDL禁止 | 原authorizer/read-only连接，实际SDK拒绝 | scope/WHERE/ATTACH/PRAGMA/LIMIT/错误停止 |
| P39 | P16 | SQL外部scope执行 | 原scoped connection，实际SDK count/物理表访问检查 | WHERE/ATTACH/PRAGMA/LIMIT/错误停止 |

P06保留SDK原有空对象/空字符串合法形式；额外字段在SDK忽略前失败，JSON解析保留异常链。省略/null的filter沿原scope继承。没有fallback、retry、正则ID或额外单侧窗口上界。

## 检查方式与已知限制

- 参数测试在真实FunctionTool解析/typed input之后才允许recording registry；非法输入必须registry零调用，合法输入保留同样参数。真实检索、scope、projection与Finalizer由原有fixture和全量工程测试覆盖。
- 精确候选manifest按production→前一候选逐步删一个片段，其他字节/空白/顺序相等。mapping定位用实际片段和最小源码行范围；不能按旧审计行号机械取行。A01已经更正P41–P71附近错位，P04 Rule是P62。
- P48–P51为近似重复，当前不标完整literal duplication，不去重。Discussion/Negative/Temporal/Stop/Routing全部保持原文。
- 本批915全量测试（18.47s）；C23最新305相关static、Ruff/mypy116通过。P10–P16、C17–C23及fixture轮次各0新增Provider；V01实际2次单独计入。L0与synthetic不证明真实模型语义等价。
- C17/C18分别修复member/semantic limit已公开的严格正整数执行；C19/C20让semantic及lexical/legacy执行默认值与scope Schema共用。Base无待删对应文字，因此不虚报Prompt迁移。正常默认/显式参数/窗口/路由不改。
- F02复现合法claims的错误强负面结论仍可Finalizer valid；F03确认after20/40实际送入下一轮模型input并解析推荐来源。只证明送达与错误边界，不证明真实模型自行选窗。
- 历史6个frozen baseline保存旧SDK合同，新lexical/semantic/member/get_schema/recent/context/SQL合同有差异；当前candidate-only/targeted预检显式拒绝，不能改写历史条件或自动付费刷新。

完整逐条matrix位于同任务目录prompt-responsibility-matrix.md；它超过自动注入上限，需按真实Rule ID手工读取相关部分，并在修改前核对实际prompt.py。实现位于openai_tools.py；检查位于test_prompt_parameter_contracts.py和test_prompt_screening.py。全文上下文不要依赖截断后的尾部。

## 后续零成本契约与Harness闭环

C21仅补semantic窗口strict/ge=0，合法2/2与0/20/40原样；C22/C23分别公开执行semantic三数组/recent双数组minItems=1，omit/null/合法值及时间/cursor不变。Base无对应待删机械句，所以未生成P17或替换生产。新增Schema与V01合同不同，不能沿用其同条件筛选结论。

H06/H07在正式SDK并行调用中复现坏JSON被当正常probe、继续后case的问题。先保留arguments_raw、原异常，再要求FirstToolProbeStop且每个已观测call解析完成、Host零执行。坏/合法两个顺序都立即阻止下一case；正常probe可继续显式选择case。没有隐藏异常、伪造Trace或重试。全部ScriptedModel验证，新Provider调用0。

当前剩余mixed规则：known canonical身份/相关锚点属于模型选择；cursor不能跨轮重复和不改位置尚不能声称全部由Host承接；时间选择、unused filter、read-only主语及SQL停止指导保护；E输出生成Schema/证据蕴含/负面判断不能靠Finalizer valid删除。纯literal duplication仍F=0。不因剩余字数继续删语义句。
