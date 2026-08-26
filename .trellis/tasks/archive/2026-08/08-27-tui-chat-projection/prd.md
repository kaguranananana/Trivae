# PRD：交互式 CLI 升级为可折叠、可持续交互的 Textual TUI

## 背景

当前 `trivae chat` 通过 `CliEventRenderer` 把 `QueryStreamEvent` 平铺到 stdout：
`Route:/Plan:/Action:/✓ completed/Answer:`。多步 Agent run 会产生几十行无视觉层级的流水账，
用户无法区分「模型思考 / 计划 / 工具调用 / 工具结果 / 检索 / 最终回答」，也无法回看或折叠过程信息。

已有事件与架构保持不变：

```text
Provider/OpenAI Agents SDK → RuntimeEvent → QueryStreamAdapter → QueryStreamEvent → 渲染层
```

本任务只在现有 `QueryStreamEvent` 之上新增一个真正的交互式终端 UI projection。

## 目标

1. 默认 `trivae chat` 进入 Textual TUI；`trivae chat --plain` 与非 TTY 环境继续使用现有 stdout renderer。
2. 每个 block 类型有明确视觉边界：Thinking / Plan / Tool(+合并的 Retrieval) / Answer / Error。
3. Tool 展示采用紧凑单行 Task Row（Beautiful UI 参考），不默认做成大块 Collapsible：

   ```text
   ✓ 搜索消息      128 hits   1.7s
   ⠋ 获取上下文    …
   ✓ 语义检索      40 hits    2.1s
   ```

   仅在聚焦或展开该行后才显示 args、result summary、partial/truncated 详情（progressive disclosure）。
4. 过程聚合：执行中逐块实时出现；本轮结束后全部折叠为一个「执行过程 · N 步 · 总时长」分组，
   最终回答始终保持最大视觉权重且永不折叠。
4. 实时 streaming：`thinking.delta`/`tool.started`/`answer.delta` 到达时立即更新对应 block；
   不等 run 结束再构建。
5. 交互：鼠标点击展开/收起、键盘聚焦、Enter/Space 切换、上下滚动、底部固定输入框支持多轮问答；
   运行中 Ctrl+C 仅中断当前 run；完成后 focus 回输入框。
6. Chain-of-Thought 边界：终端不渲染 provider reasoning 文本（沿用仓库现行产品决定），
   Thinking block 只展示真实事件派生的时长/状态元数据；禁止伪造思考内容。
7. Tool Result 分层展示：collapsed summary 一行；展开显示「参数 / 结果摘要」，
   并明确展示 `partial/truncated/returned/candidate_count` 等完整性字段。
8. Plain 模式与既有测试零回归：`tests/test_cli_renderer.py`、`tests/test_cli.py`、`tests/test_query_streaming.py`
   行为不变（chat parser 新增 `--plain` 为 additive）。

## 验收标准

### UX

用户在任意时刻能在 1 秒内看出：AI 在想什么（阶段行）、调了什么工具、工具是否成功、
返回了多少内容、执行到哪里、最终回答从哪里开始。

### 架构

```text
Runtime 不依赖 Textual
QueryStreamEvent 不依赖 Textual
TUI 只消费 QueryStreamEvent
Plain CLI 继续消费同一 QueryStreamEvent
Runtime 只执行一次
```

禁止：TUI 重跑 Agent、订阅 OpenAI SDK raw event、第二套事件状态机、手写 ANSI 光标控制、整屏重绘打印。

### 测试

- Projection 纯逻辑测试覆盖全部事件类型的 state 变换、tool identity 关联、streaming 累积、
  折叠策略、手动展开持久化、长内容/中文/Markdown 截断边界、failure/abort。
- 至少一组基于 Textual Pilot 的应用级测试验证点击/键盘切换与输入回路。
- `pytest` 全量、`ruff check`、`mypy` 通过。
- 真实 DeepSeek smoke：简单问题（thinking→answer）、单工具问题、多工具问题各一轮，
  记录 TTFT、首个 process/tool block 时间、answer 开始时间、总耗时。

## 约束

- 不修改 Runtime/Orchestrator/Router/Planner/Retrieval/Evidence/Citation/Conversation Store/Trace schema/
  Tool surface/Tool Result Budget/Provider prompt/AnswerArtifact schema。
- 允许的最小跨界修改仅限：`cli.py` 增加 `--plain` 参数与 TUI 分支入口；依赖声明新增 `textual`。
