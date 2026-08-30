# Local Web UI Scope 展示与会话分组：实施计划

## 实施清单

- [x] 1. 创建 `codex/web-ui-scope-groups` 分支，并确认工作树只包含本任务规划文件。
- [x] 2. 新增 Scope 纯函数测试，覆盖 canonical key、集合 normalization、compact/full label、unknown ID 与 `scope=null`。
- [x] 3. 实现统一 Scope helper，并把 chat store 的 selector scope 比较复用到 helper，避免两套集合语义。
- [x] 4. 新增 conversations store 测试，覆盖 `Scope Group → Date Group`、稳定顺序、重复/乱序 session IDs 与 legacy null。
- [x] 5. 调整 scope store 与 conversations store：增加 selector 恢复/合法化 action，并使用 summary scope + SessionDTO catalog 生成双层 computed projection。
- [x] 6. 新增 App/Sidebar 组件生命周期测试，覆盖 Header 权威 scope、历史打开同步、selector change → draft、New Chat、删除当前 Conversation、active Scope Group 与既有 open/rename/delete。
- [x] 7. 调整 `App.vue` 和 `ConversationSidebar.vue`，实现“当前范围”、显式 selector 事件协调、Scope Group 标题和当前组视觉强调；保留日期分组常开。
- [x] 8. 运行定向 Vitest，修复实现根因并确认新增 Failure Case 全绿。
- [x] 9. 运行前端全量测试、typecheck、lint、build；运行 Web server/conversation Python 定向回归与 `git diff --check`。
- [x] 10. 使用 `trellis-check` 做需求、架构、代码、测试和规范审查；根据真实实现更新 Web ADR。
- [x] 11. 完成 Trellis spec 更新、提交、归档与工作日志。

## 关键验证命令

```bash
cd web && pnpm exec vitest run tests/scope.test.ts tests/scopeStore.test.ts tests/conversationsStore.test.ts tests/App.test.ts tests/ConversationSidebar.test.ts tests/chatStore.test.ts
cd web && pnpm test
cd web && pnpm typecheck
cd web && pnpm lint
cd web && pnpm build
uv run pytest tests/test_web_server.py tests/test_web_streaming_contract.py -q
git diff --check
```

测试文件名可在实现时按实际组件边界小幅调整，但覆盖项不得减少。

## 风险文件与回滚点

- `web/src/utils/scope.ts`：所有 identity/display 的单一语义来源；错误会造成分组重复或误标。
- `web/src/stores/scope.ts`：selector 合法化和历史恢复；不得把 legacy null 转成 all。
- `web/src/stores/chat.ts`：只复用 scope helper，不改变 stream owner、buffer rename 或发送主链路。
- `web/src/stores/conversations.ts`：仅做 summary computed projection，不新增请求或冗余状态。
- `web/src/App.vue`：初始化、selector change 与 Header 展示必须使用显式事件，避免 watch 循环。
- `web/src/components/sidebar/ConversationSidebar.vue`：保留 Conversation item 事件和 active highlighting。

无数据库与后端迁移，以上变更均可按前端文件级 diff 回滚。

## 开始前复核

- [x] 用户已批准本 PRD/design/implement 最新摘要。
- [x] Trellis task 已从 `planning` 激活为 `in_progress`。
- [x] 实现与检查上下文 manifest 已包含真实 spec/research 条目。
- [x] 开发前已加载相关 Trellis spec 与实现角色指令。
