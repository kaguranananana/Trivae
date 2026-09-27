# Implementation plan

1. 保存当前代码、Case 和 ChatLab baseline 研究；冻结 P0 prompt 与 Development suite 身份。
2. 在 Registry 提供 canonical metadata 投影，Application 默认构造 Planner 时注入；修改 Planner prompt 与 summary。保持 QueryContext、Plan schema 和 Runtime 接线原样。
3. 增加 provider-free contract tests：summary/allowlist、entity/context/overplanning rules、既有 invalid output、未知 Tool、bound、Router/zero-result 回归。
4. 建立 Planner-only runner 与 blind packet；在已暴露 Development Case 运行 P0/P1 repeats，记录每次 Provider observation 和显式失败。
5. 对八项 rubric 做 assistant provisional review，逐项报告六个已知输出和剩余失败，不伪装人类裁决。
6. 运行 `pytest -q`、`ruff check src tests`、`mypy src`、`git diff --check`；更新 validation 和必要规范，提交本任务修改，不 push。

## 回退点

若 provider 不可用，保留 runner、准备好的 suite、静态测试和失败观测，明确实验未完成；不伪造结果。若 P1 质量无增益，保留真实结果并停止 E2E，不加 case-specific patch。
