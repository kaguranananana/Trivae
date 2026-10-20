# 验证与验收记录

2026-10-20。基线检索代码201a81b；生产检索与Prompt未改。唯一src修改为合法80来源Snapshot的结构化身份长度和typed反序列化修复。

## 已执行

- SQLite只读backup，独立快照809850 canonical /13985 forward；源revision44070、80 sources、12 sessions、217 unexpanded节点。
- 64个Query先冻结，首次LIKE发现NUL缺陷后完整保留；另建oracle-v2，8个Reference变动、共+19 query-message pairs，Query/Scope/排序未变，修正版先冻结再重测。
- A/B全深度身份及top10、每题5次SQL计时；B64/64与生产count/top10一致。Agent adapter128 arm/case及两组session+时间Scope检查通过。
- 独立Fraction/raw-ID验证128 arm/case，所有正例Recall/Hit/MRR与现有score_ranking一致；公开summary与私有results逐字典一致。
- 44条中文/混排：2853/89346→89340/89346全深度覆盖；macro Recall@10 10.166%→14.676%；32条纯中文2454/87671→87671/87671。339 mixed额外字面匹配、3条top10退化、6条mixed FN保留。
- 独立无Agent/测试并发SQL延迟320样本/侧：median0.222750→3.157729ms，P95 10.427000→66.516584ms；FTS构建1.838630→4.842146s；130686976→179273728bytes。
- 真实官方Flash经Application.query与EvaluationRunner/SQLiteEvaluationStore：8题、15 returned+1主动中断、7完整配对、两侧各5/7成功；31次已完成run Provider requests+中断项1确认响应+最多1在途=32–33 attempts；续跑httpx2实际捕获14次200。四个failed为coverage/no-result finalization；Provider没有已记录失败。一个Trace sequence1缺失，其余2–30存在，底层原因未知。
- 完整pytest首次1186 passed/1 skipped；增加转发隔离端到端测试后专项7/7通过；最终完整pytest结果见下方收口补充。
- `uv run ruff check src tests scripts/cjk_bigram_benchmark.py scripts/cjk_bigram_agent.py scripts/cjk_bigram_report.py`通过；`uv run mypy src`128文件通过；`git diff --check`通过；新文档链接检查通过。

## 产物与限制

公开实验目录evaluation/experiments/cjk-bigram-v1，面试材料interview-docs并更新索引。私有原始Reference、正文、快照、FTS、Trace、HTTP/usage、失败样例、审核packet与完整执行源副本位于ignored data/evaluation/cjk-bigram-v1，未入Git。

没有human_verified、人工语义全库标签、付费Judge、统计独立fresh holdout、默认全工具Agent或稳定E2E uplift claim。原始counter0明确无效，不伪造精确取消请求计数/费用。所有异常根因与处理见engineering-incidents.json；已知局限未增加fallback或新策略。

## 最终质量门禁

最终完整 `uv run pytest -q`：1187 passed、1 skipped（26.77s）；ruff/mypy/diff及文档链接/公开指标一致性检查均通过。

历史证据额外审计：原trace-87060c…仍在快照，可恢复0-hit的单会话trusted Scope、archive_latest前两天[1786671390000,1786844190001)、limit30/context2、complete coverage。157/187后续smoke完整参数未恢复，不能把历史记录视为本次新结果或擅自认定与14条诊断同分母。
