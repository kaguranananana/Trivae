# 调参外独立验证（2026-10-20）

**没有复现可信的质量改善。** 冻结候选的固定目标Evidence覆盖为22/29，Baseline为23/29；交付成功为11/12与12/12。候选延续拒绝决定，不进入生产。人工答案质量仍 unavailable。

这里“独立”仅指**未参与本次Prompt调整**。12题来自已有Development，历史上已暴露；不是fresh、blind、unseen Holdout，也未复用sealed v1/v2 Holdout。新快照的Case适用性与新答案人工审核均待完成。

## 数据与执行登记

- 在首次Baseline前，已从未纳入本轮8题调参的旧Development预选12题，保留原问题与参考来源；没有随机重新造题。
- 包括8道资源/具名工具相关问题，其中MCP统一管理是用途描述型工具发现；其余为明确实体/引用控制。另有3道概念改写讨论题及1道确定空日，检查非目标回归。目标分布很窄，不能外推任意工具发现。
- 12题共29个历史target全部在811,892条冻结快照中存在；空日重新按UTC查询确认为0。使用独立`quality-` Case身份，原人工GT与当前适用性状态区分。
- Candidate先冻结于`3d9cc0e`，随后使用两个冻结源码工作树：A=`8def8d7`，B=`3d9cc0e`；每次从实际import路径核对commit。主工作区恢复生产Prompt不会改变冻结B。
- 首次请求前保存24个unit的执行顺序；每题A→B紧邻，复用同一CLI、生产Query与条件相等门禁；固定顺序有时序偏差，未伪称counterbalanced。
- 无修改Prompt、GT、工具预算、评分规则或失败后的重跑。24条运行均保留，成功和失败都生成原生ReviewPacket；失败一侧`answer_text=null`，不冒充正式答案。

## 实测

| 指标 | Baseline | Candidate | 变化 |
|---|---:|---:|---|
| 人工有证据答案通过率 | unavailable | unavailable | 没有新答案人工裁决 |
| 固定目标Evidence覆盖 | 23/29，79.31% | 22/29，75.86% | −1/29，−3.45个百分点；不是整体答案准确率 |
| Tool returned目标覆盖 | 25/29 | 23/29 | −2个目标 |
| 人工事实引用支持率 | unavailable | unavailable | 未审核维度保持pending |
| 交付成功率 | 12/12 | 11/12 | −1/12；保留原12题分母 |
| Flash HTTP请求 | 30 | 33 | +3；无实验重试 |
| 总Token | 651,643 | 799,248 | +147,605，+22.65% |
| Query平均延迟 | 37.89s | 48.49s | +10.59s，+27.96% |
| Query中位延迟 | 21.22s | 52.10s | 每侧12次观察，包含失败运行 |
| 真实货币成本 | unavailable | unavailable | 不从Token推算 |

没有付费Judge，当前没有给12题计算Assistant语义通过率；选定变化的源证据诊断不能冒充全量内容审核。部分GT之外存在其他正确来源，未命中某条旧target不自动判内容错误。

## 每题目标与执行结果

下表省略共同`quality-dev-`前缀。

| Case | Evidence A→B | 执行 A→B | 诊断 |
|---|---|---|---|
| lexical-forge | 1/3→3/3 | completed→completed | 两侧已能识别正确项目与用途；B多引用两次分享，不等于首次解决业务问题 |
| lexical-mcp-switch | 2/2→1/2 | completed→completed | B只semantic，返回目标少一条；仍找到正确统一管理工具与链接，不能把重复来源减少直接判核心失败 |
| lexical-vibe-game | 1/3→1/3 | completed→completed | 固定目标仍不全，未据此声称全库检索完整 |
| lexical-siclaw | 3/3→3/3 | completed→completed | 固定目标保持 |
| lexical-zenith | 4/4→4/4 | completed→completed | 固定目标保持 |
| cite-archify | 3/3→2/3 | completed→completed | 两侧都取回三目标；B最终选据少一条，主要进展/star问题仍被回答。需人工判断局部引用支持，不能把目标减少直接当事实错 |
| cite-volcengine | 5/5→5/5 | completed→completed | 固定目标保持 |
| cite-lofisu | 3/3→3/3 | completed→completed | 固定目标保持 |
| para-intern-hard-part | 0/1→0/1 | completed→completed | 两侧已知目标未取回，其他来源充分性待审 |
| para-written-test | 1/1→0/1 | completed→completed | B工具返回未包含已知目标；先在获取/查询选择层发生差异，不归成projection省略。内容不能未经复核记为pass |
| para-webnovel | 0/1→0/1 | completed→completed | 已知target两侧均未取回；partial GT不等于所有回答都错 |
| zero-empty-2 | 0/0→0/0 | completed→failed | 非目标空日回归出现Finalizer合同失败；不计入target Recall分母但仍占执行/交付分母 |

## 唯一系统交付失败

B的`zero-empty-2`先`get_schema`，两次`execute_sql`获取其他日期的非空分组行，最后才`get_recent_messages`取得目标UTC日的complete/0。它以`kind=no_result`输出，并在summary加入邻近日期统计。

生产`has_verified_zero_result_evidence()`允许完整空时间窗与符合合同的纯数值SQL聚合并存，但普通/日期分组结构化行不属于该辅助形态。本轮已取得的30行及3行日期统计未满足这一条件，最终`INVALID_FINAL_OUTPUT`：`zero-result final answer lacks verified complete-and-empty retrieval evidence`。这不是目标日确有消息，也不是Provider timeout；HTTP均成功，Runtime正常结束，**Query最终失败且没有正式Artifact**。

A直接读取目标日并交付。不能为提高B分数放宽引用/zero-result合同，也不能将Runtime completed统计成整链交付成功。该现象与历史SQL-first风险相关，但本轮不将其混入具名资源treatment的“已修复根因”。单次波动也不足以证明那段Prompt必然导致此路径；它足以否决本候选的无退化声明。

## 可信边界与后续审核

本轮只能证明：在同一当前快照、Provider与冻结源码下，这12个调参外问题没有给出总体收益证据，并暴露了额外交付失败与开销。历史曝光、单一语料、只各跑一次、固定A→B顺序、模型后台不可固定、新答案未人工裁决都限制结论。

本地`review-packets/`提供原生Packet、隐藏arm的展示与封存映射；展示身份为`(split, case_id, side)`，避免开发集与复测复用Case时歧义。原始Answer、Runtime未通过输出、SQL结果、Trace和源消息保留ignored目录，不进入公开报告。

补充方差复测单列在[端到端实验报告](Evaluation端到端质量实验-20261020.md)，不替代这24条正式记录，也不用于重新调参。
