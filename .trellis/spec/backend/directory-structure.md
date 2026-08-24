# Directory Structure

> 目录与文件组织约定。M1 ingestion、M2 Retrieval Core、M3 最小 Capability/Tool vertical slice、M4a Agent Runtime baseline、M4 Query Execution Core、M5 Evidence/Citation finalization vertical slice、M5b Conversation persistence 与 M6 Trace/Observability 已落地；Evaluation 和 HTTP Product Interaction 仍待后续任务。

---

## 当前结构

```
.
├── .trellis/          # Trellis 工作流（spec / tasks / workspace / scripts）
├── .opencode/         # OpenCode Trellis 集成（plugins / agents / commands / skills）
├── AGENTS.md          # AI 会话项目指令（Trellis 管理块 + 项目内容）
├── pyproject.toml      # Python distribution metadata 与 CLI entry point
├── src/trivae/         # 业务 package，按 ownership 分层
├── tests/              # M1 unittest contract/integration tests
├── data/raw/           # 用户提供的只读 QQ JSON 输入
└── .gitattributes
```

Stage 1.11 已确认 package ownership；M1 已创建当前实现所需的最小目录：

```text
src/trivae/
├── bootstrap/       # Composition Root / Application lifecycle
├── data/            # Canonical Model / Ingestion / Store / Indexing
│   ├── ingestion/   # QQ Adapter 与 Shared Importer
│   └── storage/     # SQLite Canonical Store
├── retrieval/       # Structured / Lexical / Semantic / Context Expansion
├── capabilities/    # Capability Contract / Tool Registry
├── query/           # Context / Router / Planner / Orchestrator / Runtime / Evidence
├── conversation/    # Conversation / Assistant Message boundary
├── observability/   # Normalized Event / SQLite Trace / Import diagnostics projections
├── evaluation/      # Case / Variant / Runner / Review
└── interfaces/      # CLI / HTTP API adapters
```

上图只表达 architecture ownership，不表示目录已经存在，也不冻结具体文件、class、Schema 或依赖版本。正式依据为 [Stage 1.11 Application Architecture ADR](../project/technical-decisions/stage-1-11-application-architecture.md)。

package layout 与 Trivae Home 都是逻辑 ownership 语义，不要求一一映射为物理目录、文件或数据库表。bootstrap 负责 Trivae Application Factory 与 core resource lifecycle；interfaces/api 负责 HTTP ASGI / Server App Factory 与 server lifecycle；接口层通过 Application facade 进入，不直接读取 Store、Index 或 provider。

## 约定（当前架构阶段生效）

- **只按已确认边界创建业务结构**：Stage 1.11 已确认单 Python distribution、`src/trivae` 概念布局和 ownership；实际目录必须在对应 Implementation task 中按 ADR 落地。
- **不提前创建实现细节**：具体文件、class、Schema、依赖、框架版本、DI 方式和测试工具链仍须等待实现任务确定。
- M1 先只创建 `bootstrap`、`data`、`interfaces`；M2/M3 implementation task 已按确认边界实际创建 `retrieval`、`capabilities` 和 data/storage read/derived adapter；M4a/M4 implementation task 已按确认边界创建 `config`、`query` contracts/router/planner/orchestrator/runtime`；M5 implementation task 已在 `query/evidence.py` 落地 Answer Artifact、provenance 与 finalization；M5b 已创建 `conversation/`，拥有 Conversation domain、Artifact codec 和 SQLite Store；M6 已创建 `observability/`，拥有 normalized event、collector、SQLite Trace Store 和 projections。Evaluation package 仍随对应任务落地。

## 当前已落地的 M2/M3 物理文件

```text
src/trivae/
├── retrieval/
│   ├── __init__.py
│   ├── structured.py       # Read Contract、Structured/Lexical result types、repository Protocol
│   ├── lexical.py          # FTS hit → Retrieval Result 编排
│   └── context.py          # bounded context merge/dedup/trim/hit preservation
├── capabilities/
│   ├── __init__.py
│   ├── contracts.py        # trusted scope、input、envelope、typed errors
│   ├── search_messages.py  # Retrieval-facing Capability
│   ├── registry.py         # explicit Tool registry
│   └── tools.py            # thin search_messages Tool wrapper
└── data/storage/
    ├── sqlite.py            # M1 canonical write store
    ├── sqlite_read.py       # M2 read-side SQL/projection/context/FTS query adapter
    └── sqlite_lexical.py    # rebuildable FTS5 derived index
```

这些文件属于前序已实现的 ownership；Semantic、Hybrid、Reranker 和 Evaluation package 仍没有物理壳文件；Evidence、Trace、Router、Planner 和 Orchestrator 已在对应实现任务落地。

## 当前已落地的 M4 Query Execution Core 物理文件

```text
src/trivae/
├── config/
│   ├── __init__.py
│   ├── dotenv.py          # CLI-only dotenv parsing/injection；不改变 settings 纯读取边界
│   └── settings.py        # DeepSeek env contract 与 secret-safe settings
└── query/
    ├── __init__.py           # Query exports
    ├── completion.py         # provider-neutral completion boundary
    ├── contracts.py          # QueryRequest/QueryResult/context/diagnostics
    ├── router.py             # two-route rule-first Router
    ├── planner.py            # bounded validated soft Planner
    ├── orchestrator.py       # shared Query application entry
    ├── evidence.py           # Answer Artifact、Evidence/Citation contract 与 trusted finalization
    └── runtime/
        ├── __init__.py
        ├── contracts.py      # SDK-independent request/context/result/event
        ├── openai_adapter.py # streamed OpenAI Agents SDK / DeepSeek adapter
        ├── openai_tools.py   # search_messages thin SDK tool adapter
        └── prompt.py         # short model-visible instructions
```

M4 的 env、Query/Runtime request/result/event 与 M5 finalization 边界见 [Agent Runtime Guidelines](./agent-runtime-guidelines.md)。Runtime adapter 是唯一允许直接依赖 OpenAI Agents SDK 的新业务模块；`query` application contracts、`query/evidence.py`、`capabilities/`、`retrieval/` 与 `data/` 不反向依赖 SDK。

## 后续阶段（实现任务启动后补充）

- Python package / module boundary → 已由 Stage 1.11 定义概念 ownership；M5 已落地 `query/evidence.py`，M5b 已落地 `conversation/` 的 Conversation / Assistant Message persistence、显式 Artifact JSON codec、stable ordinal replay 与 Application commit boundary；M6 已落地 `observability/{contracts,collector,sqlite,projection}.py`；Evaluation 仍随对应 Implementation task 落地。
- 测试目录布局 → 当前继续使用 unittest；M1/M2/M3 contract/integration tests 分文件维护，真实数据校准记录在 task validation artifact，不把 raw 数据复制到 tests。
