# Technical Design：Textual TUI projection

## 1. 当前 CLI streaming 架构（实测）

```text
OpenAI Agents SDK stream
  → OpenAIAgentsRuntimeAdapter.stream()            # runtime/openai_adapter.py
  → RuntimeEvent(thinking_delta/content_delta/tool_*/turn_*)
      ├─ TraceableAgentRuntime persistent mapper（忽略 delta）
      └─ QueryStreamAdapter.handle_runtime_event    # query/streaming.py:442
NormalizedQueryEvent（TraceCollector event_observer）
  └─ QueryStreamAdapter.handle_normalized_event     # query/streaming.py:502
→ QueryStreamEvent(sequence 单调)
→ CliEventRenderer.handle                            # interfaces/cli_renderer.py:67
→ stdout write/flush（Route:/Plan:/Action:/✓/Answer: 平铺）
```

- `application.query(request, on_event=...)`（bootstrap/application.py:589）把同一个
  adapter 同时接到 Trace normalized events 与 Runtime live events；Runtime 只执行一次。
- `cli.py:_run_interactive_chat`（1170）每轮创建一个 `CliEventRenderer`，
  `_CallbackTextStream` 把 write/flush 适配为注入测试用的逐行 output_fn。
- 现状约束（spec/backend/agent-runtime-guidelines.md:148,387）：provider reasoning 的
  字段名不能证明可见性，终端 normal/verbose **都不渲染** reasoning 文本；
  QueryStreamEvent.thinking_visibility 仅是事实标记。

## 2. ChatLab 对应实现（已沉淀 research/chatlab-process-segments.md）

- `ContentBlock`：think / tool(running|done|error) / plan / error 同级 block。
- `buildProcessSegments` 两阶段形态：timeline（streaming 中连续 foldable blocks 归组、
  visible block 打断）与 completed（结束后所有 foldable + 中间叙述合并成单个 process
  segment，Answer 类内容留在外部）。
- `ProcessDisclosure.vue`：聚合层只决定分组；单块开合由组件本地状态接管。
- 结论 → Trivae 采用同样的两阶段形态；块级开合状态放 projection 层，
  自动策略必须尊重用户手动展开。

## 3. Beautiful UI 参考（已沉淀 research/beautifului-agent-ux.md）

分工：ChatLab 负责 process segment/thinking/tool/plan 的交互架构参考；
Beautiful UI 负责视觉层级与 compact tool presentation（Task Rows 三段式 =
status glyph · display name · metric chips · duration）；Textual 负责实现。
Tool 完成后默认严格单行，详情在聚焦/展开后才出现。

## 4. 当前体验 Failure Cases

1. `Action:/✓ completed` 无法区分同工具多次调用；结果计数淹没在 verbose 里。
2. thinking 行打印后 reasoning 内容被静默丢弃，用户只看到空白段；answer 前的十几行
   过程行把「回答从哪开始」埋掉。
3. Route/Plan/Retrieval 状态行格式各异、无时长，长 run 中间完全静态（无 spinner），
   用户不知道是否卡死。
4. 失败行与成功行只有 ✓/✗ 差异；错误后终端残缺行需要 renderer.finish() 补救。

## 5. 最小改动边界

新增：

```text
src/trivae/interfaces/tui/
    __init__.py
    models.py      # TuiBlock/TuiRound 纯 state + ProjectionEngine(event → state diff)
    widgets.py     # ProcessRow/ToolRow/PlanBlock/AnswerBlock/ErrorRow/ProcessGroup
    app.py         # TrivaeTuiApp(App) + ChatInput + worker 接线
tests/test_tui_projection.py   # 纯逻辑 reducer 测试
tests/test_tui_app.py          # Textual Pilot 应用测试
```

修改（additive）：

- `interfaces/cli.py`：`chat` 子命令加 `--plain`；`_run_chat_command` 依
  `--plain or not sys.stdout.isatty()` 选择 plain/TUI；`_run_interactive_chat` 增加
  `interface="plain"|"tui"` 参数（显式注入 input_fn/output_fn 的既有测试调用不传该参数，
  默认 plain，零回归）。
- `pyproject.toml`：dependencies 增加 `textual>=1,<2`（自带 rich，不重复声明）。

明确不改：Runtime、Orchestrator、streaming.py 事件契约、CliEventRenderer、Retrieval、
Evidence、Conversation、Trace。若实现中发现必须跨界，须先在任务 notes 记录原因并汇报。

## 6. TUI event/state/data flow

```text
QueryStreamEvent（唯一事实源）
        ↓ app 内 handle_query_stream_event()
TuiProjectionEngine.apply(event) → list[BlockChange]      # 纯逻辑，可 pytest
        ↓ change callbacks
Textual reactive state / widget mutate（mutate-reduce 或直接 update()）
        ↓
widgets 渲染（Rich markup / Markdown）
```

### ProjectionEngine state model

```python
BlockKind = Literal["thinking", "plan", "tool", "retrieval", "answer", "error", "route"]
BlockStatus = Literal["running", "completed", "failed", "aborted"]

@dataclass
class TuiBlock:
    block_id: str            # engine 分配，tool 用 f"tool:{event.tool_call_id}"
    kind: BlockKind
    status: BlockStatus
    title: str               # display name（中文 label 表复用 cli_renderer 的映射）
    metrics: dict[str, object]   # collapsed 行第三段 chips（hits/messages/…）
    arguments: Mapping | None    # L2 展开区
    result_summary: Mapping | None
    error_code/error_message
    started_monotonic/duration_ms
    streaming_text: str | None   # answer 专用累积
    expanded: bool           # 用户或策略控制
    manually_expanded: bool  # 用户动作标记，自动策略不得覆盖

@dataclass
class TuiRound:
    round_id: int
    query_text: str
    blocks: list[TuiBlock]
    answer_started/answer_completed/query_terminal
```

Engine API：`begin_round(query)`、`apply(event) -> tuple[Change,...]`、
`collapse_finished_round(round_id)`。Change 是最小 diff（block_created/updated/
appended_text/collapsed_group），app 层映射到 widget 操作。engine 不 import textual。

### 关键规则

- **Tool identity**：started 时按 `tool_call_id` 建 block；completed/failed 只更新同一
  block；同一 tool name 多次调用天然隔离。无 tool_call_id 的事件按类型兜底建独立块（不发生伪造关联）。
- **Retrieval 聚合**（deterministic）：存在 running tool block 时，
  `retrieval.completed` 的 counts/partial/truncated 合并进该 tool block 的
  metrics/result_summary（UI 摘要合并，不改 Retrieval 领域语义）；无 running tool 才建独立 retrieval row。
- **Thinking**：delta/completed 只推进时长与状态（仓库约定不渲染 reasoning 文本），
  渲染为单行 `▼ 已思考 · 3.4s`，不可展开（没有内容就不做假详情）。
- **Plan**：completed 且有 steps → 一行 `▶ 分析计划 · N 步` 可折叠；展开列 steps goal
  编号列表与 success_criteria（bounded 截断）。plan.failed → error row。
- **Answer**：首个 answer.delta 创建 AnswerBlock 并开始 streaming；
  answer.completed 用 authoritative text 整体替换（防 preview/finalizer 漂移）。
  Answer 永远 expanded、置顶于过程之上？否——保持事件顺序但在样式上强分隔：
  顶部粗分割线 + `回答` 标题 + Markdown 全宽。
- **两阶段聚合**：query.completed/failed/aborted 到达时对本轮 process blocks
  （thinking/plan/tool/route/retrieval）执行 collapse：替换为单行
  `▶ 执行过程 · N 步 · 总时长` Collapsible；answer/error rows 留在外层。
  含 failed block 或本轮 terminal failure 时 group 默认展开（error 自动展开原则）。
- 手动 `manually_expanded` 的块在 collapse_finished_round 时保留用户选择。
- **usage.updated**：累计入本轮 footer 小字（tokens in/out），无 usage 不显示。

## 7. Widget 与交互设计

- 会话区：`VerticalScroll`，内含多个 `RoundContainer(Vertical)`。
  - Round header：`You > <query>`（截断一行）。
  - ToolRow(Static-based, can_focus)：collapsed 渲染单行 Rich markup
    `[green]✓[/] 搜索消息 [dim]128 hits · 1.7s[/]`；running 时 spinner glyph +
    elapsed（app-level 0.5s Timer 仅刷新 running rows）。focused 高亮背景；
    Enter/Space/click 切换 expanded → 显示「参数/结果摘要」分区与 ⚠ partial/truncated 行。
    详情文本经 bounded 格式化（单字段 ≤800 chars，items ≤20），超限追加 `… (+N more)`。
  - PlanBlock：用 Textual `Collapsible`。
  - AnswerBlock：标题 `回答` + rule + `Markdown` widget（流式 update）。
  - ErrorRow：红字自动展开显示 code+message。
  - ProcessGroup：`Collapsible`，title=`执行过程 · N 步 · X.Xs`。
- 输入区：底部固定 `Input`（placeholder=`You > …`）。run 进行中 disabled，
  placeholder 显示运行状态；Ctrl+C 绑定两层语义——run 活跃时 cancel 当前 query
  worker（worker.cancel() → application.query 抛 CancelledError → abort 路径渲染
  aborted error row），空闲时退出确认退出。query 终态后 re-enable input 并 focus。
- resize：由 Textual layout 自动处理；长行 content 均经过 width-aware 截断 helper
  （console.width 不足时优先保 glyph+name，metrics 尾部省略）。
- 中文宽字符：使用 Rich 渲染（wcwidth-aware），不自拼对齐空格。

## 8. Textual 选型理由

内置 focus 系统/鼠标事件/CSS/bindings/Collapsible/Markdown/RichLog 直接覆盖需求；
事件驱动 message model 天然匹配 event-driven projection；官方 Pilot 支持确定性 UI 测试。
手写 ANSI 违反 PRD；prompt_toolkit 需要自行发明 widget 树与输入路由；urwid 生态老化。
`rich.live` 见下节。Python 3.14 兼容（textual≥1.x 支持）。风险：Markdown 流式 update
性能 — answer delta 为 fragment 级频率，可接受；必要时降级为 Static + 手动换行。

## 9. 为什么不用 Rich Live

Rich Live 只有单一「刷新一段输出」能力：无组件树、无 focus/键鼠事件、无滚动容器、
无可测试性（Pilot）。用它做可折叠多块交互等于重新实现半个 Textual，且要手写
终端光标管理，正是 PRD 禁止的方向。Rich Live 适合单 progress 场景，不适合 chat app。

## 10. 为什么不改 Runtime

现有链路已满足 UI 所需全部事实：tool_call_id 稳定 identity、duration_ms、结构化
result_summary（含 partial/truncated/candidate_count）、thinking_visibility 边界、
单调 sequence。任何缺失（如更细粒度进度）属于 Display 需求而非执行事实，
在 projection 层用已有字段表达即可；改 Runtime 只会增加跨界成本且违反任务边界。

## 11. Plain fallback

`trivae chat --plain` 或 `not sys.stdout.isatty()` → 原 `_run_interactive_chat`
路径原样保留（renderer/测试零改动）。CI/pipe/重定向自动获得旧体验。
`--verbose` 仅作用于 plain；TUI 下忽略（help 文本注明）。

## 12. Failure/Edge 行为矩阵

| 场景 | 行为 |
| --- | --- |
| tool.failed | 该行 ✗ + error code，详情自动展开 |
| planner failed | plan 位置替换 error row（自动展开） |
| provider stream failed (query.failed) | 当前 running rows 冻结为 interrupted 状态；error row 展开；input 恢复 |
| Ctrl+C during run | cancel worker → query.aborted 路径同上；历史不被清空 |
| Ctrl+C idle | 正常退出（Bye.） |
| non-TTY | 自动 plain |
| 极端长内容 | bounded 格式化 + 展开区内 scroll（max-height CSS） |
