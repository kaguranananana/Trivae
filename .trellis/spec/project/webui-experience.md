# WebUI 聊天体验契约

适用于 `web/src/` 的 Vue UI；验证命令在 `web/` 执行：`pnpm test`、`pnpm lint`、`pnpm typecheck`、`pnpm build`。

## 导航与范围
- 未选范围不加载全局对话列表、不自动打开最近历史。欢迎页的“从全部群聊开始”是用户显式选择 all。
- 范围选择由 SourceScopeSidebar 发出，App 调用 scope store，随后获取该范围的历史列表。
- 范围与历史合在一个可折叠侧栏，但两个组件与 store 的职责保持独立。
- 对话搜索只过滤当前范围内已加载的列表，不跨范围请求。
- 历史 conversation scope 仍不可修改；未标记范围的历史只读；URL detail-first 恢复契约保持。
- 手机抽屉打开时主区 inert，焦点进入关闭按钮；手动关闭恢复开关焦点，选择范围或对话完成后聚焦输入框。

## 输入
- ChatComposer 的 `contextKey?: string | object | null` 使用稳定 buffer 对象作输入上下文，App 传 `currentBuffer`。
- buffer 从草稿转正式 conversation 仅改变 key，不能清空等待期间输入的下一条问题。
- 切换 buffer 保存/恢复各自草稿；草稿只在页面内存，刷新不恢复。
- submit 先判断 disabled / running / busy / composing，再 trim、清空并 emit send。生成中按 Enter 不能丢草稿。
- Enter 发送，Shift+Enter 换行，composition 事件或 event.isComposing 阻止中文确认键发送。
- 快捷问题通过 `setDraft(query)` 填入并聚焦，不自动调用查询。
- 高度按 scrollHeight 自适应，上限 200px；先重设 auto，以支持删除后收缩。

## 阅读与错误
- 最终回答独立于过程分组。过程与来源的展开策略沿用既有事实，错误始终可见。
- 回答复制使用原始 Markdown；浏览器拒绝时显示错误，不能显示成功或吞错。
- Trace 仍可复制 ID、读取路径、调用 reveal API；默认收进原生 details 的“运行详情”。
- App 观察正文实际高度，而非仅观察消息数/answer.length；思考、工具结果或来源展开也可触发跟随。
- follow-tail 等 DOM 更新后读 scrollHeight；用户向上滚动暂停跟随，点击“回到最新”恢复，切换 buffer 回到底部。
- Vue 独立入口显式定义 `--ui-border`、`--ui-bg`、`--ui-text` 等语义变量，避免主题变量未注入造成黑色边框。

## 回归点
`App.test.ts` 验证 scope/URL/只读、快捷填入与聚焦；`ChatComposer.test.ts` 验证发送门禁、中文组字、草稿隔离与 buffer 转正；`ConversationSidebar.test.ts` 验证日期分组、范围内搜索、重命名和删除；`AssistantTurn.test.ts` 验证 trusted URL 与复制；`TraceFooter.test.ts` 验证路径 API 与剪贴板错误。布局需在浏览器验证桌面与手机，不能用 happy-dom 的尺寸代替真实渲染。
