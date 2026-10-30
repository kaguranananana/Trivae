# R3：评测信号与时效假设复核（零模型请求）

2026-10-30。脚本 `audit_measurements.py`，原始输出在 ignored `data/evaluation/agent-quality-codex-20261030/measurement-audit.json`。没有改历史GT、Review、覆盖率或人工待确认表。

- Case02：A2 claim-7、B1 claim-6确实包含“旧登录行为→快速测试”，故原rationale“均未报告”不准确。但A2称“群里给的做法”、B1称“另一个实践”，仍没有满足冻结02b的“转发建议而非验证实践”属性要求。保留uncovered，不把内容出现误报为合格事实。此处验证的是评定理由缺陷，不是Agent提升。
- R1的40个L6_adopted中，仅36个能在原始答案来源中找到完全一致的目标ID。其余4项受到根消息/转发兄弟节点的数字ID相交误判。即使36项ID一致，也不证明对应语义事实采用，不能用L6统计替代coverage-assessments。
- 将52条combined temporal_or_scope_error逐条辅助分类：41条主要是实体、任务条件或群体范围；4条来源日期错读；7条历史信息泛化为当前可用。分类为Codex辅助、provisional，不是独立人工GT。Q8“52条都是缺少查询日期锚定”的推断被否定；查询日期最多针对7条历史→当前风险，不能解决来源日期错读和大多数范围外推，故停止该泛化假设，暂不耗费真实模型预算注入日期。
- Z Code Q4的13/14双轴一致是分析员模型辅助复核，不能报告为judge–人工一致率；人类裁决仍未完成。
- Q5的1.31是局部输出结构倍数估计与中位数替代的结果，不是严格tokenizer实测。没有据此更改MODEL_TOKEN_CHAR_RATIO或预算；真正预算校准仍待匹配Provider tokenizer。
- Q9已有数字：B工具4.75→4.19、正文2326→2403字符、输出4289→4394 token。不支持“B只是回答更短”解释；观察到检索行为量差异，不把相关性升级成Prompt引起遗漏的因果结论。

决策：不以修改评测标准获取分数增益；保留时间/范围诊断细节，优先验证R2已有可复现工程断层。累计DeepSeek0/250、Judge0/32。

## Q8假设进一步证伪：时间锚已送达模型

新脚本audit_time_context.py读取原64Run的第一条model.turn/model_visible_context，64/64都有“本次查询的参考时间为2026-10-28T12:00:00+08:00”。源码runner.py:170–183本来就把Case.time_context注入recent_messages。此前只搜SYSTEM_PROMPT/动态instructions而推断“模型缺少查询时点”是不完整的链路分析；本轮不重复注入已存在的信息，不花模型预算验证重复时间锚。原静态观察保留，但其推论被实际请求输入否定。

## R4：严格事实覆盖与来源存在分开

audit_failure_stages.py复用原coverage labels，148个适用criterion/run pair：A覆盖38/74，B33/74（按事实加权，与原报告Case等权52.8%/45.9%不是同一指标）；未覆盖但目标已在答案source的A3/B4，已在replayed capability但模型可见性不全的A3/B3，剩余A30/B34未在所重放lexical/semantic结果观察到目标。后者不能直接标成FTS缺陷，因为还可能涉及其他context工具、已知来源之外的替代证据或问题中的认知属性。输出保留v1/v2草稿，v2显式支持无固定target ID的标准（本批未触发）。这再次否定R1把来源ID相交叫作语义采用的口径。
