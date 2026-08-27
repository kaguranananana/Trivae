# Trivae TUI 交互体验修复与 ChatLab 风格优化

## Goal

修复真实使用中已确认的 TUI 时间线、历史滚动、文本选择/复制和 Tool Result 详情问题，使运行过程按真实事件顺序可读、长输出可回看、正文可选择复制、Tool 展开后可检查有界真实结果，同时继承 ChatLab 已验证的过程折叠语义。

## Background and confirmed facts

- 现有主链路已经具备 `RuntimeEvent → QueryStreamEvent → TuiProjectionEngine → Textual Widget`，本任务只扩展既有投影，不创建第二套 Runtime、事件总线或业务状态机。
- 真实 DeepSeek smoke 已证明 provider 会产生 public reasoning，并且 live 顺序包含 `thinking → tool/retrieval → thinking → answer`；ephemeral reasoning/token delta 按既有隐私决策不写入持久化 Trace。
- 当前多段 reasoning 可确定性复现为单个 `thinking` block：`models.py:405-423` 总是查找固定 ID `thinking`，第二、第三段会追加到第一段，最终得到 `streaming_text='ABC'`，Tool 前后的时间边界丢失。
- 当前 `app.py:200,226,239,256,274` 在 round、note 和每批 stream change 后无条件调用 `scroll_end(animate=False, force=True)`，没有 follow-tail 状态，也没有 wheel/PageUp/PageDown/Home/End 的状态转换。
- 当前 `app.py:350-352,797-803` 用 priority Ctrl+C 全局抢占：运行时中断、空闲时直接退出；没有先检查 selection。`widgets.py:270-276` 又让 `ProcessRow` 任意位置点击都 stop event 并 toggle，正文拖选会触发折叠。
- 当前环境由 `pyproject.toml` 的 `textual>=1,<2` 解析到 Textual 1.0.0。该版本仅支持 Input/TextArea selection，没有 `Screen.get_selected_text()`、`Screen.action_copy_text()` 或任意 Widget text selection。Textual 2.0.0 首次提供 arbitrary text selection；8.2.8 是当前最新稳定版，并保留这些公开 API。
- 当前 `QueryStreamEvent` 与 `TuiBlock` 只有 `result_summary`。`openai_adapter.py:on_tool_end()` 已收到 provider-neutral、发送给模型的普通 Tool Result，RuntimeContext 也已保存 bounded `ToolResultRecord`，但 `RuntimeEvent(tool_completed)` 没有携带 record/detail；`streaming.py:534-550` 因此只能投影 status/error，`widgets.py:99-124` 展开后只能显示“结果摘要”。
- 当前 retrieval 聚合由 `models.py:595-600` 选择“最后一个 running tool”，属于顺序猜测；normalized retrieval event 已有 `parent_operation_id` 可用于显式 correlation。
- ChatLab 当前实现把运行中的 process blocks 保持为 timeline，完成后聚合为 process segment；用户显式开合覆盖自动默认，失败 segment 默认展开；Tool 详情展示发送给 AI 的安全结果文本，而不是 raw SDK object。

## Requirements

### R1. 多段 Thinking 时间线与隐私边界

- 每个真实 model turn/reasoning 生命周期创建独立、稳定的 `thinking:<ordinal>` block；同一段的 delta 只追加到当前 block。
- Tool 前后的 reasoning 不得合并，展示顺序必须与 `QueryStreamEvent.sequence` 一致。
- 运行中默认展开；完成后显示 `已思考 · duration` 并默认折叠。用户手动展开或收起后，自动策略不得覆盖。
- 只有 `thinking_visibility="public_summary"` 的正文可以进入 TUI state。hidden reasoning、SDK reasoning item、scratchpad 和 provider raw 字段不得进入 Query/TUI。
- provider 没有 public summary 时只允许显示由真实 model-turn lifecycle 驱动的无正文 activity row，不得制造 reasoning 文本。
- query failed/aborted 时不得留下 running thinking/tool spinner。

### R2. Follow Tail 与历史导航

- 初始和新 round 提交后 `follow_tail=True`；仅在该状态下，新增 stream 内容才自动滚到底部。
- wheel up、PageUp、Home 或任何使 viewport 离开底部的用户滚动将 `follow_tail=False`；后续 delta 保持 viewport。
- 用户滚回真实底部时恢复 `follow_tail=True`；End 明确恢复并滚到底部。
- 至少支持 mouse wheel、PageUp、PageDown、Home、End；不为快捷键数量增加额外复杂度。
- Pilot 必须断言真实 `scroll_y/max_scroll_y`，不能只断言布尔状态。

### R3. 文本选择、复制和折叠点击区域

- 使用 Textual 官方 arbitrary selection/clipboard contract；不实现私有 selection 状态机。
- 有 selection 时 Ctrl+C 复制 selection；无 selection且 query running 时中断当前 worker；无 selection 且 idle 时不退出、不清空状态。
- `/exit`、`/quit` 保持；Ctrl+Q 作为显式退出快捷键。
- ProcessRow 只有第一行 header/toggle affordance 响应点击；Thinking、Tool Result 和 Answer 正文只参与正常选择，不触发 collapse。
- Pilot 覆盖 Answer、Tool Result、Thinking summary 拖选，selection+Ctrl+C，running/idle 无 selection Ctrl+C，以及 header/body 点击差异。

### R4. Provider-neutral bounded Tool Result Detail

- `result_summary` 继续只服务 collapsed row；新增独立 `result_detail` 服务 expanded UI，不复用字段语义。
- 详情来源为当前 Tool Call 对应的 Trivae-owned `ToolResultRecord`/model-visible safe projection；不得读取 Trace Store、数据库、Capability 或 raw SDK object，不重新执行 Tool。
- RuntimeEvent/QueryStreamEvent/TuiBlock 以 additive 字段传递 detail；Widget 只渲染已经投影好的 UI-safe detail，不解析业务对象。
- 复用现有上限：最多显示 20 个 result items、每个字段最多 800 chars；补充 16,000 chars 总预算（等于现有 20×800 理论正文上限）。超出时明确显示 `仅显示 X / Y 条` 和 `Z 条未在 TUI 展示`。
- canonical Tool Result 的 `partial/truncated/coverage/omitted_count` 与 TUI preview omission 分开表达；UI 截断不得把 retrieval 标记为 partial/truncated。
- same-name multi-call 继续用 `tool_call_id` 隔离；start/terminal/detail 乱序到达时合并同一 block。

### R5. Tool/过程折叠与视觉层级

- running Tool 默认展开显示 Input；成功后默认折叠，展开显示 Input + Result；失败后默认展开并显示稳定 error code/message。
- retrieval summary 只在 `parent_operation_id == tool_call_id` 时并入对应 Tool；不按“最后一个 running tool”猜测。
- Runtime/Trace 可保留 tool/retrieval 全部事实，TUI 同一用户操作只显示一行。
- 一轮成功后过程组默认折叠，失败/中断默认展开；重建 group 时保留 reducer 中的显式 block 开合状态。
- Answer 继续逐 delta 更新 Markdown，未经 profiling 不增加 batching/debounce。
- 只做 muted thinking、弱化 completed tool、突出 answer、缩进 Input/Result 等轻量 CSS/文本层级整理，不换主题、不增加大面积 Card/边框。

## Acceptance criteria

- [x] Projection test 覆盖 `thinking:1 → tool:A → thinking:2 → tool:B → thinking:3 → answer`，三个 thinking ID、正文和顺序均正确。
- [x] 未标记/hidden reasoning 文本不进入 TUI；无 public summary 时只有无正文 lifecycle activity。
- [x] Thinking completed/manual expanded/manual collapsed/query aborted 状态符合 R1。
- [x] Tool start/completed/failed、arguments、summary、detail、same-name multi-call、乱序 detail 均有 reducer/adapter 测试。
- [x] Tool detail 20 items、800 chars/item、16,000 total chars 的三重预算和 omission 文案有边界测试；UI omission 不改变 canonical partial/truncated。
- [x] retrieval 只按显式 parent identity 合并；并发/连续 running tools 不串行。
- [x] Pilot 产生长 history，滚到中间后追加 stream delta，viewport 不跳底；End 后下一 delta 自动 follow。
- [x] Pilot 覆盖 wheel/PageUp/PageDown/Home/End 与新 round 自动到尾。
- [x] Pilot 覆盖 Answer/Tool/Thinking 拖选和 Ctrl+C 三态；正文 drag/click 不 toggle，header click/Enter/Space 正常 toggle。
- [x] Answer delta 仍实时更新 Markdown，`answer.completed` authoritative replace 与 preview 一致；中断不留 spinner。
- [x] Textual 8.2.8 下 targeted/full tests、ruff、mypy、compileall、git diff check 通过；plain renderer 回归不变。
- [x] 使用真实 provider/数据库运行 `trivae chat`，人工核验任务说明中的 12 项 smoke 行为，并记录 provider 是否提供 public summary，不伪造缺失内容。

## Handoff addendum (2026-08-27, real-device feedback)

上一轮实现的全部 AC 已勾选并通过质量门，但用户真机（macOS 中文 IME 环境）smoke 后提出三项新问题。本节是其根因证据与增量验收要求；原 R1–R5 不变，本节优先级最高。

### A1. 中文输入修复正式落地（已完成，待提交确认）

- 真机验证：`TEXTUAL_DISABLE_KITTY_KEY=1 .venv/bin/trivae chat` 可正常输入中文。
- 实现已存在于工作区：`cli.py:_run_tui_chat` 在局部 import Textual 之前设置该环境变量，并有回归测试。无需再改代码；仅随本任务一并提交。

### A2. Tool/thinking 行"展开后无内容"的真机一致性修复

代码审阅发现的候选根因（按可能性排序）：

1. **双事实源 ID 漂移**：TUI 的 tool 行由两条流合并——RuntimeEvent 路径（`streaming.py:handle_runtime_event`，terminal 事件带 `result_detail`）与 normalized 路径（`streaming.py:handle_normalized_event` 的 `tool.call.started/completed`，提供 `operation_id` 作为 `tool_call_id`）。若两条流对同一次调用给出不同 ID 字符串，`models.py` 会创建两个独立 block：用户看到的那一行缺 arguments/detail，展开后即"没东西"；同时可能出现重复行或 `tool:None` 幽灵行。
2. **retrieval 未并入宿主**：若真机下 `parent_operation_id != tool_call_id`，`_apply_retrieval_completed` 走 fallback 创建 `kind="retrieval"` 行，而 `_block_expandable` 对该 kind 返回 False——点击永远无响应。
3. **空记录投影**：部分 tool（如聚合型 archive 查询）可能产生 message_items 与 structured_items 双空的 record，`project_tool_result_detail` 接近空文本。

增量验收：

- [ ] 增加跨源一致性回归测试：同一注入序列走 `handle_runtime_event` + `handle_normalized_event` 全量消费后，每个真实 tool call 在 projection 中恰为一个 block，且该 block 同时具备 arguments、summary、detail 三元组（provider 提供时）；断言不存在 `tool:None` 或重复 id 行。
- [ ] 断言 kind="retrieval" 孤儿行不再出现在有宿主 tool 行的场景；无法关联时必须显式报错或以可展开形式呈现，不允许不可交互的死行。
- [ ] 对 record 双空的 tool 类型，expanded 视图至少展示参数与明确的"结果无可展示正文"文案，不留空白区。
- [ ] 真机复现失败时，用既有 `trivae` trace 日志导出核对真实流的 tool_call_id/operation_id 是否一致，并在任务 notes 记录结论；不为单一样例添加特殊分支。

### A3. 鼠标滚动真机修复

Pilot 直接向 history 注入事件的测试已过，但真机不滚。增量验收：

- [ ] 新增 Pilot 测试把 `MouseScrollUp/Down` 事件投递到 history 内部子组件（AnswerBlock Markdown、ProcessRow 正文、Collapsible 标题等悬停坐标），证明冒泡到 `#history` 并移动真实 `scroll_y`；若被内层 widget 截获则修复截获者。
- [ ] 对照测试真实 ANSI SGR 鼠标序列解析：用 Textual 8.2.8 的 App driver 输入 `\x1b[<64;x;yM` 序列做一次端到端最小验证（脚本级即可，不需长期维护），排除协议层原因。
- [ ] 若确认为终端应用限制（如 Warp 的 wheel 直通问题），在 `.trellis/spec/backend/product-experience-guidelines.md` 记录终端兼容矩阵与建议终端，不引入 workaround 代码。

### A5. 用户口头反馈的具体缺陷（2026-08-27 二次反馈）

用户环境确认：iTerm2；异常行为针对"已完成工具行"。新缺陷：

- **折叠不回收高度**：thinking/tool 行展开后再手动折叠，行高没有缩回单行，历史区中间留一大块空白。这是布局失效回归，要求：
  - [ ] Pilot 测试覆盖"expanded → 手动 collapsed"的完整往返：断言行可见高度回到 summary 单行、#history 总内容高度恢复、viewport 无残留空白。
  - [ ] 根因定位到首次丢失布局信息的位置（`update_block(refresh(layout=True))` 与 mount/update 路径差异或容器缓存），最小修复；不允许删掉展开功能来绕过。
- **思考正文量与语言**：用户感到正文过少且为英文。public_summary 由 provider 原样产生，TUI 只能如实显示；本轮不改 prompt/不做翻译/不伪造中文。把该现象作为 provider 事实记录进 checklist 的待真机确认项；若后续确认 provider 输出策略可配，另开任务。

### A6. A3 收尾归档条件

用户终端已确认为 iTerm2。代码层冒泡与协议解析已被测试排除。归档条件：

- [ ] 用户在同一 iTerm2 里运行官方 `python -m textual keys` 观察滚轮是否有事件上报，结论写入 research/mouse-scroll-diagnosis.md；
- [ ] 若官方 demo 也无响应 → iTerm2 配置问题（记录指引）；若官方 demo 正常而 Trivae 异常 → 回到代码层重开排查。

### A4. 思考过程展示主观质量的核验

用户表示"思考过程……做的还是不好"，未具体到行为缺陷。按 R1 原状复核真机表现：多段是否分段、public summary 是否可见、完成态折叠与时长是否正确；把真机截图/描述落入 notes 后如仍有具体缺陷另开轮次，不在本轮猜测性改 UI。

## Out of scope

- 不改 Retrieval 算法、Evidence/Citation 语义、Conversation Store、Trace canonical schema、Agent 决策或 Provider SDK 字段解析策略。
- 不引入新 TUI framework、第二套 Runtime/事件总线、TUI 数据库读取、Trace 回填、Tool 重执行或 Multi-Agent。
- 不以 Answer batching、主题替换、新内容提示或额外快捷键作为本次阻塞项；只有 profiling/简单稳定实现证明必要时再评估。
