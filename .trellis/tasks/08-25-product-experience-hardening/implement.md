# Implementation Plan

## Planning gate

- [x] 读取 `AGENTS.md`、Trellis workflow、project/backend specs 和 shared thinking guides。
- [x] 核对 architecture、overview、interview-defense、Stage 1.4/1.7/1.8/1.9/1.10/1.11。
- [x] 阅读并核对已归档 interactive chat CLI、interactive CLI streaming events、agent-facing
  tool surface 任务；检查当前 ChatLab CLI/Agent event design 作为 reference。
- [x] 确认当前 `main`、working tree、最近六工具 commits、真实 CLI/Application/Renderer/
  Conversation/Evidence/Trace/Semantic status contracts。
- [x] 建立 baseline：275 tests、ruff、mypy、compileall 和真实 DB/index status。
- [ ] 用户批准本次最终 planning summary 后，创建 `codex/product-experience-hardening`
  branch 并运行 `task.py start` 进入 implementation phase。

## Common implementation rules

1. 每个新增 Python 代码加入简体中文注释；关键状态转换和跨层边界逐行解释，保持现有
   Simple/Explicit/Testable 风格。
2. 先写或补充失败回归，再改主链路；不修改测试以接受错误行为，不增加无证据 fallback、
   retry、silent catch、compatibility branch 或 query-specific 特判。
3. CLI 只调用 Application facade；任何 SQLite/read/capability/runtime 访问都留在已有
   Application/Store/Read boundary。
4. 不把真实聊天正文、`.env`、secret、provider raw payload、reasoning/hidden CoT 写入
   Git、Trellis validation 或 smoke report。
5. 每个 checkpoint 结束前执行 focused tests、相关 integration/regression、真实 CLI
   smoke（若外部条件允许）、`git diff --check`，然后独立 commit；完成 checkpoint 后才
   进入下一个。

## Checkpoint A — Source / Citation drill-down

### Implementation

1. 先为 trusted source flatten、duplicate identity、Message/Structured 分支、invalid
   source 和 scope boundary 写 deterministic tests。
2. 在 query/evidence 相邻边界增加 source display projection（若已有 contract 足够则只
   增加 helper），按 finalized `AnswerArtifact` 顺序建立 display index；不改 Finalizer。
3. 在 Application 增加 bounded source inspection facade：复用 canonical read repository 的
   scoped context read，校验 anchor/session/time/returned context，StructuredSource 只返回
   summary。
4. 修改 CLI 在成功答案后显示 bounded Sources，并实现 `/source <n>`、显式 invalid index、
   source unavailable、structured summary；`/new`/scope switch 清理旧 source map。
5. 更新 Evidence/Citation、Application boundary 文档和本 checkpoint Failure Case 记录。

### Validation gate

- valid message citation、trusted metadata、target highlight、strict before/after bound；
- invalid index、missing source、scope violation、same-session/context boundary；
- structured source 不伪装 message；source review 不触发 Query/Tool/Provider；
- existing evidence/finalizer/conversation regression；
- scripted CLI smoke：Query → Sources → `/source`。

### Rollback point

回滚只删除 source display/read facade/CLI projection/tests/docs；不修改 AnswerArtifact schema、
Finalizer 或已持久化 Conversation data。

## Checkpoint B — Scope / startup / status UX

### Implementation

1. 为 `ReadinessReport` 和 Application status facade 写 ready/empty/semantic missing/stale/
   failed/provider missing/database failure tests；确认没有 rebuild、full scan 或 provider
   network call。
2. 增加 startup readiness projection 和 `/status`，复用现有 semantic status identity/状态；
   Provider 只使用现有 Settings contract 的 safe projection。
3. 将 `/scope`、`/chats` 接入现有 session picker；selection 只在 CLI state 编译 trusted
   `ExecutionScope`，不同 scope 后清理 conversation/source/feedback binding 并提示新会话。
4. 修改 Application Query 新建 Conversation 时保留 request scope，恢复 existing
   conversation 时做 exact scope compatibility check；保留 `/new` same-scope 行为。
5. 更新 Application/CLI architecture 文档和 scope pollution Failure Case regression。

### Validation gate

- single session ↔ another session、single ↔ All chats、scope switch new conversation、旧
  history/source 不污染；`/new` scope regression；
- status ready/missing/building/stale/failed/partial/provider missing/database unavailable；
- startup 与 `/status` 不自动修复 semantic index；
- scripted CLI smoke：startup → `/status` → `/scope` → `/chats` → next Query。

### Rollback point

status projection 和 CLI commands 可回滚；Conversation scope migration 必须保留向后读取
能力，若验证发现 legacy row 不能安全恢复，停止 resume 增量而只保留 `/history` blocker，
不猜 scope。

## Checkpoint C — Feedback + Conversation history/resume

### Implementation

1. 先定义 `FeedbackRecord`/`FeedbackStore` contract，写 good/bad/note/no completed run、
   upsert、identity/scope binding、not-ground-truth tests。
2. 新增独立 feedback SQLite schema/store，并在 Application composition/lifecycle 中注入；
   schema 只保存 bounded identity/metadata，不写 answer/tool payload。
3. 增加 `/good`、`/bad [note]`、`/feedback`；feedback 只能绑定最近 completed result，
   query failed/aborted/partial-not-committed 不可绑定。
4. 扩展 Conversation Store：additive nullable scope migration、summary/list contract、
   deterministic title fallback、legacy scope missing explicit error；不改 atomic turn
   commit semantics。
5. 增加 `/history`、`/resume <n>`；恢复 scope 时明确提示，mismatch/legacy/missing index
   显式失败；resume 不执行 LLM/Retrieval。
6. 更新 Conversation/feedback contract、Evaluation distinction、interview-defense 和
   validation Failure Cases。

### Validation gate

- feedback good/bad/note、重复 upsert、feedback before completed run、正确 trace/conversation/
  run/scope identity；
- independent feedback DB、Conversation atomic commit、scope round-trip、legacy null scope；
- empty/history ordering/title、valid/missing/unsafe resume、`/new` regression；
- restart/reopen Application 后 history/feedback 可读，Evaluation Store/Trace 不出现 feedback；
- scripted CLI smoke：Query → `/bad note` → `/feedback` → `/history` → `/resume` → Query。

### Rollback point

feedback store 是独立可移除 boundary；Conversation scope column 只 additive。若 resume safety
无法证明，回滚 `/resume` action，保留 `/history` 只读 projection，并在 validation 记录 blocker。

## Checkpoint D — Normal renderer / friendly failure hardening

### Implementation

1. 复现并锁定当前 normal 过载/重复状态、0-result、partial answer 后 failure、tool failure
   recovery、no reasoning、Unicode/line boundary、Ctrl+C/EOF 等 renderer cases。
2. 仅调整 `CliEventRenderer` normal projection：friendly tool/retrieval labels、bounded
   args/counts、成功冗余压缩、明确 zero/partial/failure；保留 verbose detail。
3. 增加 known error mapping 和 query/exception projection：normal 无长 traceback，verbose
   提供 bounded diagnostic reference；unknown exception 继续由 logging/Trace 显式可诊断，
   不 silent catch。
4. 确认 partial answer failure 不发 completed、不 commit；Tool error 若真实后续继续则按
   原事件顺序展示；Reasoning 只来自 Runtime normalized event。
5. 更新 Stage 1.7/1.9/1.11、Trace live/persisted boundary、renderer/failure docs，并汇总
   本轮 Failure Cases。

### Validation gate

- normal vs verbose same event sequence / same Query invocation；
- no reasoning、reasoning provider、multi-tool、0 result、known tool failure recovery、
  provider/finalizer/commit failure、answer delta、Unicode、line recovery、Ctrl+C；
- no raw runtime JSON/tool_call_id/operation id/provider-specific/hidden CoT in normal；
- full Query/Evidence/Conversation/Trace/Evaluation regression；
- real CLI smoke Case 1/2/3/4，记录 metadata-only evidence。

### Rollback point

renderer/failure projection 可单独回滚到当前同源 stream；不回滚 Runtime event source、Trace
schema、Finalizer 或 Conversation commit。

## Final quality and Trellis finish

每个 checkpoint 后至少运行：

```bash
PYTHONPATH=src .venv/bin/pytest -q <focused tests>
PYTHONPATH=src .venv/bin/pytest -q
PYTHONPATH=src .venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/mypy src
PYTHONPATH=src .venv/bin/python -m compileall -q src tests
PYTHONPATH=src .venv/bin/python -m trivae chat --help
python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-25-product-experience-hardening
git diff --check
git status --short
```

Trellis finish 前还要：

1. 对每个 Failure Case 保存复现、Trace/contract owner、root cause、最小修复、regression
   evidence；区分 real failure / regression test / anticipated risk。
2. 更新相关 spec/interview-defense，只写真实实现与验证结果。
3. 运行真实 provider + 当前 canonical DB + 当前 semantic index 的人工 CLI smoke；若配置
   或网络失败，保留 sanitized identity/failure category，不改成 mock 成功。
4. 审查 diff 中没有聊天正文、secret、`.env`、reasoning/hidden CoT，确认四个 checkpoint
   commit 和工作区状态，再执行 Trellis finish/archive。
