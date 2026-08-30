# Validation: Web Source Scope conversation navigation（2026-08-30）

> 所有结论基于真实代码、真实测试与真实浏览器运行。区分 `measured fact` 与 `engineering expectation`；
> 未能验证的内容明确标注。E2E 截图与请求日志见本目录 `evidence/`（32 步全通过，`e2e-results.json` 含全部 API 请求记录，console errors = 0）。

## 1. Problem / Motivation

- 原 Web Sidebar 对全局最近 100 条 Conversation 做客户端 scope 分组：当某 scope 的历史排在全局 limit 之后时会被漏掉（`GET /api/conversations?limit=100` → client filter 的确定性 Failure Case）。
- 页面打开即自动展示并打开全部最新 Conversation，Source Scope（微信群）与 AI Conversation 两级概念在导航中混在一起，范围越多 Sidebar 越乱。
- 问题归属：列表过滤属于 Conversation Store/SQLite 层（数据语义）；一级导航属于 Web navigation state（纯 UI）。

## 2. Design Rationale（problem → options → decision → trade-off）

- **列表过滤位置**：选项 A 前端分页遍历所有 scope（请求放大、语义仍错）；选项 B 前端拉全量（规模不可控）；选项 C 后端 selector filter-before-limit（design.md §4）。选 C：语义正确且一次查询完成。Trade-off：新增 bounded selector contract（`ConversationScopeSelector`），前端/后端必须同批发布。
- **unselected 状态归属**：`selectedSourceScope = null` 只是 Web navigation state，永不序列化为 `ScopeRequest`；`compileNavigationScope()` 是唯一编译函数（返回 `null` 即拒绝），删除了原 store 的 all fallback。Trade-off：调用点必须显式处理 null，换来 unselected 无法污染后端 contract。
- **draft 隔离**：draft 按 exact scope key 命名（`__draft__:` + canonical `scopeKey()`，如 `__draft__:all`、
  单 session 为 `__draft__:sessions:["<id>"]`），create await 期间切换 scope 不会把 A 的 scope 写到 B 的 draft
  （`chatStore.test.ts` create-await race 回归）。
- **URL restore**：不引入 Vue Router，窄 helper 只管理 `conversation_id` query；mount 先 load catalog → 读 detail → 恢复合法 scope → 再请求 scoped list。Detail-first 避免"先选错 scope 再打开"的闪烁与错序。

## 3. Why not（被否方案与原因）

- **把 `unselected` 加入后端 ExecutionScope**：会污染 Retrieval contract，违反 PRD R1/R4。
- **前端继续 filter 全局列表**：确定性漏数据（本任务根因），禁止。
- **多 session primary 多选器**：Out of Scope；`sessions:[A,B]` 保留 exact identity，不归入 A 或 B。
- **迁移/修补历史 scope snapshot**：immutable snapshot 原则不破坏；legacy `scope=NULL` 与 unknown session 走只读兼容。

## 4. Gates（measured fact）

| Gate | 结果 |
| --- | --- |
| `uv run pytest tests/test_conversation.py tests/test_web_server.py -q` | 35 passed（基线 19 + 新增 16） |
| `uv run pytest -q`（全量，含 CLI/TUI 回归） | 529 passed |
| `uv run ruff check src tests` / `uv run mypy src` | clean / 100 files clean |
| `pnpm test` | 55 passed / 10 files |
| `pnpm lint` / `pnpm typecheck` / `pnpm build` | 全部通过 |

关键回归（证据为测试名）：

- filter-before-limit：`test_session_selector_applies_scope_predicate_before_limit`（构造全局第 7 位的 a-old，limit=3 仍返回 3 条 A）。
- multi-session 不误配：`test_multi_session_selector_requires_full_identity_match`；legacy NULL 不进 all：`test_all_selector_excludes_session_and_legacy_rows`。
- selector 稳定错误：422 `CONVERSATION_SCOPE_SELECTOR_INVALID` / 404 `SOURCE_SESSION_NOT_FOUND`（`test_web_server.py` selector matrix）。
- ExecutionScope 字段不可穿透：`test_execution_scope_query_fields_cannot_penetrate`。
- unselected send 拒绝：`chatStore.test.ts` 'rejects sending without a selected source scope instead of falling back to all'；A→B race：`conversationsStore.test.ts` generation guard 测试。
- stream owner isolation：`chatStore.test.ts` owner buffer 回归保留 + E2E Case F。

## 5. 真实数据验证（measured fact，只读副本）

- `data/trivae.sqlite3` 分布与审计一致：legacy 78 / all 243 / single 57 / multi 0；7 个真实 session。
- 7 个 session selector 合计 56 条（57 − 1 个 unknown session ID 正确不归属任何主导航）；0 identity violation。
- all selector + limit=100 从 243 条取最新 100，排序 `updated_at DESC, conversation_id ASC` 保持。

## 6. 真实浏览器 E2E（measured fact，`trivae web --database data/trivae.sqlite3`）

32/32 步通过，console errors = 0。会话选择：A = `qq:831907794`（25 条历史）、B = `qq:1028505110`（14 条历史）。

| Case | 步骤 | 验证点 | 证据 |
| --- | --- | --- | --- |
| A 初始未选择 | 01–07 | sidebar「选择一个聊天范围以查看 AI 对话」、主区 unselected 空态、0 个 date-group/conversation、New Chat + Composer disabled、header「未选择范围」、mount 发 0 个 `/api/conversations` 请求 | `01–07-*.png` + `e2e-results.json` apiCalls |
| B session A + New Chat + 真实问题 | 08–14 | 列表请求精确为 `scope_mode=sessions&session_id=qq%3A831907794&limit=100`；New Chat 进入 draft 空态；真实 AI 查询 75s streaming 完成（Router/Planning/Thinking/Tool/Answer 正常）；URL 写入 `conversation_id`；新 conversation 出现在 A 下 | `08–14-*.png` |
| C 切换 session B | 15–18 | 请求切换为 B selector；A 的新 conversation 从 sidebar 消失；主区进入 B draft 空态；A 的问题文本不在 B 主区；URL 已清 | `15–18-*.png` |
| D 全部范围 | 19–22 | 请求为 `scope_mode=all&limit=100`；session-scoped conversation 不泄漏进 all 列表；header「全部群聊」 | `19–22-*.png` |
| E URL 恢复历史 | 23–26 | 直接打开 `/?conversation_id=<B created>`；header/scope sidebar 恢复为 session A 并高亮；历史 Question + Answer 回放；Composer enabled | `23–26-*.png` |
| F stream owner isolation | 27–32 | A 中发送长问题（streaming 中）切到 B：B 主区无 A 内容、URL 已清；切回 A 打开该 conversation：后台 stream 149s 持续写 A buffer 并最终渲染完整回答；API 层验证 B scope 列表不含该 conversation | `27–32-*.png` |

清理：E2E 创建的 2 个测试 conversation 通过正式 `DELETE /api/conversations/<id>` 删除（4 次运行共删除 6 个，全部 200；未触碰任何历史数据）。

## 7. Observability / Debugging

- E2E 全程记录 API 请求日志与 console errors（`evidence/e2e-results.json`）；每步截图。
- 后端错误走既有稳定错误信封（422/404 code），前端 catalog/list/send 错误显式渲染（`catalogError`、`readinessText`、`sendingError`），无静默吞错。

## 8. Scale / Performance

- `engineering expectation`：当前 378 行 + JSON1 predicate 无需索引；未来规模增长时先测量 `list_summaries` 查询计划，再考虑 expression index（design.md §4.3 的 reconsideration trigger）。
- `engineering expectation`：generation race guard 是 O(1) 常量开销；buffer 按 conversation 数量线性增长，与 ChatLab 形态一致。

## 9. Boundary / Ownership / Evolution

- scope identity 语义单一来源：后端 `ConversationScopeSelector` + SQLite predicate；前端 `utils/scope.ts`（`scopeKey`/`compileNavigationScope`/`restoreNavigationScope`/`navigationSelectionsEqual`）。组件与 store 不再各自实现比较逻辑。
- CLI/TUI：`list_conversations()` 无参调用保留全局列表行为（selector 可选，默认 `None`）；72 个 CLI/TUI focused tests 全绿，入口与交互未变。
- Evolution：若未来开放 multi-session primary 选择，selector 与 predicate 已支持任意非空 ID 集合，只需扩展 navigation selection UI；`SourceScopeSidebar` 是唯一需要扩展的组件。

## 10. Interview Defense Notes（事实索引）

- 为什么 filter 必须在 limit 前：`evidence/e2e-results.json` + `test_session_selector_applies_scope_predicate_before_limit`（limit=3 仍取回全局第 7 位的 A 历史是反例构造）。
- unselected 为什么不属于后端：`web/src/utils/scope.ts` `compileNavigationScope` 返回类型 `ScopeRequest | null`；store 级 send 拒绝测试。
- 如何证明 stream 不串线：Case F 步骤 27–32（切 B 6 秒后返回，A buffer 收到完整 149s stream；B scope API 列表无该 conversation）。
- immutable scope 如何保持：diff 无任何 scope UPDATE；`rename_conversation` 只写 `title_override`；E2E Case E 打开历史后 scope 恢复为只读投影。
- 已知限制：`documented in failure-cases.md` FC-3（header 与 sidebar 对 all 的措辞差异是有意保留的语境差异，非缺陷）。
