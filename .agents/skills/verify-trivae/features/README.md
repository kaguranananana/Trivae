# Trivae 验证地图

先按 [日常开发验证](../SKILL.md#日常开发验证) 验收本次改动，再用本地图定位固定回归。出现值得反复验证的新功能领域或用户入口时，按需新增或更新对应旅程。

需要数据库的旅程各用独立 SQLite，需要群聊内容时由 fixture 生成合成 QQ 导出。功能页中的 pytest 路径与节点以仓库根目录为基准，默认回归的证据和清理由 `verify.sh` 管理。

定位单条回归时，把功能页列出的路径或节点作为 `uv run --offline --no-sync --no-env-file pytest -v` 的参数。

| 功能 | 驱动入口 | 核验结果 |
| --- | --- | --- |
| [群聊检索](retrieval.md) | pytest、生产检索与索引 | 字面命中、范围及截断、向量命中回查原文 |
| [上下文补读](context.md) | pytest、SDK 工具 | 长消息正文、原消息和远距离回复、范围约束 |
| [引用校验](citations.md) | pytest、查询与 Finalizer | 来源身份、范围、绑定、无效引用诊断 |
| [Evaluation 合同](evaluation.md) | trivae CLI、pytest | Case 校验、查询 Trace、失败运行持久化 |
| [Web 查询 API](web-query.md) | pytest、进程内 ASGI | readiness、流终态、会话持久化与范围约束 |
| [浏览器真实交互](browser-e2e.md) | Playwright + Chrome + 正式 FastAPI | 选择群聊、发送查询、渲染来源、点击原文、Trace 回读 |
| [真实 Agent 决策 Smoke](agent-smoke.md) | 显式许可、真实 Provider、合成数据 | 模型自行选择工具并引用原消息；不代表 Benchmark |

优先保留操作和结果的证据，例如工具输入、可观察的输出断言和 Trace 回读。遇到缺失的 fixture 前提时记录失败与复现路径。产品 Web 与 TUI 共用查询链路，但两者的界面交互要单独驱动和取证。
