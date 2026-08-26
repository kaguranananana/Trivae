# Beautiful UI — AI Agent 界面信息层级参考

来源：https://www.beautifului.dev/ （2026-08-27 抓取）。只参考 UX 层级，不复刻 Web 技术栈。

## 与 Trivae TUI 相关的六个 primitive

### 1. Thinking
"Expandable traces — steps, reasoning, search, coding"。折叠态只有一行 header；
展开才看到 steps/reasoning 分类内容。启示：思考类信息的 collapsed 态是**一行**，
不占纵向空间。

### 2. Tool Chips
"Code edits and tool calls as compact chips"——样例是 `4 tool calls, 2 messages`
这类聚合 chip。启示：完成的工具调用先以**统计型紧凑单元**出现，而不是人人大卡片。

### 3. Task Rows（对 Trivae 最重要）
"Live agent task status — running, failed, completed"，行结构 =
`动词短语标题 · 数量宾语 · 状态`，例如：

```text
Verified vendor records    12 suppliers    Completed
Matched tax and contact IDs    12/12
Reading POS export    3 files        ← running，无结束状态词
Scoring stockout risk    68%
```

这正是终端等价物：

```text
✓ 搜索消息      128 hits   1.7s
⠋ 获取上下文    12 msgs    …    ← running
✓ 语义检索      40 hits    2.1s
✗ 结构化查询    SQL_READ_ONLY_VIOLATION
```

三段式：**状态符号 + display name + metric chips + duration**。失败行把 error code
作为第三段。启示：Tool 默认单行 row；详细信息（args / result summary /
partial/truncated）只在聚焦或展开后出现，即 progressive disclosure。

### 4. Streaming Text
答案流式渲染并携带来源/actions。启示：Answer 是独立的最高层级区域，
流式期间就完整可见，不被过程行打断。

### 5. Context Cards
检索内容按 chunk 卡片展示，含字符数与来源文件名。对应 Trivae：tool 详情里的
result summary（candidate_count / returned_messages / partial 等）分层展示，
正文永远不在顶层铺开。

### 6. Prompt Bar
底部固定 composer（`You >`），独立于上方滚动历史。启示：输入区是常驻 anchor，
对话历史在其上无限增长、可滚动回看。

## 终端约束下的落地原则

1. 纵向空间稀缺：过程信息 collapsed 高度 = 行数最少化（每 tool 严格 1 行，
   thinking 1 行，plan 1 行；本轮结束后整体再折成 1 个组行）。
2. Progressive disclosure 两级：L0 单行 summary → L1 聚焦高亮 → L2 展开
   （args / result summary / integrity 警告）。键盘 Enter/Space 与鼠标点击等效。
3. 状态语义用符号+色彩双编码（✓ ✗ ⠋ ▼ ▶），不依赖纯色弱可辨的差异。
4. Answer 永远全宽、优先、不可折叠；过程组折叠后 Answer 上方只留一行摘要。
