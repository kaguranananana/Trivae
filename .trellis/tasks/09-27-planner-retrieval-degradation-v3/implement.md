# 执行计划

1. 读取归档任务、v2 adjudication、README 与 local run ledger；确认 phase-1 commit 和当前 clean tree。
2. 完整读取相关 Project/Backend specs；定位 ChatLab checkout 并阅读相同 retrieval/runtime 职责，不假设路径或架构相同。
3. 从 canonical SQLite Trace 重建 `pu-dependent-mattpocock` Standard / Planned 两条链。再逐条重建 `dev-context-archify` Standard r1、Planned r1、Standard r2、Planned r2；保存 run/trace IDs 和每个首个差异。**已完成。**
4. 形成 `research/trace-root-cause.md`，逐层写证据、confirmed/contributing/symptom/non-cause/unknown、最早实质偏离点，以及与 ChatLab 的职责对照。根因未定位前不改代码。**已完成。**
5. 固定最小行为缺口为共享 Runtime 的 follow-up anchor 丢失：query 要保留高辨识度实体；找回复或使用反馈时要选与目标关系对应的 context anchor。明确不改 Planner、Retrieval、Evidence、zero-result contract 和自动重试。**已完成，见 `implementation.md`。**
6. 按已确认根因修改共享 Runtime prompt；新说明旁加入简体中文注释；补 provider-free deterministic prompt-contract regression。零结果主链路不修改，后续验证仍运行其现有回归。
7. 执行相关 focused tests、完整 pytest、Ruff、mypy、`git diff --check`，修复实现问题后重跑；审阅 cross-layer 行为与所有旧 failure regressions。
8. 形成实现 commit。基于该代码 commit 创建两个 forced-route 完全配对的 v3 Variant pins 和 targeted Suite 定义，提交干净 execution pin commit；不重写 v1/v2。
9. 在新 execution commit 捕获 Environment 并 gate；执行 Variant diff、Suite/Case、Snapshot、Provider 与 output create-only preflight。若 gate 失败，定位并修复身份问题后创建新的 clean pin，再重新 capture/gate。
10. 运行 focus suite：dependent 与 archify 各 2 组 paired observation，counterbalanced；每批后重建 ledger。若未出现异常增长，再跑 1 对 count/aggregation control 与 1 对 zero-result control。Provider failure 照记且不自动重试。
11. 对齐 raw、Evaluation runs/results、Trace、Snapshot、Variant、route；记录每个 batch 的 provider failure / planner failure / runtime failure / retrieval failure / truncation / evaluation failure。新调用总量不得超过 102。
12. 汇总 v3 自动指标、逐 run 人工 review、latency/token/cost，更新 `research/` 与 task `validation.md`，回答哪些假设被证伪、utility 是否改变及其不确定性。
13. 运行 task 要求的全量检查，更新必要 Evaluation/任务状态文档，保留 Jev `shadow`、不做 Holdout。分逻辑提交代码、执行 pins 与最终报告，最后核对 git status；不 push。
