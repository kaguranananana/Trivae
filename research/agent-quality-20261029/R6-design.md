# R6：把检索保留优先序贯穿Host预算裁剪

2026-10-30，承接R2真实Case08暴露的新Failure。源trace-5ad00d5575be431b9c5d12f61e8fdb84：semantic_search原预算10933，100条Capability→75条模型可见，25 hit省略；真实08b目标在Capability内但被Host尾裁。使用EvaluationWorkspace+本地离线embedding重放一次，持久化ToolEnvelope，重放投影与Trace的75/25/10841估算token一致。没有Agent/Judge请求。

单变量：保持该Envelope正文、候选/命中、100条集合、原预算和外部时间顺序；仅让SemanticRetrieval.primary_message_ids按既有literal→rank顺序表达，Host slot删除优先序沿用它。字面优先、来源身份、内容缩短阶梯、范围过滤、预算失败和Prompt不变。

已完成局部前后对照：原75条/估算10841、08b不可见；Candidate80条/估算10742、08b可见，预算仍10933。条数差异源自同预算中所选消息的metadata大小，不能当作性能或全局质量提升。扩展两项capability→Host回归先红后绿，相关43项通过。

广泛离线检查正在复用R1全部51个已保存ANN池；对每次同一ranked envelope分别运行旧Host与CandidateHost，预算取原Trace有效per-call值。基准中能力100条已经用R2修复，故这里隔离Host优先序。门槛：已知GT可见性净增且没有GT丢失；若有丢失则不直接保留，分析原始反例。报告区分消息可见和事实采用，保留所有结果。

若通过广泛离线与完整确定性回归，再以R2 Candidate的4题×两次=8个已完成Run为复用Baseline（同Prompt B、同模型/快照/条件），Candidate只加Host优先序，4题×两次=8个新Run/8次Judge。检查01/07/08的失效与10的回归；均为既有Eval题，不是fresh Holdout。复用Baseline避免重复消耗。与R2的总矩阵相关，不合并成独立样本。若Provider失败停止新调用，任何已完成Run不重跑。

不实施R5查询Prompt候选：确定性查询对照已显示联合命中优势，但工具schema本来已解释AND，先闭合Host真实断层；不同时改变查询策略和裁剪，避免质量收益混因。R5保留为后续独立方向。
