# 执行计划

- [x] 审计旧失败、官方/SKD类型，捕获缺失的实际metadata形状（必要时最多2次诊断，原ledger）。
- [x] 最小协议修复与相关回归；Ruff/mypy/static。
- [x] 独立当前chunker snapshot与readiness核验，不改原件。
- [ ] 真实High端到端；4条Baseline smoke；扩Development约16条，预算优先留最终配对。
- [ ] B逐组机械删除，C逐组策略；每轮查完整答案/证据，明确拒绝/通过/不确定。
- [ ] 最终累计门禁、中文报告、spec、全量测试、工作commit、journal/收尾、pushmain。

硬停仅凭据不可访问、不可消除外部阻塞、120总预算；一般实现失败自行修复重测，不降低断言或质量标准。

## 本轮执行状态（保留待续）

- SSE修复、静态/全量回归、真实High多轮已完成；独立v2-forward索引completed/integrity valid。
- 16条派生Case离线GT核验完成；真实尝试8个Case/23个run，新快照11 completed，3个有效质量pair为Agent审查2改善1持平。
- B01/P64定向通过；B02参数删文因TLS未验证而保留；实际C01为19854字符，C02的P33父控制/UI未完成而恢复。未改生产Prompt。
- 累计full-gate第一HTTP再次TLS失败；最后四条未调参Development执行0。当前52/120，所有目录ledger合计52；保留68，不再发送新请求。
- 代码/报告可交付，但原实验未全部验收。报告及机器摘要记录实际完成/失败/未执行；任务不以全部完成归档，保持当前task供网络恢复后续跑。
