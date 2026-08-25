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

`trivae chat` 默认从当前工作目录自动加载存在的 `.env`；`--env-file PATH` 可显式指定
配置文件，进程环境变量优先，dotenv 解析失败要在启动时明确提示且不打印密钥。
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

## 8. Answer Evidence and Process Projection（2026-08-25）

### 1. Scope / Trigger

- Trigger：真实用户查询需要在答案层直接看到“claim 依据、来源、URL、局限”，同时要求过程展示
  接近 ChatLab 的可审计阶段，而不是输出 provider scratchpad。
- Scope：`CliEventRenderer`、CLI Answer/Sources projection、`MessageDisplaySnapshot.urls` 和
  QueryStreamAdapter 的 provisional answer 边界。
- Boundary：CLI 不读 SQLite、不重新执行 Query、不从模型正文猜 trusted URL；Evidence ownership
  仍归 `query/evidence.py`，CLI 只渲染 validated Artifact。

### 2. Signatures

```python
def _print_evidence_block(
    artifact: AnswerArtifact,
    source_summaries: tuple[AnswerSourceSummary, ...],
    *,
    output_fn: Callable[[str], None],
) -> None: ...

def _print_source_block(
    source_summaries: tuple[AnswerSourceSummary, ...],
    *,
    output_fn: Callable[[str], None],
    verbose: bool,
) -> None: ...
```

### 3. Contracts

- 成功答案顺序为 `Answer` → `Evidence` → `Sources` → `Note: answer limitations`；Evidence 展示
  `Claim → evidence_id`、`Finding`、`Criterion`、`Sufficiency`、source index 和 limitations。
- Message Source 展示 trusted session/author/timestamp/excerpt，并逐条展示 canonical snapshot URL；
  Structured Source 展示 locator/value/source_id，URL 只从 trusted value 提取。
- normal/verbose 都不渲染任何 provider reasoning 文本；真实过程只来自 Route、Plan、Tool、
  Retrieval、Evidence normalized facts。Tool turn 的模型说明不能标为 Answer。
- `AnswerArtifact` 未 validated 或 Query failed 时不展示 Evidence/Sources，不产生 commit 或 feedback
  target；错误显示 owner error 与 Trace/log identity。

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| validated Artifact 无 Evidence | 不展示空 Evidence block；Tool-backed answer 在 Finalizer 层已失败 |
| Message snapshot 有 URL | 输出 bounded `URL:` 行，不访问 DB |
| Structured source | 输出 `Value` / `Source ID` / URL，不能伪装成 message |
| provider reasoning delta | 消费顺序但终端无输出 |
| Tool turn provisional text | 不显示为 Answer；只显示真实 Action/Retrieval 行 |
| query/finalization failure | 关闭文本段并输出短错误；不输出正式成功标志 |

### 5. Good / Base / Bad Cases

- Good：`Claim claim-1 → e1` 下显示 criterion/sufficiency，Sources 1 显示实际 GitHub URL，用户可
  用 `/source 1` 继续复核。
- Base：partial retrieval 在 Evidence limitation 与 Note 中明确标记，不把部分列表说成穷尽结果。
- Bad：CLI 从回答正文正则 URL、从 SQLite 二次查询补 source，或显示 `Thinking:` 加 provider reasoning。

### 6. Tests Required

- CLI：成功 Artifact 的 claim/evidence/source/URL/limitation 输出、friendly finalization errors、
  no raw runtime answer fallback。
- Renderer：reasoning summary 不渲染、Tool recovery、0-result、verbose 不含 raw JSON/trace identity。
- Streaming：Tool-turn provisional text 不投影，最终无 Tool turn 才发 answer delta；失败不发
  answer.completed。

### 7. Wrong vs Correct

#### Wrong

```python
print(model_answer_text)
print(re.findall(r"https?://...", model_answer_text))
```

#### Correct

```python
artifact = result.answer_artifact
source_summaries = answer_source_summaries(artifact)
_print_evidence_block(artifact, source_summaries, output_fn=output_fn)
_print_source_block(source_summaries, output_fn=output_fn, verbose=verbose)
```

展示只接受 Finalizer 已 hydrate 的 Artifact；过程只投影真实事件，不制造“正在思考”的叙述。

## 9. Resource inventory result bound（2026-08-25）

### 1. Scope / Trigger

- Trigger：用户真实检索命中 31 条 GitHub 链接，但旧默认只返回 20 条，答案因此无法覆盖完整命中并
  可能把有限输出预算耗在重复链接上。
- Scope：资源/仓库/Skill 类查询的检索默认值、宽范围上下文策略、最终答案 artifact 预算和 CLI 事实
  展示。
- Boundary：CLI 不自行补检索、不读取数据库、不把 100 当成无限制；只展示同一 Query 的 finalized
  Artifact 和 normalized retrieval facts。

### 2. Contracts

- lexical 默认结果上限为共享 bounded `DEFAULT_RESULT_LIMIT=100`；在 100 以内的命中必须能够全部进入
  hits，超过时必须保留 total/returned/truncated 边界。
- 宽范围资源清单使用 `limit=trusted maximum`、`context_before=0`、`context_after=0`；解释单条命中
  时才请求局部上下文。
- 最终答案必须包含具体 URL（若 trusted message 有 URL）、claim→evidence→source 关系、sufficiency
  和 limitations；群聊提及与价值验证必须分开表达。
- 宽清单以有限代表性 URL 加剩余数量呈现；模型先闭合 `claims`，Host 再生成
  `evidence_items`/`citation_bindings`，不因追求穷举而提交无证据的半截答案。
- 模型只提交当前 Tool Result projection 的短 source handle；Host 保存完整 ToolEnvelope、解析
  archive-relative 时间、生成 artifact/evidence/binding ID，并在 finalized Artifact 中保留 trusted
  URL/value。CLI 不让模型正文或本地当前时间成为 metadata authority。

### 3. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| 31 条命中、trusted limit 100、零上下文 | CLI 显示 31/31，不显示默认 20 截断 |
| 超过 100 条命中 | Evidence/Note 明确显示 partial/truncated 和 returned/total |
| finalizer 缺 evidence 或 citation | Query 失败，不显示 provisional answer，不创建 commit/feedback |
| trusted source 有 URL | Sources 展示 canonical URL，不从答案正文正则补 URL |

### 4. Tests Required

- Capability/Runtime：31-hit regression、共享 limit schema、资源清单 prompt 的零上下文和证据优先规则。
- CLI/Trace：真实 successful smoke 终态 completed、retrieval partial/truncated 为 0、citation unresolved
  为 0，并显示具体 URL/Sources。
- Quality gates：全量测试、静态检查、类型检查、Trellis validation 和 `git diff --check`。

### 5. Wrong vs Correct

#### Wrong

```text
31 hits / 20 returned
```

只报告 total 而没有扩大共享结果边界，用户仍无法定位其余资源。

#### Correct

```text
31 hits / 31 returned
Evidence: claim-1 → e1
Sources: canonical message URLs
```

用户可看到完整命中统计、有限但具体的链接、来源和边界说明；默认仍保持有界，避免大库查询把模型
上下文和输出拖垮。
