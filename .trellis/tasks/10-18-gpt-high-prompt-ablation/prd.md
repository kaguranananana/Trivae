# GPT High Prompt 受控消融

## 目标与验收
基于 main 5757327，固定 chatgpt-plan / gpt-6.1-sol / high，通过 Application.query 评估当前完整生产 Prompt 和逐组候选。新实验 HTTP 总预算 120，含失败和多轮，不复用旧 80 预算。先适配配置与 HTTP 门禁、相关测试，再 4 条真实 baseline smoke，按可用 snapshot/预算扩到约 16 个 Development case。逐条审查事实、召回、作者、时间、引用、强否定，finalizer valid 不代替语义质量。

只有同条件累计最终门禁通过才替换生产 Prompt；Provider 阻塞、重大回归、预算用尽或验证不完整则保留原文，交付实际完成与阻塞证据。不更改 GT、旧冻结记录、Holdout、OAuth、用户环境、Jev、SDK、检索/索引算法。所有私有实验材料留在 ignored data/evaluation；公开仅脱敏结论。自动提交本任务并推送。
