# 执行计划

1. 读取归档任务、v2 adjudication、README 与 local run ledger；确认 phase-1 commit 和当前 clean tree。
2. 完整读取相关 Project/Backend specs；定位 ChatLab checkout 并阅读相同 retrieval/runtime 职责，不假设路径或架构相同。
3. 从 canonical SQLite Trace 重建 `pu-dependent-mattpocock` Standard / Planned 两条链。再逐条重建 `dev-context-archify` Standard r1、Planned r1、Standard r2、Planned r2；保存 run/trace IDs 和每个首个差异。**已完成。**
4. 形成 `research/trace-root-cause.md`，逐层写证据、confirmed/contributing/symptom/non-cause/unknown、最早实质偏离点，以及与 ChatLab 的职责对照。根因未定位前不改代码。**已完成。**
5. 固定最小行为缺口为共享 Runtime 的 follow-up anchor 丢失：query 要保留高辨识度实体；找回复或使用反馈时要选与目标关系对应的 context anchor。明确不改 Planner、Retrieval、Evidence、zero-result contract 和自动重试。**已完成，见 `implementation.md`。**
6. 按已确认根因修改共享 Runtime prompt；新说明旁加入简体中文注释；补 provider-free deterministic prompt-contract regression。零结果主链路未改。**已完成。**
7. 执行 focused tests、完整 pytest、Ruff、mypy、`git diff --check`，并审阅 cross-layer 行为与旧 failure regressions。**已完成。**
8. 形成实现 commit；基于代码版本创建 forced-route 配对的 v3 Variant pins 与 targeted Suite，提交 execution pin；未重写 v1/v2。**已完成。**
9. 在 execution pin 捕获 Environment 并通过 gate；Variant diff、Suite/Case、Snapshot、Provider 与 output create-only preflight 均通过。**已完成。**
10. dependent 与 archify 各运行 2 组 counterbalanced paired observations；count/aggregation 与 zero-result 各运行 1 组；每批后重建 ledger，未自动 retry。**已完成。**
11. raw、Evaluation runs/results、Trace、Snapshot、Variant、forced route 身份已对齐；记录 Planner、Runtime、Retrieval、工具参数与 evaluation context 缺失。Provider invocation 为 44/102。**已完成。**
12. v3 自动指标、逐 pair assistant review、latency/token/cost 与不确定性见 `validation.md`。**已完成。**
13. 全量质量检查通过；Evaluation 文档已更新；Jev 保持 `shadow`、未访问 Holdout；代码、execution pins 与报告分别提交，最终 Trellis 收尾后核对工作树；未 push。**已完成。**
