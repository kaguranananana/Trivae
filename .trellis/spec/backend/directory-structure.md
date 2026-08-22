# Directory Structure

> 目录与文件组织约定。M1 ingestion vertical slice 已落地；Retrieval、Query Plane、Evaluation 和 HTTP Product Interaction 仍待后续任务。

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
├── query/           # Context / Router / Planner / Runtime / Evidence
├── conversation/    # Conversation / Assistant Message boundary
├── observability/   # Normalized Event / Trace / Projections
├── evaluation/      # Case / Variant / Runner / Review
└── interfaces/      # CLI / HTTP API adapters
```

上图只表达 architecture ownership，不表示目录已经存在，也不冻结具体文件、class、Schema 或依赖版本。正式依据为 [Stage 1.11 Application Architecture ADR](../project/technical-decisions/stage-1-11-application-architecture.md)。

package layout 与 Trivae Home 都是逻辑 ownership 语义，不要求一一映射为物理目录、文件或数据库表。bootstrap 负责 Trivae Application Factory 与 core resource lifecycle；interfaces/api 负责 HTTP ASGI / Server App Factory 与 server lifecycle；接口层通过 Application facade 进入，不直接读取 Store、Index 或 provider。

## 约定（当前架构阶段生效）

- **只按已确认边界创建业务结构**：Stage 1.11 已确认单 Python distribution、`src/trivae` 概念布局和 ownership；实际目录必须在对应 Implementation task 中按 ADR 落地。
- **不提前创建实现细节**：具体文件、class、Schema、依赖、框架版本、DI 方式和测试工具链仍须等待实现任务确定。
- 当前 M1 只创建 `bootstrap`、`data`、`interfaces` 与必要的 package 初始化文件；未实现的 Query Plane package 不提前创建。

## 后续阶段（实现任务启动后补充）

- Python package / module boundary → 已由 Stage 1.11 定义概念 ownership；实际文件与 import direction 随 Implementation task 落地。
- 测试目录布局 → 随首份业务代码的确定落地（预计 pytest 结构，具体工具链在业务实现任务启动前确定）。
