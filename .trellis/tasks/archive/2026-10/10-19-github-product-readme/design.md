# 设计
README 是外部读者入口；配置、架构、评测拆至 docs。已有 qce-auto-import 与 semantic-incremental-index 复用。源码和测试优先于阶段规范。许可审查区分架构参考、实际代码/资源复用与依赖，不自行选择项目许可证。公开风险保留本地审查报告，避免新增私人信息。

截图在独立临时目录与合成 Canonical 数据库启动真实服务器；任何 mock 必须显式标明，优先真实生产 Query。外部模型调用只用合成群聊。架构图表达 Application/QueryOrchestrator、可选 Planner、同 Runtime、Evidence 原子提交、Trace 和 Evaluation 的依赖。
