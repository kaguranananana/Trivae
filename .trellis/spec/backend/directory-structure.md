# Directory Structure

> 目录与文件组织约定。**当前阶段（Stage 1.1–1.11 架构契约已完成，Evaluation Implementation / Calibration 与 Stage 1.11 Implementation / Product Interaction 待推进）：仍无业务代码。**

---

## 当前结构

```
.
├── .trellis/          # Trellis 工作流（spec / tasks / workspace / scripts）
├── .opencode/         # OpenCode Trellis 集成（plugins / agents / commands / skills）
├── AGENTS.md          # AI 会话项目指令（Trellis 管理块 + 项目内容）
└── .gitattributes
```

Stage 1.11 已确认未来业务代码的概念 package ownership，但尚未创建 `src/` 或业务文件：

```text
src/trivae/
├── config/          # Settings / PathProvider
├── bootstrap/       # Composition Root / Application lifecycle
├── data/            # Canonical Model / Ingestion / Store / Indexing
├── retrieval/       # Structured / Lexical / Semantic / Context Expansion
├── capabilities/    # Capability Contract / Tool Registry
├── query/           # Context / Router / Planner / Runtime / Evidence
├── conversation/    # Conversation / Assistant Message boundary
├── observability/   # Normalized Event / Trace / Projections
├── evaluation/      # Case / Variant / Runner / Review
└── interfaces/      # CLI / HTTP API adapters
```

上图只表达 architecture ownership，不表示目录已经存在，也不冻结具体文件、class、Schema 或依赖版本。正式依据为 [Stage 1.11 Application Architecture ADR](../project/technical-decisions/stage-1-11-application-architecture.md)。

## 约定（当前架构阶段生效）

- **只按已确认边界创建业务结构**：Stage 1.11 已确认单 Python distribution、`src/trivae` 概念布局和 ownership；实际目录必须在对应 Implementation task 中按 ADR 落地。
- **不提前创建实现细节**：具体文件、class、Schema、依赖、框架版本、DI 方式和测试工具链仍须等待实现任务确定。
- 业务代码尚未出现（验收标准之一）。

## 后续阶段（实现任务启动后补充）

- Python package / module boundary → 已由 Stage 1.11 定义概念 ownership；实际文件与 import direction 随 Implementation task 落地。
- 测试目录布局 → 随首份业务代码的确定落地（预计 pytest 结构，具体工具链在业务实现任务启动前确定）。
