# 2026-10-06：P16连续预算验证收口

本批从main e48a852继续，未新建任务。production Prompt与9256550/起点文件逐字相等，起始/最终均20,450字符。P01–P16与C17–C23/H06–H08/A05–A06、早期34%大改失败全部保留。本批没有任何生产Prompt删除；release gate未开始，不能说通过。

## 候选与真实结果

| 累计范围 | 字符 | 决定 | 主要证据 |
| --- | ---: | --- | --- |
| P01–P16 | 19736 | Rejected | discussion错误附和；单case+2有未经完整线程覆盖的唯一推荐判断 |
| P01–P08 | 20054 | Rejected | 书目保留，但唯一材料/此后无新教程超出有限窗口证明 |
| P01–P04 | 20207 | Rejected | exact/zero/overview/discussion有通过；UI两侧漏GT，补C24后恢复；inventory cutoff与正文更晚消息矛盾，且漏用户start_timestamp |
| P01–P02 | 20286 | Rejected | 4位分享者实际3 canonical user_id；GitHub命中最新日期误作archive_latest |
| P01 | 20346 | Rejected | Baseline使用用户起点，candidate未传start_timestamp，读取56条再过滤而非要求的10条窗口 |

拒绝的是完整候选的行为筛选，不推翻P0合法性测试，也不证明某一删句为因果。保留Model承担的P07时窗、P23–25讨论、P44–45时间/关系、P46–49归属、P50强负面、P75–92输出/覆盖等原策略。当前行为波动/错误不能由参数Schema或citation valid消除。P01“最后一条相关”可能指返回数组顺序，不把这一歧义冒充已证明的时间最大值错误。

## 修复与实验能力

H09：原HTTP budget hook增加顺序跨轮总ledger，在send前占用，local与total同时约束；两个实例耗尽测试证明不能清零/扩大。H10：paired-targeted复用现有full-gate paired执行引擎/生产Application，无新Agent。候选及Baseline除Prompt外conditions一致；C24改变Schema说明后拒用旧合同的freeze，改用fresh pair。

C24：共享lexical keyword字段说明公开既有空白分词AND语义、不要求相邻或同顺序；没有新增检索实现/guard/fallback或特定案例词。四消息SQLite fixture验证单词排除/非相邻/逆序命中，两SDK名称验证Schema。真实UI首probe提出UI skill组合，fresh pair两侧GT推荐/第三人评价都进入模型及答案。它是合理contract说明与本次恢复证据，单组不能证明稳定因果。仍有近似semantic重查，不虚报效率收益。

索引root核实：semantic_index_state=completed、473236/473236消息、54267 chunks，GT所在chunk存在；partial来自bounded pool/expansion，不应按basis名称推断缺索引。skill628取100遗漏GT，ui260取100也遗漏；ui skill只有3命中含GT。HF元数据SSL请求曾拖慢首次加载，官方同缓存offline预加载成功，两侧同encoder身份，无数据/向量更换或重建。

## 证据和预算

全部真实执行通过TrivaeApplication.query/EvaluationRunner，标准route、同DeepSeek/deepseek-flash、snapshot/scope/tool/result/output预算，不改Benchmark/GT/Finalizer。公开A06 category exact_lexical/zero_result/temporal_overview/context_recovery与既有本地discussion/inventory CaseBundle覆盖六领域。后两者GT为空，用read-only canonical人工核实，不冒充人工标注/盲holdout。

新增58/80 HTTP；57为E2E中的模型请求，1为first-tool probe。input 1,245,957；output47,594；total1,293,551；cached input328,960。全部run usage已获得；金钱费用未可靠获得。run wall累计475.442s含HF网络等待/encoder冷启动，不能当配对效率收益。历史V01的2HTTP不计入本批，旧丢失tokens仍unknown。

每轮详情见optimization-log、loop-20261006-usage.json。完整原件位于本机ignored data/evaluation/prompt-loop-20261006，包含独立目录的requests、Trace/SQLite、answer/evidence、comparison、review/correction；不覆盖原pending或旧失败Provider记录。共享total-budget.json保留58，不能清零重启预算。

## 停止与后续

满足用户停止条件3：五个累计范围依次无法通过。四领域错误在Model语义职责（范围、关系、negative、数量/时间合成）；静态owner完整并不构成删除后行为等价证明。仍无单句因果定位，不能把问题说成已证明“所有剩余机械规则不可删”。不再用剩余22请求做盲目删词/重跑；production保留最后稳定原Base，不启动不可信发布。

下一轮最小可行工作是独立研究范围与结果排序/最高时间的Model误用，以及非exhaustive证据的负面语义；先冻结同条件、人工确认GT的强Baseline再改一个责任点。URL/作者去重与时间最大值若工程上能由Host提供明确事实，可以独立审计现有元数据合同；不得用regex修正文、专用关键词或放宽GT弥补。当前任务仍in_progress，不归档、不丢历史。

工程验证：static311（3.00s）、full pytest921（17.53s）、Ruff/mypy116通过。工作commit在journal前，统一push main；push结果另记。production Prompt最后变更commit为460259d（9256550是文件相同的审计checkpoint），C24代码commit3ec4631仅工具说明。没有新production Prompt commit。
