# 验证记录

- 原ledger从1继续，第2次真实诊断复现原MALFORMED_STREAM，完整wire后续有completed；未把诊断当有效答案或Baseline。
- 新metadata测试先2 failed/5 passed，根因是合法扩展被SDK联合类型拒绝；修复后相关68 passed（2.68s）。旧缺字段反例继续MALFORMED_STREAM并明确missing，新未知tag断言仍拒绝。
- static：Ruff、mypy128 source files通过；415 passed（9.27s）；0推理。
- 生产Prompt未改；当前真实预算2/120。

## 修复后真实协议E2E

- b669bcc，沿用原ledger追加3HTTP，总5/120；3/3完整response.completed、actual_model=gpt-6.1-sol、实际body high，metadata安全记录与函数done恢复，Usage22546input/286output/22832total，transport reasoning42。
- Agent选择lexical→semantic并完成Finalizer，但两工具因旧derived合同不就绪报CAPABILITY_UNAVAILABLE/SEMANTIC_INDEX_NOT_READY，答案明确无法确认，不能作为质量Baseline。
- 新发现：历史lexical缺current forward projection/revision/count markers；独立正确重建将增加派生forward FTS，snapshot lexical count会变化。只在副本重建、生成新真实snapshot，显式派生case identity绑定，GT/质量约束全文保持，旧Baseline一律不复用。

## 后续已完成检查

- 全量pytest：1171 passed、1 skipped（29.04秒）；独立审查68 passed，真实metadata重放/取消通过。
- 473236原生消息24字段、14来源8字段，全字段差异/新增/删除均0；副本lexical通过当前readiness，476736 FTS=473236原生+3500forward。新snapshot如实不同，不覆盖旧冻结材料。
- 16条所选Case离线GT复核全部通过：全部已标注locator可回读、3个exhaustive精确集合相等、excalidraw与2个UTC空窗仍为零；只读核验，不提前在building语义上付费。
- Router第一次ConnectError、显式一次连通性恢复后重测SSE完整（High、actual_model、metadata、Usage250/reasoning42），但ROUTER_COMPLETION_INVALID；没有把传输成功记作路由成功。Planner独立真实High请求触发原20秒completion_timeout，未改超时/策略。所有失败已计总ledger，当前8/120；不再为组件挑结果重试。

## 独立索引完成与本轮真实A/B/C结果

- v2-forward completed：473236原生/3500forward水位匹配；54651 metadata与vectors一一对应，missing/orphan0，32向量+32范围抽样有效。16派生Case正式绑定；GT/旧Snapshot/Holdout未改。
- 新快照实际8种Case/23次运行，11 completed；B01 SQL持平、C01 TS改善固定target、C02书籍改善材料/推荐者覆盖，共3有效配对，均经独立Agent完整投影/Canonical复核，不冒充新增human review。
- C02父控制和UI因网络失败未形成增量门禁，保留P33；B02无有效答案对照保留P56/P57。累计待续候选19854，生产20450不变。
- matt完整Prompt失败本地精确复现为共享投影剩134 token无法容纳最小envelope；原SDK包装UserError导致generic分类，记录既有缺口，不加预算/窗口补丁。
- macOS清空代理环境仍带系统代理，旧direct意图标签已更正；NO_PROXY实际核验API/auth AsyncConnectionPool后仍TLS start_tls ConnectError。最后UI/父控制/累计门禁连续失败，当前外部硬阻塞停止推理。
- 原总账52/120与逐阶段ledger求和52一致，余68；不是总预算耗尽。C01局部8HTTP后阻止A为0HTTP，未隐瞒；之后参数按变体数声明。
- 全阶段已返回Usage的40次实际请求下界479227 input/7155 output/486382 total/14720 cached/913 reasoning，12次Usage未知，金额未知。详见experiment-report.md及experiment/results-summary.json。
- 原封存Holdout未访问；最后4条未调参Development真实执行0，不能宣称最终质量/发布门禁通过。

- 最终按项目约定补充metadata关键行的中文解释；与b669bcc解析AST完全相等，运行行为未变；该文件Ruff再次通过，git diff --check通过。
- 独立终审核对26个总run逐项原件、新快照23/11/8、20阶段账52、Usage下界、候选父链及隐私，详见research/final-review.md；原代码身份与metadata终态说明已收窄。
