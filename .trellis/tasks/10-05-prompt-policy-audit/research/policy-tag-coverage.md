# A06：现有case的policy标签覆盖

Iteration ID：A06。Scope：实际case标签与targeted选择。Risk：只读低。Prompt lines：0。Owner：EvaluationCaseBundle.suite_tags / select_policy_cases。Expected/Maximum Provider calls：0/0。

实际读取并通过CaseBundle解析evaluation/cases递归64份case（包括13份design_seed），没有构造Provider或运行query。选择使用现有exact tag，不推断自然语言、添加alias/fallback或另建Suite。

| 短标签 | 选中公开case | 已有真实benchmark分类标签 | 选中case |
| --- | --- | --- | --- |
| discussion | 1，全部design_seed | category:context_recovery | 5 |
| retrieval | 2，全部design_seed | category:exact_lexical / category:semantic_paraphrase | 13 / 10 |
| recent | 2，全部design_seed | category:temporal_overview | 8 |
| no_result | 2，全部design_seed | category:zero_result | 5 |
| negative | 4 | 根据实际case的空窗/上下文边界选择，不按category自动推断negative GT | — |
| structured | 1 | citation_evidence与SQL结果/JSON输出不是同一policy，不能机械映射 | — |
| identity | 1 | 不能把所有scope/filter case当作person身份消歧 | — |
| temporal | 2 | category:temporal_overview；必要时明确指定关系case | 8 |
| inventory | 0 | exact_lexical不能全部推断为exhaustive inventory | — |

真实精确筛选命令的policy可直接用`--policy category:context_recovery`等已有tag，并显式提供1–3个最相关case路径，不能因为匹配5个就全部运行。category前缀不影响selector，实际离线选择得到上述计数，不只是字符串推测。

另有ignored历史Frozen Baseline六case：discussion/retrieval/negative 1，discussion/negative 1，inventory/retrieval/temporal 1，retrieval/identity/temporal 1，recent/temporal 1，no_result/negative 1。它们有短标签，但当前SDK合同漂移，付费前仍拒绝复用。结构contract的真实层覆盖不能用design_seed标签计数冒充；由SQL/Finalizer fixtures先做L0，真实语义case选择仍需逐个检查。

不改写已有versioned case/freeze的metadata或provenance；不把旧记录重绑到新Schema。Removed/Moved/Reworded/Added：无Prompt变化；Added仅本审计。所有高风险策略不动。接受只读审计，0新增API/tokens/cost；累计真实仍V01的2，token/费用未知。
