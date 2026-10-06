# 第一批候选映射（未通过真实回归）

用户已批准第一批方案，并在实施过程中明确要求不使用子代理。曾启动的 implement 子代理已中断，未留下产品改动；本轮实现、检查和评测由主会话完成。

> 候选与测试 patch 已保存，运行源码及测试已恢复原版；当前为 review-ready 候选，尚未交付上线。

## 修改边界

候选仅重写 `prompt.py` 的策略字符串和说明注释；工具 description/Schema、typed input、Capability、Retrieval、Plan、预算、Provider、Finalizer 和输出字段均保持基线实现。没有将相同内容搬进工具描述，也没有新增自动补查、去重 ledger、重试或恢复机制。

实测主 Prompt 从 20,450 到 13,479 字符，减少 6,971（约 34.1%）。这是字符事实，不是语义质量或 Provider token 节省结论。实际 SDK 初始 instructions 包含同一动态预算后为 20,643 / 13,672；工具描述与 Schema 的序列化体积相同，预检中为 16,129 字符。

## 原审计 ID → 稳定主位置

行号继续指审计基线，候选按标题定位；归档后代码行号可能变化。

| 原 Policy | 候选主位置 | 等价边界 |
| --- | --- | --- |
| P01–02、P17、P35、P43、P53–54 | Core principles / Discussion investigation | 实际问题与证据、Plan 软建议、实体区分度、不能虚报或泄漏内部执行细节 |
| P03–05、P10–12、P65 | Recent overviews / Verified zero results / Parameters | 时间决定候选集、人物过滤、完整空窗停止；Host 默认和 SQL 不足空证明保留 |
| P13–16、P41–42 | Precise and conceptual lookup / Stopping and errors | 精确与概念两路径、只补实质证据缺口，不无目的双查或重复变体扩展 |
| P06、P29–36、P45 | Discussion investigation / Parameters | 相关提问锚、局部不足优先 context、独立并行、按线索选窗口、邻接不证明关系 |
| P07–09、P18–23、P25、P38、P83–87 | Resource inventories / Answer depth | github.com-first 适用边界、lexical 最大值/0 context、semantic 独立上限、类别缺口、避免重数、链接与代表性呈现 |
| P24、P44、P85、P91–92 | Host time facts / Evidence policy | archive_latest 交 Host、UTC 原样、不从历史/毫秒计算日期；text/finding/criterion 时序一致 |
| P26–28、P37、P39–40、P63–64 | Identity and structured statistics / Parameters | canonical identity/SQL 字段关系、只读、get_schema、统计而非手数、SQL error 停止 |
| P46–52 | Evidence policy | author 与 content 区分、提问/回复/推荐/使用/模型归纳、命中数与实体数、partial 的负面结论边界 |
| P55–62、P66–67 | Parameters and continuation | 尚未由 Schema 完整表述的必要字段指导集中一次；身份恰一项、非空/非负、时间互斥、游标原样续传均保留 |
| P68–71、P74–75、P90 | Evidence policy / Output contract | 只用当前 message/structured 短 handle，Host hydrate/ID，既有局部 degraded 与 fatal scope/provenance、不伪造来源 |
| P72–73、P76–78、P89 | Output contract / Verified zero results | JSON mode 下保留 claims/no_result 格式、enum、无 fence、closing braces、完整空证明与 SQL aggregate 边界 |
| P79–82、P88 | Answer depth and presentation | metadata 有界与正文充分分开、独立 finding 可分 claim、相关事实可分组、不倾倒原文 |

去重簇与跨段定位可能重复列出同一 ID，但 P01–P92 全部有承接。四个单行字面重复只保留一次；30 天相对时间示例与 JSON handle 示例因当前生成契约保留，未为了字符数强行删除。

## 实测后的最小修订

首个候选为 13,143 字符。第一轮真实配对出现精确查找的同轮近似词扩展，资源材料清单先走精确词路径；同时宽讨论局部窗口未覆盖推荐。最终候选明确讨论/清单意图优先于通用查找默认，恢复原版“不要向同一检索工具发起第二次翻译/同义/标点变体查询”的直接禁令，并恢复原版 20/40 选窗示例及其“不是固定规则或新默认”的边界。均承接 P13–16/P41–42、P07–09/P18–23 与 P06/P29–36/P45，不新增关键词路由或机械窗口规则。宽讨论漏推荐仍须用真实证据验收，不能只靠措辞承诺已解决。

## 逐字测试断言映射

只更新以下五项文案断言，测试函数、数量、真实执行/参数/来源/结果断言均未删除或放宽。文案变化在候选测试运行前完成；不用于绕过错误实现。

| 测试 | 旧措辞 | 新措辞与原因 | Policy |
| --- | --- | --- | --- |
| test_agent_runtime.py | exact keyword + github.com | github.com the FIRST retrieval call；URL-first 与精确 keyword 仍在同段，去除断言对行内拼接的依赖 | P07/P18 |
| test_agent_runtime.py | never use SQL to calculate | Never use SQL to calculate；只是新段首大小写 | P24 |
| test_agent_runtime.py | never choose … 20 or 30 | rather than a smaller convenience limit；保留 MUST lexical maximum，具体小 limit 例子不再重复 | P19/P22 |
| test_agent_runtime.py | context_before/context_after 中间换行 | 同一句无换行；仍为 0 context | P20 |
| test_context_source_contract.py | source_id="m1-1" 出现在主 Prompt | copy an exact returned source_id；具体 m1-1 仍由真实工具 Schema 断言验证，canonical message ID 区分与错误参数执行测试保留 | P29/P59/P60 |

初次候选测试有两个逐字失败，原因是 `use get_message_context` 与 `canonical internal message ID` 的中间换行；通过调整候选原句排版解决，未改这两个断言。随后 145 项相关测试和 662 项全量测试通过。

## 未实施与后续边界

工具 Schema 的 minLength/minimum/互斥缺口未补，Structured Outputs 未引入；no_result “关键词空结果与全窗无消息”的既有措辞张力保留。语义评估仍应核对实际证据；短 Prompt 不承诺解决既有缺失召回、局部窗口不足或强否定问题。
