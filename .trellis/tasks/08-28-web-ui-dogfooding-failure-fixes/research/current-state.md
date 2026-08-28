# Current state and baseline

## 运行环境

- 日期：2026-08-28，时区 Asia/Shanghai。
- Git 基线：`main`，任务创建前工作树干净，基线提交为 `61d739b`。
- 真实数据库：`data/trivae.sqlite3`，只通过应用和只读检查确认存在；未读取或输出 `.env` 内容。
- canonical 数据规模：7 个 Source Session、473,236 条消息；已有约 343 条 AI Conversation 和 360 条 Trace。
- 真实启动命令：`uv run trivae web --no-open --database data/trivae.sqlite3 --host 127.0.0.1 --port 8710`。

## 基线质量门

任务创建前已执行并通过：

- `uv run pytest -q`：498 passed。
- `pnpm -C web test`：12 passed。
- `pnpm -C web typecheck`：通过。
- `pnpm -C web lint`：通过。
- `uv run ruff check src tests`：通过。
- `uv run mypy src`：100 个 source files 无问题。
- `python3 -m compileall -q src tests`：通过。
- `git diff --check`：通过。
- `pnpm -C web build`：Vite build 成功。

## 只读真实页面/API 观察

- `http://127.0.0.1:8710/` 页面标题为 `Trivae`，初始页面可见 `+ New Chat`、Conversation 侧栏、Scope 选择器、输入框和 Send 按钮。
- 初始页面的 Send 在空输入时 disabled；页面提示 Enter 发送、Shift+Enter 换行、Esc 停止。
- 真实 Source Session 当前为 7 个 QQ 群，包含全部聊天、指定会话两种 Scope 入口。
- `/api/readiness` 显示 database ready、semantic completed、provider ready；语义索引的 canonical/indexed message count 均为 473,236，chunk count 为 54,267。
- `/api/conversations?limit=3` 返回按更新时间倒序的 bounded summary；空 Conversation 显示为 `New conversation` / `（空对话）`，已有 Conversation 带有 title、preview、scope。
- 浏览器初始加载时无 error/warn console log；页面 DOM 有 1 个 Scope select、1 个输入 textarea 和侧栏/页面按钮。
- 初始页面侧栏一次展示大量历史 Conversation。它是后续真实用户视角下需要观察的可用性风险，但在没有滚动、切换、恢复失败证据前不作为产品 Failure。

## 当前实现边界

- Web API 在 `src/trivae/interfaces/web/routes.py`，统一挂在 `/api`；stream 由 `streaming.py` 产生 NDJSON，并调用 `application.query` 一次。
- Web request 的 scope 由 `contracts.py` 的 bounded DTO 编译为 trusted `ExecutionScope`；follow-up 会校验 Conversation scope 一致性。
- 前端的 stream owner 以 `request_id -> buffer` 归属，关键实现位于 `web/src/stores/chat.ts`；完成态以 `stream.end` 为权威。
- 前端回答、过程块、Tool result、Sources、Trace 分别由 `AssistantTurn.vue`、`BlockTool.vue`、`SourcesBlock.vue`、`TraceFooter.vue` 展示。
- 本任务已修改 final synthesis Prompt、candidate shape Trace 诊断和空 final output 的 Runtime 错误映射；真实 Provider 查询均通过 Web UI 发起。
- 本轮继续修复了两条独立运行链：资源/GitHub 清单问题即使带“最近”也先走有界的
  `lexical_search(github.com)`；成员近期主题问题由 `find_members` 的 canonical `user_id` 传入
  `get_recent_messages.sender_user_ids`，并贯穿 cursor、Structured query 和 Trace。
- `openai_adapter.py` 新增 bounded Provider transport/response-shape 观测：HTTP status、短 request/response
  标识、finish reason、stream completion、usage、output item shape 和 compatibility repair 前后 shape；不保存
  response 正文或 hidden reasoning。Runtime failure 额外携带 `exception_type`，便于区分 Provider/Runtime/Finalizer。

## Answer Quality / Depth 补充审计

- 已把 `final-answer-brevity` 建为独立 Failure Case，详细审计见 `research/final-answer-depth-audit.md`。
- 只读审计确认 `ModelAnswerClaim.text` 会直接编译为 `AnswerContentBlock.text`，再由 `AnswerArtifact.answer_text`、`answer.completed` 和 Web Markdown renderer 展示；因此当前 Prompt 的 claim-level compact/grouped/concise 约束存在直接影响用户正文的结构性可能。
- AQ6 基线 Trace 显示 semantic/lexical/context projection 没有 omission，但 final 只有 549；这是证据充分而正文过度概述的最小 Failure。
- 修复后 AQ6 为 5 claims/793 字符/29 citations，AQ7 为 6 claims/1598 字符/38 citations；candidate 与 content block 长度一致，浏览器 DOM 没有二次截断，E/F 已排除。
- 当前 Tool Result projection 继续使用 bounded token/item 预算与 `truncated`、omitted hit/context 等指标；AQ1/AQ2 等 partial/omission 仍在 limitation 中传播，未通过扩写掩盖 B。
- ChatLab 当前仓库的默认中文 Agent 明确要求复杂问题分层说明，Agent final answer 是普通自然文本，EvidenceBlock 与 prose 分开；该差异已记录为对照基线，不作为“ChatLab 一定正确”的假设。
- 已在同一真实 Web 环境完成 AQ1–AQ7；AQ6/AQ7 已完成修复后回归，AQ1 概览和简单事实问题也完成修复后重测。AQ3 资源查询一次空 final、AQ4 成员查询一次 Runtime failure 被分别记录为独立 Provider/运行链观察，不归入 brevity 根因。
- 最后一次代码重载后的 Web 复测为 AQ6 `trace-d664f68f13824ade8ab209e153ccaa0e`（4 claims/4 blocks/19 citations，0 projection omission/truncation）和简单事实 `trace-461335012f294b14826ffb574041d53b`（1 claim/224 字符/2 citations，0 omission/truncation）；Trace 同时保留 `answer_text` 与有界 `answer_shape`。
- ChatLab 直接审计和真实对照已完成；实际对照使用与本机历史数据兼容的 `chatlab-cli@0.37.0`，结果与 Trivae 的差异按有效信息覆盖而非字数解释。
- AQ3 资源修复后真实 Web Trace 为 `trace-11cea2531b6c4984b5c4dc2bf29c5456`：93/93 lexical hits、0 projection omission/truncation、Tool Result 约 17,070 tokens，最终 7 claims/1,999 字符/49 citations，valid。
- AQ4 成员修复后真实 Web Trace 为 `trace-48410dcce379492c81dbcd2566524f14`：sender-scoped recent 52/52 条、0 projection omission/truncation，最终 5 claims/676 字符/36 citations，valid。
- 修复后的质量门通过：Python 508 tests、Web 12 tests、typecheck、lint、build、Ruff、mypy、compileall、git diff check 和 Trellis validate；Trellis 校验命令为 `uv run python .trellis/scripts/task.py validate .trellis/tasks/08-28-web-ui-dogfooding-failure-fixes`。
