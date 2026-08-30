# Implementation Plan

## 1. Baseline and contracts

- [ ] 加后端 Conversation selector domain contract 与 Store protocol tests。
- [ ] 加 SQLite all / A / B / multi / filter-before-limit regression，先让测试失败。
- [ ] 加 Web API selector matrix 与不存在 Source Session 稳定错误测试。

## 2. Backend implementation

- [ ] `SQLiteConversationStore.list_summaries` 实现 exact predicate → order → limit。
- [ ] Application facade 透传 selector，不复制匹配逻辑。
- [ ] Web GET DTO 只编译 `scope_mode/session_id`，routes 校验真实 Source Session。
- [ ] 更新 API client contract tests；确认 create/query 的 ExecutionScope DTO 不变。

## 3. Frontend domain state

- [ ] 在 shared scope helper 定义 canonical key、navigation selection 编译/恢复逻辑。
- [ ] Scope store 初始 `selectedSourceScope=null`，catalog load 不自动选择。
- [ ] Conversations store 改为 selector-scoped fetch，加入 clear + generation race guard。
- [ ] Chat store 删除 unselected→all fallback，增加 clear displayed 与 scope-keyed draft buffer。
- [ ] 加 URL query helper，覆盖合法 restore 与 legacy/unknown read-only restore。

## 4. UI composition

- [ ] 新增有独立职责的 `SourceScopeSidebar.vue`：all + real sessions + highlight/loading/error。
- [ ] `ConversationSidebar.vue` 只展示当前 Scope 下 today/yesterday/earlier，保留 preview/rename/delete/open。
- [ ] `App.vue` 编排三栏；移除顶部可写 selector，Header 改只读当前 Scope。
- [ ] Scope switch 先清主区与列表，再加载；New Chat / Composer disabled 与提示一致。

## 5. Frontend tests

- [ ] scope utility/store：initial null、compile all/session、restore、multi/unknown/null。
- [ ] conversations store：all/A 请求、A→B race、groups、rename/delete scoped refresh。
- [ ] chat store：unselected send、scope-keyed draft create race、stream owner isolation。
- [ ] components/App：highlight、unselected/empty/loading、date groups、rename/delete、New disabled、scope switch、URL restore。

## 6. Focused verification and failure repair

- [ ] `uv run pytest tests/test_conversation.py tests/test_web_server.py -q`
- [ ] `pnpm test`
- [ ] `pnpm lint`
- [ ] `pnpm typecheck`
- [ ] `pnpm build`
- [ ] 失败时复现并修主链路，不增加 fallback/静默吞错/样例特殊分支。

## 7. Real browser E2E

- [ ] 启动 `uv run trivae web --database data/trivae.sqlite3 --no-open`。
- [ ] 使用真实浏览器验证 Case A-F，并保存 API / UI / stream owner 证据。
- [ ] 为 E2E 新建的测试 Conversation 记录 ID；验证后只通过正式 delete API 删除本次测试产物。
- [ ] 验证真实 legacy/unknown scope 不被主导航误展示。

## 8. Full regression and documentation

- [ ] 全量 Python tests、ruff/mypy（按项目既有命令）、frontend 全 gates。
- [ ] CLI/TUI focused tests与 `trivae --help` / `trivae web --help`。
- [ ] 更新 `web-primary-interface.md`；写 `validation.md`、`failure-cases.md`、Interview Defense evidence。
- [ ] 使用 `trellis-check` 完成质量复核，使用 `trellis-update-spec` 校验 ADR 沉淀。

## 9. Commit and finish

- [ ] `git diff --check`、review diff、确认无无关改动。
- [ ] 创建工作 commit，记录 SHA。
- [ ] 使用 `trellis-finish-work` 归档 task、记录 journal，再创建 bookkeeping commit。

## Risky files / rollback points

- `chat.ts`：stream owner / draft rename；每次修改后先跑 `chatStore.test.ts`。
- `sqlite.py`：JSON predicate 与 limit 顺序；先跑 Store regression，再跑 API。
- `App.vue`：mount/URL/scope async ordering；组件测试后必须做真实浏览器 reload。
- API query contract：frontend/backend 必须同批提交；不做双 contract fallback。
