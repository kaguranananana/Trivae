# Runtime Prompt 分层、去重与配对验证

## 目标与用户价值

依据用户粘贴的 Prompt 膨胀分析，对当前 Runtime `SYSTEM_PROMPT` 做逐条职责审计，再形成可评审的等价重构计划。减少重复和维护成本，同时保留既有讨论调查、资源清单、时间、身份、引用与零结果行为。

## 本轮范围

- 将当前规则标注为 `KEEP_IN_PROMPT / MOVE_TO_TOOL_SCHEMA / MOVE_TO_RUNTIME / MOVE_TO_FINALIZER / DEDUP / EVAL_ONLY`。
- 每项迁移建议说明现有承接代码、缺口和删除前提，区别硬约束与模型决策知识。
- 核对实际 provider 请求、SDK Schema、Host 校验、Finalizer 与既有 Evaluation。
- 产出审计、技术设计、执行计划与真实验证记录。审计阶段保持 planning；用户批准第一批实施后，按下列已确认范围实现，不改历史实验结果。

## 已确认事实

- 用户已同意登记 Trellis 任务；随后明确批准“按照你的方案实现”，并要求不要使用子代理。
- 基线 commit 为 `460259d`；`SYSTEM_PROMPT` 实测为 20,450 字符。
- 当前请求使用 `response_format={"type":"json_object"}`，未提供完整 Structured Output JSON Schema。
- SDK 工具均为 non-strict；部分参数的上下界和互斥仅由 Host 校验。
- 讨论调查修复已有真实配对结果，但存在负面结论、范围一致性与日期关系反例。

## 验收标准

1. 审计覆盖 `prompt.py` 当前字符串所有规则，保留原位置并明确分类、承接点和风险。
2. 不把尚不存在的 Schema 或 Runtime guard 当成迁移已完成；不把来源校验当成语义正确。
3. 设计说明保留的稳定 Policy 层级、最小去重方案及后续下沉条件。
4. 执行计划包含现有契约测试和真实 Development 配对评测；静态测试不能替代模型行为验收。
5. 本轮文档链接、引用、覆盖与 diff 检查通过；相关 provider-free 基线测试结果如实记录。
6. 仅提交本任务文件并推送当前 upstream；产品实现已由用户批准；真实评测通过后收尾。

## 非目标

更换模型或 provider、增加工具/依赖、修改 Planner 生产策略、调整轮次/预算/默认窗口、引入重试或降级、自然语言日期解析、把语义结论改成关键词判断、运行 sealed Holdout、追求固定字符数。

## 已确认决策

建议第一批仅做 Markdown 分层、语义去重与已承接说明的压缩，保留现有 JSON 输出契约；Schema 能力补齐和 Structured Outputs 作为后续独立变量。用户已确认第一批范围，任务已进入 in_progress。

## 第一批实施验收

- Markdown 分层与策略去重，保留已确认工具、Host、JSON mode 与生成契约。
- 可按同义策略更新纯文案断言，真实参数/来源/结果测试不放宽。
- 相关与全量 pytest、Ruff/mypy 通过；相同初始请求契约下进行实际 Development 配对，保留全部失败与质量限制。
- 不使用子代理。

## 2026-10-06：低成本小步优化（本轮用户直接授权）

旧大改计划与默认付费配对不再用于本轮。主会话直接实施，沿用 in_progress task，保留历史失败与完整候选。

最小缺口：现有 EvaluationRunner 默认 repetitions=1、支持生产 query 与冻结 snapshot，但没有 policy 筛选、冻结结果复用、probe 提前终止和硬 Provider 计数。复用 suite_tags、EvaluationRun/Trace/Review，不建第二套 Agent。实验 runtime 子类只在既有 builder 注入候选及首调用拦截，正式 runtime 不增加 mode 分支。

预期文件：新增 prompt screening module/CLI、fixture/tests、责任矩阵和迭代日志；P01 仅 lexical limit 契约与独立候选。逐字保护讨论/negative/time/stop/routing，默认窗口、预算、Provider、Finalizer 不改。

关键模块七问：输入是当前 case/query/scope/snapshot 与生产 Prompt；输出是可复核 screening artifacts；依赖正式 Application.query 与既有 SDK/Trace；成功是明确拒绝非法 limit、预算内执行与可复用冻结结果，不宣称语义等价；失败保留原异常/Trace、不得覆盖 artifacts；验证由真实 SDK/SQLite、ScriptedModel 与 fixture 完成；演进只在受影响 policy 的最低 tier，release 才 fresh paired gate。

分离提交：A00 只读审计；H01 评估能力；F01 fixture；P01 一个参数职责迁移。每轮真实 API 预计/最多均 0。Prompt 候选在 L0 接受后仍需 release gate，不替换 production。禁止使用之前失败候选作 baseline。

## 2026-10-06：80新增HTTP请求连续循环（用户重新授权）

沿用P01–P16/C17–C23/H06–H08/A05–A06与全部历史失败，不启动新设计。先验证P16，真实Application.query单变量相同条件，至少覆盖exact/temporal/context/zero/discussion-recommendation/inventory；targeted后必须fresh paired release才替换production。成功提交新Base后自动下一项；失败留Trace/根因定位并修订。全部新请求硬上限80，历史V01两次不计入。只在80耗尽、无可优化规则、连续5候选高风险失败、不可合理修复环境/正确性blocker时终止；不在每轮询问。总预算通过既有HTTP hook的共享ledger落实，顺序实验计数，不并行Agent或第二套Harness。
