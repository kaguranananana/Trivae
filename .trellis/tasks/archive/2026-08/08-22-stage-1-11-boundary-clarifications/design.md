# Stage 1.11 应用边界契约修订设计

## 1. 设计目标

本次只修正文档中的边界语义，不重做 Stage 1.11 的总体架构。修订后的文档应让实现者能够区分：

- 运行时请求经过哪些层。
- 哪些 Python 包可以互相导入。
- 哪个 factory 创建核心应用，哪个 factory 创建 HTTP server。
- 哪些资源由核心应用管理，哪些资源由 server 管理。
- 哪些 Query context 是经过授权后可信的，哪些只是外部协议输入。

## 2. 权威文档与同步范围

权威定义放在 Stage 1.11 ADR：
.trellis/spec/project/technical-decisions/stage-1-11-application-architecture.md

同步摘要放在：
.trellis/spec/project/architecture.md
.trellis/spec/project/overview.md
.trellis/spec/project/workflow.md
.trellis/spec/backend/directory-structure.md
.trellis/spec/backend/index.md
.trellis/spec/backend/quality-guidelines.md

只更新会传播 Stage 1.11 边界语义的段落；此前 Stage 1.1–1.10 的技术结论、单 distribution 方案和现有 package 数量不变。

## 3. 依赖关系的双层表达

### 3.1 Runtime Call Flow

运行时调用流表达一次请求如何进入共享 execution core：

    CLI / HTTP / Evaluation execution adapter
      -> TrivaeApplication
      -> QueryOrchestrator
      -> Context / Router / Planner / Runtime
      -> Capability / Retrieval
      -> Data

这条箭头描述调用顺序，不等价于 Python import 方向。Conversation、Import、Trace 等产品路径同样先进入 TrivaeApplication 的对应 facade，再进入其拥有的 application service。

### 3.2 Source Dependency Rule

源码依赖表达可导入关系：

    interfaces / evaluation adapters
      -> application / query contracts
      -> Trivae-owned business contracts

    concrete infrastructure adapters
      -> Trivae-owned business contracts

    bootstrap / composition root
      -> contracts + concrete implementations

约束如下：

- Trivae-owned business contracts 不导入 SQLite、FastAPI、Typer、具体 provider SDK 等基础设施细节。
- concrete infrastructure 可以实现或依赖 Trivae-owned contracts。
- interfaces 依赖 Application facade，不直接依赖 Store、Index 或 provider。
- bootstrap 是允许组装抽象契约和具体实现的 Composition Root。
- 本规则不要求新增 ports、adapters、domain、usecases 等目录，也不把当前包布局改造成多层 Clean Architecture。

## 4. Application facade 与产品路径

TrivaeApplication 的概念树修订为：

    TrivaeApplication
      - query
      - ingestion
      - conversations
      - evaluation
      - traces
      - lifecycle

所有产品路由均通过 Application service 进入：

- conversations/{id} -> application.conversations -> Conversation Store。
- imports -> application.ingestion -> ingestion pipeline。
- traces/{id} -> application.traces -> Trace Store 与 projection。
- query -> application.query -> shared Query execution core。
- evaluation -> application.evaluation -> Evaluation subsystem 与共享 Query execution core 的薄 adapter。

路由层只负责协议解析、认证上下文传递、调用 facade 和响应投影，不直接读取 Store 或编排底层 provider。

## 5. Factory ownership 与 lifecycle

### 5.1 Factory ownership

- bootstrap 持有 Trivae Application Factory，例如 create_application(settings)，负责构造依赖、Application facade 和核心资源。
- interfaces/api 持有 HTTP ASGI/Server App Factory，例如 create_http_app(application)，负责创建 ASGI app、注册 routes、协议 middleware 和 response projection。
- CLI serve 通过 bootstrap 创建 Application，再启动 HTTP interface；CLI 不复制 API 组装逻辑。

### 5.2 Lifecycle ownership

core application lifecycle 管理 Store、Index、Provider、Runtime、Trace Store、Conversation Store 等长期资源，并提供 application.close。

HTTP server lifecycle 管理 ASGI app、Uvicorn 或其他 server、listener、socket 和连接生命周期。核心 Application 不拥有 Uvicorn、listener 或 socket。

关闭顺序是 server 停止接收新请求，server 完成在途请求，再调用 application.close 释放核心资源。这个顺序是 ownership 约束，不要求当前阶段立即实现具体 server。

## 6. Trusted Query context

QueryRequest 的 wire 输入与 Application 内部可信上下文分开：

    protocol request / local authenticated caller / Evaluation harness
      -> authentication and policy derivation
      -> trusted Application context
      -> QueryRequest
      -> Query execution core

data_access_scope、特权 execution_overrides、trace_profile 等字段如果进入 QueryRequest，表示已由 Application boundary 解析并校验的上下文，不表示普通 HTTP/CLI 客户端可以自由提交这些值。

必须保持的契约：

- Protocol input != trusted Application context。
- 普通调用者不能通过 wire 字段扩大 data access scope。
- 特权 execution override 和 debug trace profile 只能由受信任的本地策略、认证上下文或 Evaluation harness 派生。
- 后续实现可以分别设计 wire schema 与内部 QueryRequest；本次不提前锁定认证框架或授权策略实现。

## 7. Evaluation 边界

Evaluation 是独立评测子系统，拥有 Case、Variant、Runner、Judge、Review、Comparison 和 Regression 等评测语义。它不是单纯的 HTTP/CLI 薄入口。

但 Evaluation 进入生产 Query execution core 的 adapter 必须保持薄，复用 TrivaeApplication.query 和同一套 execution core，不复制第二套 query planner、runtime 或 capability execution chain。

## 8. Trivae Home 命名空间

Trivae Home 表示用户数据、索引、运行产物和 trace 等内容的逻辑命名空间与 storage ownership。它用于定义谁拥有数据、谁负责生命周期和隔离，不强制一一映射为物理目录、文件或具体数据库表。

## 9. 不变项与风险控制

本次修订明确保留：

- 单一 Python distribution 与 src/trivae 包布局。
- Application 作为唯一 product boundary。
- CLI、HTTP API、Evaluation surface separation。
- HTTP v1 与 SSE-first 的既有方向。
- 共享 Query execution core。

主要风险是后续实现把概念字段直接暴露为客户端可写参数，或把 bootstrap factory 与 HTTP factory 合并。实现阶段应以本设计中的 factory、lifecycle、trusted context 和双层依赖规则作为验收依据。
