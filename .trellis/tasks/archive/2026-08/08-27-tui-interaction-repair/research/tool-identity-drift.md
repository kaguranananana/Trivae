# A2 根因诊断：双事实源 tool identity 漂移（2026-08-27）

## 现象

真机 smoke 后用户反馈：Tool / thinking 行"展开后无内容"，同时怀疑存在重复行或
`tool:None` 幽灵行（handoff addendum A2 候选根因 #1）。

## 根因证据链

对同一次真实 tool call，两条流给出**不同**的 `tool_call_id` 字符串：

1. Trivae-owned call id 由 `RuntimeContext.resolve_tool_call_id()` 分配，
   形如 `request-<uuid>/tool-call/1`（`contracts.py:131-147`）。
2. `openai_tools.py:_tool_runtime_context()` 在生成 trace child 时使用
   `child(f"tool:{tool_call_id}")` —— trace 树节点名带 `tool:` 前缀。
3. normalized 投影（`streaming.py:handle_normalized_event`）把
   `event.operation_id`（即 `tool:<X>`）当作 `QueryStreamEvent.tool_call_id`。
4. runtime 投影（`streaming.py:handle_runtime_event` 的 `tool_completed`）用
   RuntimeEvent 自带的 `X` 作为 `tool_call_id`。
5. reducer 以 `f"tool:{event.tool_call_id}"` 建 block：同一次调用出现
   `tool:tool:<X>` 与 `tool:<X>` 两个 block —— 一个持 arguments+summary、
   另一个只持 result_detail。

失败测试（修复前）输出直接证明两个集合不相交：

```
self.assertEqual(terminal_ids, started_ids)
E AssertionError: Items in the first set but not the second:
E 'request-026ecf5b115c4275992b2bf1d07fcbed/tool-call/2'
E 'request-026ecf5b115c4275992b2bf1d07fcbed/tool-call/1'
```

retrieval 的 parent_operation_id 也是 `tool:<X>`，因此 retrieval counts 合并到
normalized 那个 block 上；runtime terminal block 则完全脱离宿主 —— 双行、缺半事实、
展开空白全部由此而来。

## 修复（单一事实源统一 identity）

- `_tool_runtime_context()` 改为 `child(tool_call_id)`：trace 树的 Tool 节点
  直接以 Trivae-owned call id 命名。normalized facts 与 RuntimeEvent 从此携带
  同一字符串，下游无需任何跨源格式翻译。
- 各工具闭包 emit 点中复制的 `operation_id=f"tool:{tool_call_id}"` /
  `cause_operation_id=f"tool:{tool_call_id}"` 字面量改为显式引用
  `trace_context.operation_id`（消除重复的格式知识，7 个工具 × 2 处）。
- 未在 models.py 加任何猜测式兼容匹配；reducer R1–R5 语义零改动。

回归验证：`tests/test_agent_runtime.py::CrossSourceToolProjectionTests`
走真实 OpenAI adapter + registry tool + TraceCollector 双源 +
application.query(on_event=...)，断言每个真实 tool call 收敛为恰好一个 block，
且 arguments/result_summary/result_detail 三元组齐全、无 `tool:None`、无孤儿
retrieval 行。

## 关联死行与空 record

- `_block_expandable` 曾对 `kind="retrieval"` 一律返回 False —— 孤儿检索行可见但
  点击/Enter/Space 全部无响应（唯一完全不可交互的死行）。已让 retrieval 与 tool
  共用 expandable 规则与详情渲染（有内容才可展开）。
- 双空 record（message_items/structured_items 为空）的 detail 由
  `project_tool_result_detail` 输出明确的
  `状态: ok；结果无可展示正文（返回条目 0 条）`，expanded 视图不留空白。
