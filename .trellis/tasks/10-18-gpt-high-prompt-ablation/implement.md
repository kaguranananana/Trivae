# 执行计划

- [x] 审计当前 main、Provider、Screening 与历史失败。
- [ ] 复现配置/请求计数缺口；实现 High 和实验 HTTP hook、请求安全捕获、冻结身份。
- [ ] Ruff / mypy / 相关测试 / static；提交工程 checkpoint 固定实际版本。
- [ ] 新建 ignored 实验身份及总 120 ledger，确认目录 slug/snapshot，4 条 baseline smoke。
- [ ] Provider 成功则扩 Development 并构造 B/C 单组候选，逐条语义复核，失败立即拒绝候选。
- [ ] 最终同条件验收；不足则保留生产 Prompt 并报告阻塞。
- [ ] 全量回归、脱敏中文报告/spec、工作提交、归档/journal、统一 push。

停止：Provider 不兼容或授权阻塞、预算 120、重大回归拒绝候选、无法满足冻结条件；不自动重试挑结果、不换 Provider。已授权顺序推进，不逐阶段询问。
