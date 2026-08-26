# ChatLab 执行过程分块/折叠设计调研

来源：`ChatLab/ChatLab@main`（clone 于 2026-08-27，浅克隆）。

## 1. ContentBlock 类型（`src/services/ai/types.ts`）

```ts
type ContentBlock =
  | { type: 'text'; text; processDurationMs? }
  | { type: 'think'; tag; text; durationMs? }
  | { type: 'chart'; ... } | { type: 'evidence'; ... } | { type: 'cross_chat_evidence'; ... }
  | PlanContentBlock
  | { type: 'tool'; tool: { name; displayName; status: 'running'|'done'|'error'; params? } }
  | { type: 'skill'; skillId; skillName }
  | { type: 'error'; error: { name; message; stack } }
  | { type: 'summary_meta'; ... }
```

要点：think/tool/error 都是**同级 block**；tool block 有 running/done/error 状态与 displayName。

## 2. `chatMessageProcessSegments.ts` — segment 聚合

```ts
type ProcessSegment<T> = { type: 'process'; blocks: T[] } | { type: 'visible'; block: T }
```

两种 mode：

- **timeline**（streaming 中）：连续的 foldable process block 归入一个 `process` segment，
  遇到 visible block（正文/evidence/chart）就 flush 并独立成段 → 当前步骤总是容易看到。
- **completed**（结束后）：所有 foldable block + 「后面还有 foldable 的中间 text block」合并成
  **一个** process segment，插在第一个 foldable 出现的位置；其余 visible block 保持原顺序在外部
  → 结束后过程整体收拢，最终回答独占视觉权重。

辅助函数：segment 累计时长、locale 化时长格式、当前活动 header activity（activeToolName /
lastFoldable kind）、`isActiveProcessSegment = isStreaming && 是最后一段 && 是 process 段`。

## 3. `ProcessDisclosure.vue`

极简 disclosure：header slot 提供 `{open, toggle}`，body 默认惰性渲染（首次展开才 mount）。
折叠状态是组件本地 ref —— 聚合层只决定分组，不接管单个 block 的开合。

## 4. 启示 → Trivae 终端等价物

1. **两阶段形态**照搬：执行中逐块实时出现（timeline），query terminal 后把本 run 的全部
   process blocks 冻结进单个可折叠「执行过程」组，Answer 保持外部独立可见（completed 模式）。
2. 折叠状态分两层：组级折叠由 terminal 边界一次性决定；块级展开/收起由用户交互控制，
   自动策略必须尊重用户手动操作（对应 ChatLab「聚合层不接管单块开合」的原则）。
3. tool identity、status、duration、参数/结果分区在 Trivae 里由 `tool_call_id` + normalized
   events 直接给出，比 ChatLab 的 web 流更确定。
4. Terminal 差异化：鼠标点击折叠用 Textual 原生 focusable 容器即可获得 click+Enter+Space 三种交互；
   不需要复制 web 的 CSS/动画细节。
