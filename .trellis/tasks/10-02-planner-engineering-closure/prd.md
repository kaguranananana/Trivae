# Planner Evaluation 最终工程收口

用户已授权直接实施、限定付费验证及正常 commit/push，无需中途确认。完整约束见 user-request.md。

## 要求与验收
- 审计 2da57b9 / 23a3e9b / 361a38e / 221f57a、任务和真实失败；记录 Router low、P1 Planner none、Runtime low，保持 Thin Planner 边界。
- 结束 low/none 研究；none 只作为 completion reliability / latency 工程选择，不声称答案质量稳定优于 low。
- 模型可见 source_id 为 run-local mN-K；message_id 为 canonical internal ID。保留 canonical 能力，无 silent alias fallback；离线验证 projection/resolver/原始与 normalized Trace。
- 保存 low-r2 两个真实 canonical 时间戳及错误 Answer/Evidence，复用现有 Evaluation/Judge；稳定暴露同日/顺序错误，不能宣称通用语义 checker 已实现。
- 全量 pytest、Ruff、mypy、diff check 通过后运行 8 exposed Development Case × Standard/Planned × 1 = 16 次。同一生产 Runtime、Snapshot/GT/预算/工具/评测，新 conversation，AB/BA。
- create-only preflight 固定 commit/status/源文件逐字副本/快照/cases/GT/schema/settings/credential configured，不落盘密钥；失败零正式 attempts / Provider calls。
- 完整保存 HTTP 原始参数、normalized Tool/Trace、ToolResult、Evidence/Citation/Answer/Evaluation、真实 usage，未知金额不估算。
- 16 次后停止；仅新严重生产 regression 可对单 case 每侧追加 2 次，禁止自动补跑。
- 根据实际收益/风险/开销保留或限制使用 Planner，不强行宣称获益；更新文档、保留历史、正常提交推送并报告 ancestry。
