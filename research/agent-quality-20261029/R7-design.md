# R7：比较问题先检索联合提及（预注册候选，尚未调用模型）

2026-10-30。来自R2真实Case08：两次独立单词搜索各前100条均无两条GT，而联合Kimi DeepSeek的79条包含两条；Case07同样单词各前100均无目标，联合MCP Skills的87条含1条。确定性结果见conjunctive-query-audit.json。工具schema本来说明空白词AND，但主Prompt的“topic-wide broad recall”没有单独说明比较意图。此处验证的是比较调查策略，不引入查询改写器或实体规则。

Candidate只在现有Prompt B最后增加一句通用策略：For a question explicitly comparing named alternatives or asking whether anyone used both, start with a lexical_search keyword containing their names together; whitespace-separated terms use AND matching to find joint mentions.

不硬编码Kimi/MCP或Case ID，不改变工具、语义/Host优先序、预算、模型、Scope、Judge v2.1、GT或旧覆盖状态。Prompt保存为新文件；产品SYSTEM_PROMPT不改。

基准复用R6完整Host候选的Case07/08各两次，不重新跑已完成基准；Candidate对同两题各两次，最多4新Run/4Judge。观察首轮联合提及检索是否稳定出现、冻结事实清单的完整覆盖和来源属性、Judge可信度及执行失败。若策略没有重复起效、关键事实无增益或任何重要退化，不保留该Prompt，停止同一方向微调。

若两题关键事实改善且未退化，再用01/10各两次检查原本不涉及具名比较的问题，共再4新Run/4Judge；这两题同样复用R6基准。累计新Judge最多8，R2的15+R6最多8+R7最多8=31，仍在整项32次累计限制内。DeepSeek仍受250实际HTTP累计门禁。任何失败保留、不补跑，不换Provider，不按结果改判分标准。

这是同一Eval v1内的定向开发与回归，不是fresh Holdout；结果只允许相应样本结论。若无稳定收益，后续方向是独立任务证据和来源语义，而不是继续叠提示词。
