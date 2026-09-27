# Implementation plan

1. 核对源提交、旧 task、五次 failure observation、同轮 P0 和 prompt composition；写 `research/failure-attribution.md`。
2. 定义通用 P2 prompt 压缩，并只补足直接相关的 reasoning-token usage 投影；加入 provider-free contract tests。
3. 扩展 Planner-only runner，固定 P0/P1/P2 身份、交错 3 repeats、原始记录、指标和三路盲审。
4. 运行真实 Provider 实验；逐 Case 审阅 rubric 和重点回归，写 provisional review 与 gate 结论。失败保留，禁止 retry。
5. 运行定向与全量 pytest、Ruff、mypy、`git diff --check`；必要时只修主链路。
6. 完成 Trellis 研究/实施/验证记录，提交实现和实验产物；检查 HEAD、push 状态与工作树。

Rollback boundary: Planner prompt 与实验 runner 为独立修改；若质量或稳定性不达标，不进入 E2E，不扩大到 Runtime/Router。
