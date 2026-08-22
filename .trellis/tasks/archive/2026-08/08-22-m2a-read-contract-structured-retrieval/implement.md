# M1 Hardening → M2 Retrieval Core → M3 Capability/Tool — Implementation Plan

## Phase 0 — Fast-track Task Activation

- [x] 读取 AGENTS、Trellis workflow、工程原则、backend/project specs 与 interview-defense evidence 规则。
- [x] 读取 Stage1.3 Retrieval、Stage1.4 Tool/Capability、Stage1.11 Application Architecture 和 architecture baseline。
- [x] 检查 M1 model、SQLite schema/index、write store、bootstrap、现有 unittest 与真实数据统计。
- [x] 用户通过 Fast-track implementation mode 授权在本 task 内连续推进已有架构支持的 milestone。
- [x] 更新任务 scope/artifacts 后运行 `task.py start`，状态切换为 `in_progress`。

## Phase 1 — M1 Hardening First

- [x] 运行现有 unittest、ruff、mypy、`python -m trivae --help`，保存 baseline。
- [x] 检查 `seq` contract、canonical conflict projection、typed error code mapping、ingestion Failure Case regression、CLI exit code、transaction rollback、rerun/provenance 幂等缺口。
- [x] 对每个真实缺口按“复现 → 定位 → 最小修复 → regression test”处理；本轮没有新 Failure Case，因此未改 M1 主链路。
- [x] 使用独立临时数据库完成 clean real-data import + rerun；比较 messages、duplicates、conflicts、errors、provenance 统计并记录原因。
- [x] M1 validation 全绿后直接进入 M2，不停下来等待下一次确认。

## Phase 2 — M2.0 Read-side Boundary + M2.1 Structured

- [x] 新增 `src/trivae/retrieval/__init__.py`，只导出已落地 Retrieval Core 类型。
- [x] 新增 `src/trivae/retrieval/structured.py`：query、projection、coverage/metadata、message/aggregate result、repository Protocol、service。
- [x] 新增 `src/trivae/data/storage/sqlite_read.py`：独立只读连接、集中参数化 SQL、projection conversion、count/group/order，禁止泄漏 sqlite row/connection/raw JSON。
- [x] 在 `bootstrap/application.py` 组装 read repository 和 Structured Retrieval，保持 M1 write lifecycle 与异常传播。
- [x] 完成 session/time/sender/type/source/reply/limit、半开时间、确定性 ordering、empty/invalid、total/returned/truncated/coverage contract tests。

## Phase 3 — M2.2 Lexical Retrieval

- [x] 实际探测当前 Python/SQLite FTS5 能力，并在 fixture/真实数据上比较 LIKE 与 FTS5；记录 measured fact。
- [x] FTS5 可用且校准适合当前 local-first 规模，已新增最小 FTS derived index/read adapter；Canonical Store 仍是 source of truth。
- [x] 实现 rebuild，验证删除/rebuild derived index 不损失 canonical facts；保留显式 rebuild path。
- [x] 实现 lexical query 的 keyword、中文、多关键词、scope、ordering、limit、empty/invalid/no-hit contract；未引入 semantic/vector/hybrid。
- [x] 增加 lexical unit/integration tests，并在 validation.md 记录 LIKE/FTS5 选择与未采用方案的状态。

## Phase 4 — M2.3 Context Expansion + M2.4 Result

- [x] 实现同 session 的前后窗口读取，不跨 session boundary。
- [x] 实现 overlapping window merge、stable identity dedup、chronological ordering。
- [x] 实现 bounded trim，并保证真实 lexical hit 不被 context 挤掉；hits 超过 bound 时显式 partial/truncated。
- [x] 实现 Retrieval Core Result，分开 hits 与 expanded messages，不混入 Tool/Citation/Trace/Evaluation schema。
- [x] 增加相邻 hits、session boundary、multiple hits、overlap、dedup、trim、hit preservation 和 empty-hit tests。

## Phase 5 — M2.5 Real-data Validation and Performance Baseline

- [x] 使用 clean imported/copy-on-read SQLite 做真实校准，不修改 `data/raw` 或 canonical facts。
- [x] 覆盖低频、高频、中文、多关键词、sender/time/session scope、无结果、大结果、邻近 hits、context merge/trim、不同 session 同关键词。
- [x] 每个 case 记录 query、expected behavior、actual result、failure signal，并可迁移为未来 regression/evaluation case。
- [x] 记录 message count、session count、FTS build/rebuild time、典型 lexical latency、高频 latency、context latency、returned row count。
- [x] 如出现明显慢查询，先记录 query plan/Failure Case；当前没有证据要求新增复杂索引。

## Phase 6 — M3 Capability / Tool Layer

- [x] 读取并对齐 Stage1.4 已确认的 capability metadata、input contract、output envelope、scope、typed error、registry 边界。
- [x] 新增最小 `src/trivae/capabilities/` contract/registry，避免复杂 Tool framework 和重复 Retrieval abstraction。
- [x] 实现 `search_messages`：Tool input → capability validation/scope → Retrieval Core lexical + automatic context → bounded normalized result → Tool envelope。
- [x] 确保 Tool handler 不直接访问 SQLite、不构造 FTS SQL、不实现 context merge/order/trim。
- [x] 增加 valid/invalid/empty keyword/bound/session/time/retrieval error/partial-truncated/wrapper-core consistency contract tests。
- [x] M3 全绿后停止，不进入 M4 Router/Planner/Agent Runtime。

## Phase 7 — Documentation and Evidence

- [x] 更新 backend directory/database/error/quality guideline，记录实际 API、schema/index、error code、rebuild 和 validation contract。
- [x] FTS5 选择形成稳定 technical decision，已增量更新 Stage1.3 decision，写清 options/trade-off/reconsideration trigger；未重建 ADR。
- [x] 完成 `validation.md`：Problem/Motivation、Design Rationale、Why not、Failure Cases、Evaluation/Evidence、Observability/Debugging、Scale/Performance、Boundary/Ownership、Evolution、Interview Defense Notes。
- [x] 每条事实标明 measured fact、engineering expectation、real failure/regression/anticipated risk 和 permanently rejected/currently unnecessary。

## Phase 8 — Quality Gate and Handoff

- [x] `.venv/bin/python -m unittest discover -s tests -v`（70 tests passed）。
- [x] `.venv/bin/ruff check src tests`（项目代码全绿）；额外尝试 `ruff check .` 时仅发现既有 `.codex/hooks` 与 `.trellis/scripts` lint debt，本 task 未改动这些文件。
- [x] `.venv/bin/mypy src`（24 source files passed）。
- [x] `.venv/bin/python -m trivae --help`。
- [x] 检查 M1 regression、derived rebuild/rerun/provenance、FTS scope isolation、context hit preservation、Tool/Core consistency。
- [x] `git diff` 核对：无 raw 数据修改、无越界 M4/M5/M6/M7 实现、无用户现有规范改动被覆盖。
- [x] 按任务要求报告 Implemented、Architecture Mapping、ChatLab inheritance/adaptation、Failure Cases、Real-data Results、Tests/Quality、Remaining Risks、Next Task(M4)。
