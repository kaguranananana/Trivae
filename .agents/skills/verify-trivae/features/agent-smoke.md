# 真实模型 Agent Smoke（按需付费）

**入口：** `.agents/skills/verify-trivae/verify-agent.sh` 默认只打印说明。需要显式配置 API-compatible Provider、`TRIVAE_VERIFY_ALLOW_SPEND=YES` 和 `--run`。

**场景：** 独立合成 QQ 群消息，其中原分享与直接使用反馈相隔 143 条；真实 Agent 执行生产 Application Query，自主调用工具，检查 Finalizer 来源绑定到 `qq:100:reply`，保存安全元数据和 Trace ID。

**范围：** 单查询、Standard Route、最多 4 模型轮次、2 工具轮次、每轮最多 1200 输出 token，120 秒超时，不执行 Judge 或完整 Benchmark。

**证明：** 模型在本次固定样本上能否返回正确引用；不证明整体 Groundedness、工具选择充分性或 Holdout 性能。需要这些指标时使用已有 Evaluation Harness 的冻结 Case/Variant/Snapshot 和 Benchmark 工具。

**费用：** 运行前需用户明确同意；模型与 API 价格不同，不承诺金额上限，不自动调用任何连接账户、真实数据库或外部 Provider。
