# Web UI exploratory E2E dogfooding and failure fixes

## Goal

以真实用户视角对 Trivae 本地 Web 主链路做一轮可审计的 exploratory E2E / dogfooding：启动正式 `trivae web`，使用真实 canonical SQLite、真实语义索引、当前配置的真实 Provider 和现有 Conversation/Trace 存储，在浏览器中完成一组自然问题与 UI 操作；对实际暴露的 Failure 做复现、根因定位、最小修复、回归测试和真实浏览器复测。

本任务的成功标准是用户从页面输入问题后，能在不越权、不虚构证据的前提下得到可理解的回答，并能在同一页面验证过程、来源、覆盖边界、Conversation、Stop/刷新行为和 Trace 结果。

本任务新增一条独立的 Answer Quality / Depth Failure Case：当宽泛或多维问题已经检索到充分证据时，Final Answer 不能只给两三句空泛概括；回答深度必须随问题复杂度自适应。该问题必须通过真实 Web UI、Trace、Tool Result、final synthesis candidate、Host finalization 和 Web renderer 逐层核实，不能先假定是 Prompt 或 token budget 问题。

## Requirements

- 使用项目真实 Web 启动方式和真实运行时链路；禁止 fake provider、fake runtime、fake retrieval、fixture DB 或绕过 Web 的 API-only 代替品作为主验证。
- 在真实浏览器中覆盖约 20–30 个自然问题，至少覆盖：时间窗口/最近消息、精确关键词、中文词法、语义检索、成员查询、跨群/宽泛总结、明确无结果、带上下文追问、多轮对话、指定 Source Session 以及 Scope 切换。
- 在真实浏览器中覆盖页面行为：首次加载和 readiness、New Chat、已有 Conversation 打开、连续追问、Scope 选择、Scope 改变后的新草稿/隔离、Enter/Shift+Enter/IME 输入、流式过程和最终回答、Sources/上下文展开、Trace 入口、Stop、切换 Conversation、刷新恢复、重命名和删除。
- 每个异常都必须记录最小可复现步骤、期望/实际结果、浏览器现象、HTTP/NDJSON/Trace 证据和根因归属；没有证据的主观不适不直接改代码。
- 对 Answer Quality / Depth 单独记录 retrieval volume、model-visible Tool Result、truncation、最终 candidate claims、每个 `claim.text` 的 bounded 信息量、最终 UI 正文、独立 finding 覆盖、specificity、explanation depth、useful detail、citation coverage 和重要遗漏；不以 answer 字数单独判定质量。
- 真实测试覆盖最近两天概览、Agent/AI Coding 主题、技术资源/GitHub、某人近期主题、多方观点、讨论来龙去脉和一组结果归纳分类等复杂问题，并选择证据较丰富的 Case 做 Trivae/ChatLab 配对比较。
- 直接审计当前 ChatLab 仓库的 system prompt、tool-result 处理、agent final answer 和证据展示；只有当 ChatLab 使用相似证据给出更多有效主题、参与者、观点、上下文、资源或时间信息时，才把差异记为 Trivae Final Synthesis Failure。
- 明确区分 A Retrieval 不足、B Tool Result projection 丢信息、C final synthesis prompt 过度压缩、D Answer Candidate/Evidence Contract 限制、E Finalizer 丢正文、F Web projection/renderer 截断、G Provider 偶发过短；未经 Trace 证明不得修改 temperature、max tokens 或 Prompt。
- 修复方向优先保持 bounded Evidence Artifact，同时允许用户可见 Answer Content 按复杂度充分表达；不得用固定字数、固定 section 数、无限 token 或 universal verbose prompt 替代质量判断，也不得削弱 provenance、citation、scope、coverage、partial/truncated 和 trusted hydration。
- 修复必须保持 Application/QueryStreamAdapter/QueryStreamEvent/Conversation/Trace 单一主链路，不能在 Web 层另造检索或回答逻辑。
- 保持错误透明：不得用静默吞错、针对单个问题的特判、无依据的 fallback、降级或重试遮盖真实失败；coverage、partial、truncated、failed、aborted 等事实必须继续可见。
- 新增或修改的代码必须有简体中文注释；关键逻辑按项目约定逐行解释。新增回归测试应锁定真实 Failure 的行为契约，而不是修改测试迎合实现。
- 只记录有界的诊断信息；不得把 `.env`、Provider 凭证或未必要的真实聊天正文写入仓库。

## Acceptance Criteria

- [ ] Trellis planning 文档（PRD、设计、实施计划）完成，并得到用户对规划摘要的明确批准后才进入实现阶段。
- [ ] 真实 Web server 可在本地启动，readiness 明确显示 database、semantic、provider 状态；浏览器页面可加载且无未解释的 console error 或失败 API 请求。
- [ ] 真实浏览器完成 20–30 个问题的探索记录；每类问题都有结果状态、scope、回答/来源/限制或显式失败证据。
- [ ] 至少完成一条 3–5 轮多轮链，并验证 follow-up 沿用正确 Conversation 与 trusted Scope，不串线、不越权。
- [ ] 至少完成一次指定 Source Session 查询、一次 Scope 切换、一次已有 Conversation 恢复，确认 scope mismatch 不会把消息写入错误 Conversation。
- [ ] 至少完成一次过程展开/折叠、Tool 结构化结果、Sources/上下文入口、Trace ID/路径入口的真实验证；partial/truncated/coverage 边界在 UI 中不被误报为完整成功。
- [ ] 至少完成一次 Stop、一次页面刷新恢复和一次侧栏切换；终态、错误、interrupted 状态和后台流归属均可解释。
- [ ] 对每个确认的产品 Failure 完成根因记录、最小代码修复和回归测试，并在同一真实 Web 环境重新执行原始步骤确认修复。
- [ ] 完成独立的 Answer Quality / Depth 复现与 ChatLab 配对测试；最终报告列出过度简略 Case、Retrieval 是否充分、根因所在层、调整前后真实回答差异、ChatLab 实际差异和 contract 保持情况。
- [ ] 对确认的 brevity Failure 建立语义回归：覆盖多个独立 finding、资源名称/URL、比较双方、讨论上下文、partial limitation 和每个重要事实的 citation provenance；answer length 只能作为 diagnostic measurement。
- [ ] 通过相关定向测试、完整 Python 测试、Web 测试、类型检查、lint、ruff、mypy、compile 和 Web build；验证结果写入任务报告。
- [ ] 完成 Trellis quality check；若修复改变了项目契约，更新对应 `.trellis/spec/`，最后按用户确认的提交计划收尾。

## Notes

- 本任务是 complex task；`design.md` 和 `implement.md` 必须在 `task.py start` 前完成。
- 规划批准与浏览器 action-time confirmation 合并处理：真实问题提交会触发当前 Provider 使用真实聊天数据，开始输入前需用户明确确认。
- 真实查询执行可能产生新的本地 Conversation、Trace 和历史摘要；它们属于本轮 dogfooding 证据，收尾时只保留必要的 bounded 记录，不提交敏感原文或凭证。
