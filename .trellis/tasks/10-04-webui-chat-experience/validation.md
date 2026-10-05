# 验证记录（2026-10-04）

## 实测
- Baseline：10 个测试文件、55 项测试全部通过。
- 最终：12 个测试文件、67 项测试全部通过；`pnpm lint`、`pnpm typecheck`、`pnpm build` 通过。
- `git diff --check` 通过。Node 测试环境既有 localStorage ExperimentalWarning 不影响退出码。
- 使用现有 `127.0.0.1:8710` 后端托管生产构建，在真实浏览器测试 1280×800 桌面与 390×844 手机。
- 欢迎页显式选择全部群聊、范围搜索、历史搜索、历史回答、原始回答复制反馈、手机抽屉与选择后关闭可见。
- 手机 16 行问题输入框为 200px、scrollHeight 435px，页面无横向溢出。
- 手机选择范围后抽屉关闭，真实 document.activeElement 为“输入问题”；welcome 显式 all 操作也聚焦输入框。
- 原有主题变量缺失：浏览器 computed `--ui-border` 为空、实际 border 为 rgb(32,37,43)；补齐语义变量后实际为 rgb(230,233,237)。
- 截图：`screenshots/desktop.jpg`、`answer.jpg`、`mobile.jpg`、`mobile-welcome.jpg`。

## 设计与事实索引
- 问题：双固定侧栏占用空间、输入不自适应、生成中 Enter 清空草稿、调试操作挤占正文。
- 选择：保留 source/history 两个组件职责，组合成单侧栏；用稳定 buffer 对象保存草稿，用真实正文尺寸触发跟随。避免重新设计 store、scope、API 或 Runtime。
- 替代方案：仅调整配色不能解决空间/输入问题；新增模型选择器和附件缺少后端契约，本任务不实施。未来对应能力有接口时再考虑。
- 失败案例：新 ChatComposer 回归验证生成/提交期间 Enter 保留文本、中文组字不发请求；稳定 buffer 转正时保留预输入。原有 scope/URL/background-owner 回归全部保留。
- 验证：67 项前端测试与浏览器尺寸/交互检查证明展示与局部交互；没有在本任务重新评估模型回答质量或真实 provider stream 性能。
- 定位：导航、发送、重命名、删除、剪贴板失败显式呈现；运行详情仍能取得 Trace ID/path。
- 规模：当前搜索在现有最多 100 条 scope 列表内完成；未增加全库请求、依赖或新的持久化。
- ownership：UI 管草稿、布局与阅读；scope、stream ownership、检索、引用和持久化保持已有 store/Application 契约。
- 演进：刷新恢复草稿、全历史搜索和模型切换需另外确认产品行为与接口，不写成已交付功能。

## 测试调整说明
旧 App 测试用真实 ChatComposer 替换无 focus 方法的 shallow stub，以验证新的聚焦交互；重命名测试改用 aria-label 定位，避免把新增搜索框误当编辑框。新 Trace 测试按照现有 API client 自动附加 JSON header 的事实修正请求断言。没有删除已有断言或为通过测试添加产品特殊分支。
