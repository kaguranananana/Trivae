# 产品预览的运行条件

README 截图于 2026-10-19 从实际构建的 Vue Web UI 拍摄，使用正常 FastAPI 服务、Application、Router、Runtime、工具、Finalizer 与会话持久化。没有伪造界面或替换模型 API 返回。

## 数据与环境

- 独立临时数据库，未连接本机日常群聊数据库；5 条手工合成消息，群名和“演示用户甲 / 乙 / 丙”均为虚构。
- 消息描述 FTS5 精确检索、语义检索、Canonical 原始消息回读及来源核验的取舍，不包含账号、真实群号、Token 或个人聊天。
- 前端经 `pnpm -C web build` 构建；通过实际 `trivae import` 导入，并经 Application 重建 FTS5。
- 使用已有配置的 `deepseek / deepseek-flash` 主模型；未修改生产业务代码或模拟 Provider。Jev 配置未因演示另作调整，本次可见路由来源为主模型 LLM。
- 服务仅绑定回环地址；截图来自窄屏布局。回答与过程截图是在同一个已完成会话中切换折叠状态取得。

## 实际观察

问题为“合成演示群聊中，大家为什么同时保留 FTS5 和语义检索？请用关键词检索原始讨论，简要说明并引用消息来源。”Router 选择 Standard，Runtime 实际调用 `lexical_search`，关键词为 `FTS5`。工具命中 2 条消息，并以有界上下文返回全部 5 条演示消息；最终 Sources 显示 4 条绑定来源。可在界面展开路由、工具参数和检索结果。

该次演示只验证词法检索、真实模型工具调用、回答交付与来源展示；没有由此证明向量召回、Planner 效果、规模性能或泛化质量。临时数据库与原始 Trace 未纳入仓库。

## 图片

- [自然语言问题与回答](assets/product-answer.png)
- [执行过程](assets/product-process.png)
- [来源列表](assets/product-sources.png)
