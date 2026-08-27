# TUI interaction repair design

## Change boundary

最小行为差距是：现有 live facts 已到达 QueryStreamEvent，但 reducer 丢失 reasoning segment identity，controller 无条件抢 scroll/Ctrl+C，Tool terminal 丢弃可展示结果正文。修复分别落在事实首次丢失的边界，不修改检索、Evidence、Conversation、Trace source of truth 或 Agent 决策。

预计修改：

- `pyproject.toml`：把 Textual 提升到提供官方 arbitrary selection 的 `>=2,<9`；验证环境使用 8.2.8。
- `query/runtime/contracts.py`：为 `RuntimeEvent(tool_completed)` additive 携带当前 Trivae-owned bounded Tool Result record/detail。
- `query/runtime/openai_adapter.py`：在现有 `on_tool_end` 通过 `tool_call_id` 取同一 RuntimeContext record；不读取 provider raw result。
- `query/streaming.py`：新增 `thinking.started`、`result_detail` 和 UI-safe bounded projector；retrieval event 显式带 parent tool identity。
- `interfaces/tui/models.py`：独立 thinking segment reducer、terminal cleanup、tool detail merge和 identity-based retrieval aggregation。
- `interfaces/tui/widgets.py`：header disclosure affordance、Input/Result 分区和仅 header 点击 toggle。
- `interfaces/tui/app.py`：FollowTailScroll、导航 binding、selection-first Ctrl+C、Ctrl+Q。
- `tests/test_query_streaming.py`、`tests/test_agent_runtime.py`、`tests/test_tui_projection.py`、`tests/test_tui_app.py`：边界与真实 Pilot 交互回归。
- `spec/backend/agent-runtime-guidelines.md`、`spec/backend/product-experience-guidelines.md`：完成后记录 additive lifecycle/detail/follow-tail contract。

明确不做：不在 Widget 解析 Capability 数据；不向持久化 Trace 写 Tool 正文或 reasoning delta；不从 QueryResult terminal 批量回填 Tool 详情；不修改 plain renderer；不通过 last-running-tool 或事件相邻性猜 correlation。

## Data flow

```text
SDK public model lifecycle ───────────────┐
SDK tool-end + RuntimeContext record ─────┤
normalized tool/retrieval facts ──────────┘
                  ↓
             RuntimeEvent
                  ↓
          QueryStreamAdapter
   ┌──────────────┼────────────────┐
thinking lifecycle│tool result detail│parent tool identity
   └──────────────┼────────────────┘
                  ↓
           QueryStreamEvent
                  ↓
        TuiProjectionEngine
                  ↓
       Textual Widget / Scroll state
```

## Contracts

### Thinking lifecycle

- `turn_started` 投影为无正文 `thinking.started`，只表达真实 model turn activity。
- 第一个 public-summary delta 更新当前 running segment 的正文；未标记 delta 只消费顺序，不写正文。
- Runtime `thinking_completed`、tool boundary、answer boundary 或 turn terminal 关闭当前 segment；关闭操作幂等，避免重复完成事件产生新行。
- reducer 用每轮单调 ordinal 生成 `thinking:1..N`，只保存当前 running thinking ID；完成后清空 active ID，下一次 start/delta 创建新 block。
- 该设计只把 lifecycle 标为“正在思考”，不把 provider hidden reasoning 转成文字；正文仍受 `public_summary` 单点 gate。

### Tool Result detail

- Runtime adapter 从 `RuntimeContext.tool_results` 按 `tool_call_id` 找到 canonical bounded `ToolResultRecord`，作为 RuntimeEvent additive fact。
- Query boundary 只投影允许展示的 message/structured item 字段；不包含 run/scope snapshots、raw SDK fields 或 secret。
- `ToolResultDetail` 是不可变 UI-safe value：预格式化 `text`、`displayed_count`、`available_count`、`omitted_count`、`preview_truncated`。Widget 不再遍历 Runtime/Capability object。
- 预算顺序：先稳定取前 20 items，再限制单字段 800 chars，最后限制详情正文 16,000 chars；每次截断都更新 UI preview metadata 和明确 footer。
- canonical `status/limitations/partial/truncated/coverage` 继续来自 normalized summary/record；preview fields 只进入 detail，不写回 block metrics。

### Correlation

- Tool block identity 为 `tool_call_id`。
- normalized `retrieval.*` 的 `parent_operation_id` 作为 QueryStreamEvent 的 `tool_call_id`；reducer 只更新同 ID tool block。
- 找不到关联 block 时 retrieval 独立显示；不选择任意 running tool。
- normalized tool terminal 和 Runtime detail 可能先后到达；两者都对同 block 做字段合并，terminal 状态更新幂等，不创建重复行。

### Follow tail

- `ChatHistory(VerticalScroll)` 持有唯一 `_follow_tail`。
- user scroll 导致 `scroll_y < max_scroll_y` 时关闭；到达底部时打开。新内容只读取更新前状态，若为 true 才在 refresh 后 `scroll_end`。
- PageUp/Home 显式关闭；End 显式打开；PageDown/wheel down 依赖真实 bottom watcher 恢复。
- `begin_round_view()` 是用户主动开始新轮，显式打开并到尾。

### Selection and Ctrl+C

- Textual 2+ Screen selection 是唯一 selection source；Ctrl+C action 顺序：selected text → `screen.action_copy_text()`；否则 active worker → cancel；否则 no-op。
- Ctrl+Q/`/exit`/`/quit` 是退出路径。
- ProcessRow 仍保留键盘 Enter/Space；鼠标只在 header line toggle，detail event 不 stop，让 Screen selection 正常处理。

## ChatLab inheritance

- 继承 timeline-active/completed-process-group 两阶段模型、显式 open override、failed default open、Tool safe result disclosure 和 Answer 最高阅读权重。
- Textual 无 Web `details`/DOM，因此以 reducer snapshot + ProcessRow header/body 复现语义，不复制 ChatLab 的 CSS/组件结构。
- ChatLab 展示发送给 AI 的安全 Tool Result；Trivae 优先使用更强的 Trivae-owned bounded record，再独立做 TUI preview，避免 raw runtime dump。

## Compatibility and rollback

- Textual 1.0 → 8.2.8 探针：26 个现有 TUI 测试中 25 个通过，唯一差异是测试读取已移除的 `Static.renderable`；改用公开 render/content 断言。升级后必须跑全套验证。
- 若 Textual 升级暴露真实应用不兼容，直接修复公开 API 使用点；不保留 1.x/8.x 双分支。
- 各 Failure Case 独立完成实现/测试闭环；任何阶段可通过对应文件 diff 回滚，不需要数据 migration。

## Risks

- selection 的坐标测试可能受双宽中文影响：Pilot 使用 Textual 官方 `mouse_down/mouse_up`，断言选中文本而非像素实现细节。
- streaming mount 后 layout 延迟更新 max_scroll：follow-tail scroll 必须用 refresh 后调用，测试同时覆盖连续 delta。
- Tool record 与 normalized terminal 到达顺序不固定：reducer 必须合并而非假定顺序。
- public reasoning 不持久化 Trace：真实 smoke 通过 live event recorder/可见 UI 取证，不把 reasoning 正文写进 Trace。

