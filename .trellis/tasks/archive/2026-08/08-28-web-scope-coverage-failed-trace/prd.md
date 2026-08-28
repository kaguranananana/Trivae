# 修复 Web Scope、Coverage 与失败 Trace 恢复

## Goal

修复 Web UI 中指定群聊未进入实际 Query、独立 recent 查询被误判为 coverage 倒退、失败回答看不到已持久化 Trace 的三个真实问题，使用户选择的检索范围、最终 coverage 和失败诊断入口与后台事实一致。

## Background

- Web 启动会打开最近 conversation；该 conversation 已绑定不可变 scope。顶部 selector 更新 `scopeStore`，但 `chat.send()` 仍发送 `targetBuffer.scope`，导致用户改选 `qq:831907794` 后实际请求仍为 `all`（`App.vue:42`、`chat.ts:322`、`chat.ts:376`）。
- 真实失败 Trace `trace-5e2ed5cddf674a6ebc3fc1d6f0a7c084` 先完成 `2699/2699` 的 root recent 查询，随后执行同窗口 `60/2699` 的独立 root 查询；`evidence.py:1319` 把所有记录机械视为一条 continuation 序列并抛出 `COVERAGE_MISMATCH`。
- Trace 已在 SQLite 和文本日志持久化。Web 收到 `query.failed` 后先把 assistant 标记为 `failed`；`stream.end` 再通过 `lastRunningAssistant()` 查找时得到空值，未把 `trace_id` 附到失败卡片（`chat.ts:405`、`chat.ts:411`）。
- 现有架构明确规定 Query failed 不提交 completed Assistant row；本任务不伪造 `AnswerArtifact`，也不改变该数据库契约。

## Requirements

### R1：Scope 切换必须作用于下一次发送

- 当页面当前打开的 conversation scope 与 selector 的有效 scope 不一致时，下一次发送必须进入绑定新 scope 的 draft/new conversation。
- 不修改已有 conversation 的 scope，不通过发送旧 scope 规避后端 `SCOPE_MISMATCH`。
- 指定“一群开心快乐的小奶龙”时，请求必须携带 `mode=sessions` 和 `session_ids=[qq:831907794]`。
- 同 scope 的正常 follow-up 必须继续复用当前 conversation。

### R2：Coverage 汇总必须基于事实最大覆盖，而不是调用顺序

- 同一 Host-resolved 时间窗内，多次 recent 调用的最终 coverage 使用已证明的最大 `covered_units` 记录作为权威状态。
- 独立 root 查询返回较小样本时，不得降低此前已经证明的 coverage，也不得触发虚假的 `recent page coverage moved backwards`。
- 合法 cursor continuation、唯一消息计数、scope/time-range 冲突检查和真实 coverage mismatch 必须继续有效。
- 不增加 retry、fallback、静默降级或针对单条 Trace 的特殊规则。

### R3：失败卡片必须显示已返回的 Trace

- `query.failed` 或 `query.aborted` 已先结束 assistant 状态时，后续 `stream.end` 仍必须写入同一 owner buffer 的终态字段，包括 `trace_id`、status、error、sources/limitations。
- 已完成 Query 的现有 Trace 展示和跨 conversation stream owner 路由不得回归。
- Trace 持久化失败继续显式暴露；本任务不伪造缺失的 Trace ID。

## Acceptance Criteria

- [x] 打开一个 `all` conversation，改选 `qq:831907794` 后发送，捕获到的新 conversation 与 Query payload 均为 sessions scope。
- [x] 未改变 scope 的 follow-up 仍携带原 conversation ID，不创建新 conversation。
- [x] `2699/2699 complete` 后出现同窗口独立 `60/2699 partial` 时，finalization 不再报 coverage 倒退，最终 canonical coverage 保持 complete。
- [x] 合法多页 continuation 的 union/coverage 结果保持正确，冲突时间窗或 eligible units 仍显式失败。
- [x] 流中先出现 `query.failed`、后出现带 Trace 的 `stream.end` 时，失败 assistant 的 `traceId` 等于终态 Trace ID，UI 可渲染 TraceFooter。
- [x] Web 单测、temporal coverage 单测、相关后端回归、前端 typecheck/lint 通过。
- [x] 生成或修改的关键代码包含简体中文注释，关键判断可逐行理解。

## Out of Scope

- 不改变“失败 Query 不提交 completed User/Assistant turn”的 Conversation Store 契约。
- 不新增失败消息表、Trace 列表页或跨刷新失败 turn replay。
- 不修改模型 provider、增加模型重试或为本次问句添加特殊提示词。
- 不调整 canonical recent retrieval 容量、Tool Result token budget 或 scope 权限边界。

## Constraints

- 根因优先、错误透明、最小修复；禁止 fallback、降级、静默吞错和样例特判。
- 已有 conversation scope 保持不可变；后端 `SCOPE_MISMATCH` 校验继续作为真实边界。
- Coverage 的 Host-owned 时间窗、eligible units 与 provenance 校验继续保留。
