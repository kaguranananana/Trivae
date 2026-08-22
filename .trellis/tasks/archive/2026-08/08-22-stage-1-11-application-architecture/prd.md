# 沉淀 Stage 1.11 应用边界与工程结构架构

## Goal

把 Stage 1.1–1.10 已确认的 Data Plane、Query Plane、Router、Planner、Agent Runtime、Retrieval、Evidence / Citation、Trace 与 Evaluation 边界，收束为可落地的 Python 工程边界。

文档需要明确：代码如何组织、CLI / HTTP API / Evaluation 如何进入同一套业务执行核心、公共契约由哪一层拥有，以及哪些内容仍留给 Implementation / Real-run Calibration。目标是完成架构封口，不提前实现业务代码或重新设计既有内部模块。

## Background and Confirmed Facts

- 当前仓库没有业务代码，已有内容主要是架构决策、项目规范与 Trellis 任务记录。
- ChatLab 是项目级 Reference Implementation；应继承“薄入口、集中装配、可复用核心”的组织原则，但不机械复制其多 workspace monorepo。
- Trivae v1 只有一个 Python Runtime，计划采用一个 Python distribution；具体 Python 版本、CLI / HTTP 框架版本和实现依赖仍不在本 ADR 中冻结。
- Query 主链路由 `QueryOrchestrator` 统一承接：Context → Router → 可选 Planner → Agent Runtime → Tool / Capability → Retrieval → Evidence / Citation → Finalization。
- Stage 1.9 已确认 Normalized Query Event 是入口投影与 Trace Collector 的共同事实边界；Stage 1.10 已确认 Evaluation 必须复用生产执行语义，并通过受控 Variant 做 forced-path 与 paired comparison。

## Requirements

### R1. 明确应用边界

正式架构文档必须把 CLI、HTTP API、Evaluation 定义为三个 Interface Adapter，把 Application / Query Orchestrator 定义为共享的业务入口；入口层不得各自实现 Router、Planner、Runtime、Retrieval 或 Evidence 流程。

### R2. 冻结 v1 的物理组织原则

文档必须确认单 Python distribution 与 `src/trivae` layout，并按架构 ownership 划分 `config`、`bootstrap`、`data`、`retrieval`、`capabilities`、`query`、`conversation`、`observability`、`evaluation`、`interfaces` 等概念包。

目录树只表达边界和职责，不冻结每个小文件、类数量、数据库表、JSON Schema 或具体依赖版本。

### R3. 定义 Composition Root 与生命周期

文档必须说明统一 Composition Root 如何从 Settings / Paths 装配 Store、Index、Retrieval、Capability、Tool Registry、Router、Planner、Runtime Adapter、Evidence / Citation、Trace Collector 与 Query Orchestrator，并向 CLI / API / Evaluation 暴露一个可管理生命周期的 Application 对象。

必须避免 import-time 的全局数据库连接、Runtime 初始化或其他不可控副作用。

### R4. 统一 Query Application Contract

CLI 参数、HTTP JSON、Evaluation Case 必须映射到同一个 Application-level `QueryRequest` 语义，再调用 `QueryOrchestrator.execute`。`request_id`、`conversation_id`、`chat_session_id`、query、locale、Data Access Scope、execution override、Trace profile 等字段的语义要统一；具体类型和序列化格式留给实现。

### R5. 复用同一个 Execution Core

Evaluation 只能通过受控的 `forced_route` / Variant / execution override 进入同一个 Query execution core，不得复制 `eval_router`、`eval_runtime` 或独立 Retrieval / Tool 链路。Production Query 与 Evaluation Query 的差异必须显式可见、可 Trace、可比较。

### R6. 统一事件、Streaming、Trace 与 Error 投影

SDK Event 必须先由 Runtime Adapter 转换为 Trivae-owned Runtime Event，再进入 Normalized Query Event 边界；CLI、API、未来 UI 只能消费 Stream Projection，不能直接依赖 OpenAI Agents SDK 类型。

入口从开始就保留 `request_id` / `trace_id` 关联；Domain / Application Error 保留 canonical `error_code`、origin stage、category 与 safe message，CLI / HTTP 只负责投影，不重新定义错误语义。

### R7. 集中管理 Config、Paths 与 Lifecycle

CLI、API、Evaluation 共用同一 Settings / PathProvider / Application lifecycle；不得在各入口自行拼接用户目录或重复初始化基础设施。启动、关闭、错误暴露与 Trace 关联必须是可观察的。

### R8. 冻结依赖方向与 SDK 隔离

默认依赖方向为：`interfaces / evaluation → application / query → domain modules → infrastructure implementations`。Retrieval 不得依赖 CLI，Runtime 不得依赖 FastAPI，Router 不得依赖 Typer，Capability Contract 不得向上暴露 OpenAI Agents SDK 类型，Data 不得依赖 Agent Runtime。

### R9. 区分产品入口与 Agent Capability Surface

第一版 CLI 只承载 query、import、serve、eval、trace、config 等产品入口；Agent Tool Surface、CLI Surface、HTTP API Surface 不因复用方便而合并。MCP、Daemon、Electron / Web UI、self-update 等 ChatLab 能力不进入当前 v1 架构承诺。

### R10. 明确 HTTP 与 CLI 的协议边界

HTTP API 采用版本边界（第一版为 `/api/v1` 的概念约定），Route 与 Server Lifecycle 分离。一次查询的普通响应与单向 Streaming 响应都应建立在同一个 Application Contract 与 Normalized Event Projection 上；第一版不为此引入 WebSocket 语义。

### R11. 记录 ChatLab 的继承、适配与暂不继承

Stage 1.11 ADR 必须说明继承薄入口、集中初始化、共享核心、配置路径集中管理、Streaming / Trace 边界；适配为单 distribution + 内部 package；暂不继承 Desktop / Web UI、Daemon、MCP 与 self-update，并写明 Trivae v1 的约束与 trade-off。

## Acceptance Criteria

- [x] 新增 Stage 1.11 技术决策文档，包含 Context、Boundary、Decision、Data Flow、Package Layout、Failure Cases、Trade-off、Deferred、Validation 与 Reopen Conditions。
- [x] ADR 明确 CLI、HTTP API、Evaluation 三个入口都通过同一个 Composition Root 和 QueryOrchestrator 执行；没有入口私有的 Agent / Retrieval / Evaluation 主链路。
- [x] ADR 明确单 Python distribution、`src/trivae` 概念布局、依赖方向、SDK 隔离、Config / Paths / Lifecycle ownership，以及哪些细节仍为 Implementation Pending。
- [x] ADR 明确统一 `QueryRequest`、Normalized Event Projection、`request_id` / `trace_id`、canonical Error projection 与 Evaluation controlled override 的语义。
- [x] ADR 明确 CLI / API 的第一版边界、`/api/v1`、单向 Streaming，以及 Tool Surface ≠ CLI Surface ≠ HTTP API Surface。
- [x] `technical-decisions.md` 新增 Stage 1.11 索引；`architecture.md`、`overview.md`、`project/workflow.md` 与相关 backend 指南的阶段状态和 Pending 路由一致。
- [x] `backend/directory-structure.md` 能反映已确认的概念包边界，但不伪装业务代码已经实现。
- [x] 全局一致性检查不再把 Stage 1.11 架构描述为未设计，同时仍明确 Stage 1.10 Implementation / Real-run Calibration、业务代码、Schema、框架版本与真实运行结果尚未完成。
- [x] `git diff --check` 通过；文档链接、Stage 编号和术语经过 `rg` 复核。

## Out of Scope

- 不创建 `src/` 业务代码、`pyproject.toml`、CLI / FastAPI 应用、Evaluation runner、数据库 Schema 或测试实现。
- 不选择或锁定 Typer / FastAPI / OpenAI Agents SDK 的具体版本，不冻结 DI library、ID 编码、SSE wire schema、HTTP status 全表或目录最终物理名称。
- 不重新设计 Stage 1.1–1.10 已 Confirmed 的 Router、Planner、Runtime、Retrieval、Evidence / Citation、Trace、Error Ownership 与 Evaluation contract。
- 不将 ChatLab 的参数、Case 数量、Route taxonomy、Judge heuristic 或运行结果写成 Trivae 的默认值、质量 baseline 或 numerical threshold。
- 不在本任务中实现 UI、MCP、Daemon、WebSocket、self-update、分布式部署或产品化权限工作流。

## Constraints and Risks

- 文档必须区分“架构边界已确认”和“实现细节已完成”，避免以目录树制造虚假实现进度。
- `QueryRequest`、Normalized Event、Error 与 Evaluation Variant 是跨层契约；任何重复定义都可能导致 CLI / API / Evaluation 语义漂移。
- Composition Root 如果被入口绕过，会造成配置、Trace、Runtime 和 Evaluation 行为分叉；因此应把绕过路径列为明确 Failure Case。
- ChatLab 的 monorepo 结构不能直接迁移到当前空仓库；适配必须保留 ownership，而不是引入多 distribution 的 packaging 复杂度。

## Open Questions

无阻塞性问题。具体框架、Schema、字段类型、目录物理实现和生命周期参数已明确列入 Deferred / Implementation Pending。
