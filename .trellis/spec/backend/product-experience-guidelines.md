# Product Experience Hardening Contract

> 2026-08-25 已验证的 CLI/Application 产品边界。本文只记录当前实现，不把未验证的
> provider 网络健康、质量指标或未来 UI 行为写成事实。

## 1. Scope / Trigger

- Trigger：CLI 已能进入统一 Query/Application 链路，但缺少 source review、scope/readiness、
  experiential feedback 和 history/resume 的日常闭环。
- Scope：`interfaces/cli.py`、`interfaces/cli_renderer.py`、Application read facade、
  `conversation/` scope migration、独立 `feedback/` SQLite boundary。
- Explicit non-scope：Router、Planner、Runtime、六个 canonical Tool、Retrieval ranking、
  Finalizer validation、Trace event taxonomy 与 Evaluation ground truth。

## 2. Signatures

- `TrivaeApplication.readiness() -> ApplicationReadiness`：只读 canonical count/session
  metadata、已有 semantic status 和 `load_settings()` safe provider projection。
- `TrivaeApplication.inspect_message_source(source, scope, before=2, after=2) -> tuple[MessageProjection, ...]`：
  复用 `read_message_context_scoped()`，不启动 Query/Tool/Provider。
- `TrivaeApplication.list_conversations(limit=20) -> tuple[ConversationSummary, ...]`。
- `TrivaeApplication.resume_conversation(conversation_id) -> Conversation`：scope 缺失时显式失败。
- `TrivaeApplication.save_feedback(..., rating="good"|"bad", note=None) -> FeedbackRecord`。
- `ConversationStore.create_conversation(scope=None)` 与 `list_summaries(limit=20)`。
- `SQLiteFeedbackStore` 使用相邻独立数据库；`(conversation_id, trace_id)` 唯一并 upsert。

## 3. Contracts

### CLI commands

`/scope` 只读当前 scope；`/chats` 重新选择 scope 并清空 conversation/source/feedback state；
`/new` 只清空同 scope 的 conversation；`/status` 显示 readiness 与当前 scope/conversation；
`/source n` 读取当前 finalized answer 的来源；`/good`、`/bad [note]`、`/feedback` 只作用于
最近一轮完成 Query；`/history` 展示 bounded metadata；`/resume n` 只恢复有完整 scope contract 的记录。

### Persistence fields

- `conversations.scope_snapshot_json`：新 Conversation 保存 trusted `ExecutionScope`；旧
  row 保留 `NULL`，只能列出不能恢复。
- `user_feedback`：`feedback_id`、`created_at`、`updated_at`、`conversation_id`、`trace_id`、
  `run_id`、`scope_snapshot_json`、`rating`、bounded `note`、`feedback_kind=user_experiential`。
- feedback 不写 Canonical Message、Conversation、Trace 或 Evaluation Store。

### Renderer

normal/verbose 都消费同一个 `QueryStreamEvent` 来源。normal 显示真实阶段、回答和失败的
用户投影；不显示 raw event/sequence/operation identity、JSON、provider-specific 字段或
hidden CoT。Runtime reasoning event 可以被消费以维持顺序，但不进入终端。verbose 只增加
bounded/redacted metadata，不改变执行路径。

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| source index invalid / source missing | CLI 显式提示，不执行 Query |
| source session/time outside scope | `SourceInspectionError`，不返回 context |
| structured source | 只显示 locator/value/scope/limitations summary，不伪装 message |
| legacy conversation has NULL scope | history 可见，resume 与带 id Query 显式拒绝 |
| persisted conversation scope differs | `QueryContractError` / `ConversationScopeError` |
| semantic missing/stale/failed/partial | 原状态保留，不 rebuild、不 lexical fallback |
| feedback has no completed run or scope mismatch | `FeedbackError` / `ConversationScopeError` |
| known renderer failure | 人类可理解的短提示；trace/log identity仍可用于诊断 |
| unknown exception | logging 保留 traceback；normal 只显示类型级 bounded diagnostics |

## 5. Good / Base / Bad Cases

- Good：finalized `AnswerArtifact` 的 trusted `MessageDisplaySnapshot` 生成稳定 Sources，
  `/source 1` 从 canonical same-session bounded context 返回并高亮 anchor。
- Base：空数据库 readiness 显示 `messages=0` 与 semantic `missing`；反馈重复提交更新同一
  record；history 标题使用首条 user query 的 bounded projection。
- Bad：CLI 直接读 SQLite、从模型正文拼 source metadata、把当前 scope 猜给 legacy row、
  将 good/bad 写成 Evaluation label、或把 CoT/raw JSON 当 normal 输出。

## 6. Tests Required

- `tests/test_product_experience.py`：source deterministic dedup、scope round-trip、legacy
  NULL、history title/count、feedback upsert、readiness empty/missing。
- `tests/test_cli_renderer.py`：CoT 不渲染、friendly failure、0-result、tool recovery、
  verbose 不含 stream/trace identity 和 JSON。
- `tests/test_cli.py`：既有 Query/Application facade、`/new`/scope 语义和最终答案不回退到
  runtime 原文。
- Existing full suite：Query/Evidence/Conversation/Trace/Evaluation/semantic/index 全部保留。

## 7. Wrong vs Correct

### Wrong

```python
# CLI 直接打开 SQLite，再用模型生成的 source 文本拼一个引用详情。
messages = sqlite3.connect(path).execute("SELECT * FROM messages").fetchall()
print(model_source_text)
```

### Correct

```python
# finalized source 只作为 locator 进入 Application；展示正文重新来自 trusted canonical read。
context = application.inspect_message_source(source, current_scope)
```

这样可以保持 CLI 是薄 adapter，scope/证据/持久化 ownership 仍由 Application、Finalizer、
Conversation Store 和独立 Feedback Store 分别负责。
