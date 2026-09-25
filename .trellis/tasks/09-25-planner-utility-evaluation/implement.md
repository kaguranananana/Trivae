# Implementation and validation plan

1. 审计 forced route、Planner/Runtime 共享链路、Runner、GT 与 Trace；冻结判定规则及身份。
2. 最小补齐 Planner operational projection 和对应有意义的测试。
3. 提交执行代码和预先冻结的实验设计，获得干净 execution commit。
4. 创建本轮 Variant/Environment manifest；对 Provider、Planner、DB、Snapshot、索引、scope、Tool、输出隔离执行 preflight。
5. 独立 smoke：不同类别各若干 Case × 2，核验路径与投影；不计入正式分母。
6. 正式 37×2×1；只在首次尝试前启动，逐条保留失败；核对 raw/Evaluation/Trace。
7. 基于主结果选择少量 Case 做独立 targeted repeat 至三轮；主分母不变。
8. 计算分类别与逐 Case 指标、Planner/Tool/latency/usage/failure；生成人工 review packet，区分自动事实和待裁决。
9. 更新实验报告、Jev ADR、Evaluation README 与必要的面试事实；验证链接和隐私边界。
10. 执行 `uv run --extra dev --with tqdm pytest -q`、`uv run --extra dev ruff check src tests`、`uv run --extra dev mypy src`、`git diff --check`、Trellis validate；提交、归档，检查 clean worktree，不 push。

预期代码改动限于 Evaluation projection 与测试；Variant、Task、ADR、README 和报告是实验身份与证据文件。若 Trace 已足够，则不扩大生产路径改动。
