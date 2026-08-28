# 修复 Web Scope、Coverage 与失败 Trace 恢复：实施计划

## 实施清单

- [x] 1. 在 `chatStore.test.ts` 增加 scope mismatch 与失败 Trace 的红色回归用例。
- [x] 2. 在 `chat.ts` 增加 scope 等价判断；scope 不一致时切换到新 draft，同 scope 保持 follow-up。
- [x] 3. 调整 `stream.end` assistant 查找逻辑，使先收到 `query.failed/query.aborted` 时仍附加 Trace 终态。
- [x] 4. 在 `test_temporal_overview_coverage.py` 增加 complete root + smaller independent root 的真实 Failure Case 回归。
- [x] 5. 在 `evidence.py` 以最大已证明 coverage 汇总同窗 records，保留现有冲突校验与唯一消息计数。
- [x] 6. 运行定向测试并检查新增测试修改前红、修改后绿。
- [x] 7. 运行 `pnpm test`、`pnpm typecheck`、`pnpm lint`。
- [x] 8. 运行 temporal/evidence/web Python 回归及项目规定的质量检查。
- [x] 9. 使用 `trellis-check` 做 spec、实现和测试复核；清理临时诊断产物。

## 关键验证命令

```bash
cd web && pnpm exec vitest run tests/chatStore.test.ts
uv run pytest tests/test_temporal_overview_coverage.py tests/test_evidence.py tests/test_web_streaming_contract.py tests/test_web_server.py
cd web && pnpm test && pnpm typecheck && pnpm lint
```

## 风险与回滚点

- `chat.ts`：scope 比较错误会导致不必要的新 conversation；用 same-scope follow-up 测试锁定。
- `evidence.py`：coverage 选择错误可能误报 complete；保留 invariant 校验并覆盖 partial/continuation 测试。
- `stream.end`：错误关联可能写入错误 buffer；沿用现有 request owner buffer，测试跨 conversation routing。
- 无 schema migration；每一步均可按文件级 diff 回滚。

## 实施与验证记录

### 修改前红色基线

- `pnpm exec vitest run tests/chatStore.test.ts`：6 项中 2 项失败。scope mismatch 仍发送
  `conversation_id=conv-all, mode=all`；`query.failed → stream.end` 后 `traceId` 仍为 `null`。
  初版 same-scope fixture 未包含真实 API 投影的默认字段，因此当时通过但不足以证明真实 follow-up。
- `uv run pytest tests/test_temporal_overview_coverage.py -q`：23 项中新增的独立 root 回归失败，
  明确抛出 `COVERAGE_MISMATCH: recent page coverage moved backwards`；其余 22 项通过。
- 独立审查后把 same-scope fixture 改为真实 conversation DTO 形状：显式
  `max_results=5000`、`start_timestamp=null`、`end_timestamp=null`，selector 请求仍省略默认字段。
  修改前该用例按预期失败为 `createCount=1`，复现了 follow-up 被错误拆成新 conversation。

### 修改后验证

- `pnpm exec vitest run tests/chatStore.test.ts`：评审补充 aborted 终态与错误去重回归后 7 passed。
- `uv run pytest tests/test_temporal_overview_coverage.py -q`：23 passed。
- `uv run pytest tests/test_temporal_overview_coverage.py tests/test_evidence.py tests/test_web_streaming_contract.py tests/test_web_server.py`：85 passed。
- `cd web && pnpm test && pnpm typecheck && pnpm lint`：12 passed，Vue typecheck 与 ESLint 通过。
- `uv run pytest -q`：498 passed。
- `uv run ruff check src tests`、`uv run mypy src`、`uv run python -m compileall -q src`、
  `git diff --check`：全部通过。

### 设计取舍与边界

- Scope 由发送入口比较 selector 与当前 conversation 的不可变快照；session IDs 按集合比较，
  当前 selector 不可编辑的时间与容量字段不参与“用户是否切换选择”的判断；同 scope follow-up
  继续发送 conversation DTO 的完整 `buffer.scope`，保留后端时间/容量快照。不同 mode/session
  复用现有 draft/create 主链路，同选择不创建新会话。
- Coverage 不再假设所有 recent records 都是一条按调用顺序排列的 continuation；在 basis、unit、
  eligible units 一致的前提下选择最大 `covered_units` 事实，唯一消息 union 仍决定
  `retrieved_count`，因此冲突 scope 和真实计数不一致仍显式失败。
- `stream.end` 只在 request owner buffer 内读取最新 assistant；普通 live event 仍只允许修改
  running assistant。评审补充修复了 failed 终态错误块重复追加，并让 aborted 终态更新同一错误块；
  没有新增跨 buffer 猜测、重试、fallback 或数据库失败 turn。
- 本次没有数据库迁移、Provider 调整或性能算法变化；没有新增性能测量，规模风险仍由既有 bounded
  scope、Tool Result 与 Trace contract 管理。
- `trellis-check` 同步了 Web ADR、temporal backend guideline 与 Failure Case record，明确 selector
  可表达字段/完整 scope snapshot 边界、独立 root 最大 coverage 规则以及 failed/aborted 终态字段更新。

### Interview Defense Notes

- Q：为什么 scope 改变时创建新 conversation？
  Evidence：`chat.ts` 的 scope 等价判断、`chatStore.test.ts` 的 mismatch/same-scope 两组回归，
  以及 Conversation scope 不可变契约。
- Q：为什么 coverage 取最大而不是最后一次调用？
  Evidence：真实 Trace 的 `2699/2699 → 60/2699` 形状、`evidence.py` 汇总逻辑和
  `test_independent_smaller_root_query_does_not_reduce_complete_coverage`。
- Q：失败 Trace 为什么没有改持久化 schema？
  Evidence：故障发生在前端 `query.failed` 先关闭 assistant 后的终态关联；`chatStore.test.ts`
  证明同一 owner buffer 的 `stream.end.trace_id` 可以直接恢复。本任务明确不改变失败 turn replay。
- Q：什么证据会触发后续演进？
  Evidence：只有跨刷新恢复失败 turn 的真实产品需求，才考虑新增失败消息持久化或 Trace 列表入口；
  当前实现只修复 live stream 已返回 Trace 的关联。
