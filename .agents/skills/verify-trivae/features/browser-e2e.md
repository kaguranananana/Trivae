# 浏览器真实交互 E2E

**入口：** `.agents/skills/verify-trivae/verify-web.sh`

**覆盖：** Mac Chrome 通过正式 HTTP 服务访问打包后的 Vue；后端使用隔离的合成 QQ 消息与真实 Trivae Application/SQLite，只有模型输出是预编排的 SDK ScriptedModel（零真实调用）。

**用户旅程：** 选择「回复实验」→ 提问项目是否有人使用 → 流式回答结束后可见一条有效引用 → 打开来源面板 → 点击「查看完整原消息」 → 核对「实际用过，值得推荐」 → 关闭弹窗 → 再检查本轮 Conversation 和 Trace 已持久化。

**负例：** `verify-web.sh --negative-control` 注入模型伪造引用，期望脚本退出非 0，并保留 `browser-failure.png` 和日志。其失败是验证器能识别无来源行为的证据，不是生产 Bug。

**证据：** 每次独立生成 `data/evaluation/verify-trivae/browser.*/`。人工查看脚本退出码、Chrome 截图、HTTP/JS 错误和 Trace 回读断言。

**不覆盖：** 真 LLM 工具决策、真实向量质量、OAuth、TUI 或其他浏览器设备。更改 UI 功能时需增加该功能特有的用户断言，不能只因这条固定旅程通过就报告新增 UI 合格。
