# 修订 Stage 1.11 应用边界契约

## Goal

根据 Stage 1.11 复审意见，补齐应用边界契约，使文档能够直接指导后续实现，同时保持 Stage 1.11 已确认的单 distribution、共享 execution core、CLI/API surface separation 与 SSE-first 等总体决策不变。

## Background

当前 ADR 已确定包布局和应用入口，但仍有几处容易被实现误读的表述：

- 将运行时调用流和 Python 源码依赖方向写成同一条箭头。
- Application facade 未明确包含 conversations 与 traces。
- Trivae Application Factory、HTTP ASGI/Server App Factory 与两类 lifecycle 的 owner 未分开。
- QueryRequest 中的 scope、override、trace profile 容易被误解为客户端可自由声明的字段。
- Evaluation 被概括为薄入口，未说明它本身是独立评测子系统。
- Trivae Home 的概念命名空间容易被误读为强制物理目录映射。

## Requirements

- R1：在权威 ADR 中分别定义 Runtime Call Flow 与 Source Dependency Rule；业务契约不得依赖具体基础设施，bootstrap 可以同时依赖契约和具体实现，但不新增 ports、adapters、domain、usecases 等层级。
- R2：将 TrivaeApplication facade 明确为 query、ingestion、conversations、evaluation、traces、lifecycle；所有产品路由通过 Application service 进入，不直接读取 Store。
- R3：明确 bootstrap 持有 Trivae Application Factory，interfaces/api 持有 HTTP ASGI/Server App Factory；CLI serve 只负责启动 HTTP interface。
- R4：分离 core application lifecycle 与 HTTP server lifecycle，并说明关闭顺序和各自资源边界。
- R5：明确协议输入不等于 trusted Application context；data_access_scope、特权 execution_overrides、trace_profile 必须由认证、本地授权策略或 Evaluation harness 派生，普通客户端不能自行扩权或启用特权模式。
- R6：明确 Evaluation 是独立评测子系统，但其接入生产 Query execution core 的 adapter 保持薄，不能复制第二套业务执行链。
- R7：将 Trivae Home 定义为逻辑命名空间与存储 ownership 语义，不把它固化为物理目录结构。
- R8：同步更新 architecture、overview、workflow 与 backend 相关索引/指南，清理会传播旧语义的汇总表述；不修改此前 Stage 的架构结论。

## Acceptance Criteria

- [x] 权威 Stage 1.11 ADR 同时包含两种依赖规则，并明确其适用对象。
- [x] ADR 明确 Application facade、两类 factory、core/server lifecycle 与 trusted context 的 ownership。
- [x] ADR 对 Evaluation 和 Trivae Home 的边界表述与上述契约一致。
- [x] architecture、overview、workflow、backend 文档没有残留“Evaluation 只是薄入口”或混合依赖方向的旧表述。
- [x] 文档中没有引入新的 Clean Architecture 层级、第二套 execution core 或客户端自授权路径。
- [x] 通过 Trellis task 校验、Markdown 链接/内容一致性检查与 git diff --check。

## Notes

- 本 task 只修改架构文档与 Trellis task 记录，不实现 Python、CLI 或 API 代码。
- 具体认证、授权策略、wire schema 和 Evaluation runner 的实现仍属于后续阶段。
- 变更范围以 Stage 1.11 文档及其同步索引为限。
