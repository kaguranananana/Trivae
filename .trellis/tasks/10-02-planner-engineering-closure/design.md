# 设计与变更边界

最小差距：ToolResult 公开短 source handle，但 context schema 两字段无 description、Tool description 合并称 message_id or source_id。行为归属 SDK adapter/prompt；resolver 已正确，不改它。其次真实正确日期被 synthesis 写成同日；确定性 Finalizer 只证明 provenance，不验证语义。

修改 openai_tools.py：使用 Pydantic Annotated Field 为 SDK generated schema 指定独立英文说明，source_id 优先列出；不按字符串形状猜 ID。prompt.py 同步身份契约并要求 Answer/finding/criterion 的时间关系来自 canonical 时间事实。测试走生产 SDK 与真实本地 canonical 存储，比较原始模型调用与 normalized Tool trace。

Evaluation：保存原 low-r2 的错误 artifact 与两个完整 source facts；既有 Tier 2 Judge 的 evidence excerpt 目前仅正文，缺少时间元数据，补 canonical timestamp，支持现有 grounded claim 检查；source review packet 单列 sender 身份。回归包记录显式 relation 判断、旧错误和正确对照，离线核对日期与评审输入，不引入 NLI/语义硬拒绝/第二套评分。自动测试不能证明模型永不写错，最终逐 claim 复核。

新增 final closure runner 复用历史 HTTPRecorder/usage/EvaluationRunner 和现有 production override。两路只切 forced route，生产 SoftPlanner 调用独立 none boundary。不注入重新生成的研究 Planner、不复制 SDK loop。预检用 MockTransport 检查真实 Planner 请求及两个 Agent builder 的相同初始输入/参数/schema；Planned 后续唯一允许增加生产 rendered guidance。首次真实 HTTP 再核对。

仅写新目录，不改历史 artifact/GT；逐字副本作为身份，无哈希。预算固定 16 次，不自动 repeats。未来仅真实新严重 Failure Case 可重开。Provider cache 保持现状、counterbalance 后仍有顺序不确定性。评审由 root 完整事实核对，明确非 human/独立盲审。

## 关键模块七问
职责：表达身份与来源关系；失败：参数混用/错误时间推断；观测：raw HTTP + normalized Trace + citation；归因：adapter contract 表达与 Evidence/Answer synthesis；决策：局部说明/来源日期投影，拒绝 silent alias 和复杂 engine；验证：SDK/本地存储/时间 fixture/全量检查/16 E2E；回归：历史原始事实保持，并将时间关系作为收口审核重点。

## 最终状态（2026-10-03）

设计已按此边界完成。正式16次/54 HTTP后关闭，未追加repeat；当前架构保留，路由继续保守，Jev shadow未变。source contract观察成功，语义关系/required-context风险继续显式保留；结论与停止判断见report.md。
