# M7 Evaluation / Regression 执行计划

## Phase 1 — Task activation and contract groundwork

- [x] 将 Trellis task branch/base/scope 写入 metadata；完成 planning gate 后执行 `task.py start`。
- [x] 增加 `ExecutionOverride` 和 QueryRequest/RouteDecision 校验；为 normal、forced standard、forced planned 加 Trace contract tests。
- [x] 建立 `src/trivae/evaluation/` package 与中文关键注释，先完成 contracts/JSON round-trip，再接执行。

## Phase 2 — Snapshot, Variant, Suite, Case data

- [x] 实现 Case Bundle、Reference Finding/Evidence、三态 completeness、Scope identity、ReviewPolicy、Snapshot manifest/状态和 Suite references。
- [x] 实现 ControlledVariant normalized identity、secret rejection、stable fingerprint、baseline/candidate diff。
- [x] 增加 version-controlled seed/regression JSON 与 schema validation；不写完整聊天正文。

## Phase 3 — Checks, Store, Runner

- [x] 实现独立 SQLite Evaluation Store 和 close/reopen persistence。
- [x] 实现 Deterministic Checks/operational projection，保留 Trace reference，不复制 Trace。
- [x] 实现 EvaluationRunner 单 Case/Suite/repetitions，调用 `TrivaeApplication.query()`，错误显式、结果单次保存。
- [x] 在 Composition Root 装配 Evaluation Store/Runner，并保证所有资源 close；CLI 不直接创建 Runtime。

## Phase 4 — Review, comparison, diagnosis, CLI

- [x] 实现 Human review packet export/import、fake/model-assisted JudgeAdapter、质量轴和 diagnosability 分离。
- [x] 实现 blind paired comparison、条件一致性、显式 Variant diff、randomization identity 和单次 Run 回溯。
- [x] 实现 FailureDiagnosis 与 M6 Failure A/B/C regression mapping/report。
- [x] 增加 `trivae eval cases validate/run/show/compare/regression` 最小命令。

## Phase 5 — Tests and real runs

- [x] 新增 contracts/snapshot/variant/runner/override/check/store/comparison/privacy/regression tests。
- [x] 运行全量 `PYTHONPATH=src ./.venv/bin/pytest -q`；失败优先复现并修主链，不修改测试掩盖错误。
- [x] 运行 `ruff`、`mypy`、`git diff --check` 和 `task.py validate m7-evaluation-regression`。
- [x] 复制当前真实 Canonical DB 到临时目录，解析 snapshot，建立小型 Calibration/Core candidates；不修改 canonical raw data。
- [x] 建立 pinned M6 `last_stable` Variant 定义；Provider 不可用，使用 scripted/fake 完成 real-data integration，明确 real-provider blocked。
- [x] 对真实失败按 Trace 定位；记录 limitation mapping Failure Case、最小修复、regression 和 post-fix real validation。

## Phase 6 — Documentation and delivery

- [x] 更新本 task 的 `prd.md`、`design.md`、`implement.md`、`validation.md`，明确 Measured Facts / Deterministic Validation / Calibration / Baseline / Paired / Regression / Limitations / Deferred。
- [x] 只有有真实 implementation fact 时更新对应 spec；本次没有重开 Confirmed ADR。
- [x] 检查 secret/private data 未进入 Variant、Store、Report、Git diff。
- [ ] 检查 branch、base SHA、commit、push、clean worktree；不自动 merge main。

## Validation commands

```bash
PYTHONPATH=src ./.venv/bin/pytest -q
./.venv/bin/ruff check src tests
./.venv/bin/mypy
git diff --check
python3 ./.trellis/scripts/task.py validate m7-evaluation-regression
```

## Risky files / rollback points

- `src/trivae/query/contracts.py`、`src/trivae/query/router.py`、`src/trivae/query/orchestrator.py`：只增 override contract；若 normal route tests 改变，先回滚 override 逻辑，不修改 Router 规则。
- `src/trivae/bootstrap/application.py`：只做 Evaluation Store/Runner 装配和 query trace metadata；不把业务执行移入 Evaluation。
- `src/trivae/evaluation/store.py`：独立 DB；schema 变更只影响 Evaluation 文件，不触碰 Canonical tables。
- `evaluation/` case metadata：只允许 stable identity 和必要 bounded reference；若误含 private data，立即移除并检查 `git diff`。

## Required final evidence

最终 validation 必须能从仓库或命令输出回答：Evaluation 是否走生产 QueryOrchestrator、forced path 是否真实改变唯一实验变量、相同 Case/Snapshot/Scope 是否可配对、每次 Run 是否能回到 Trace/Review、M6 critical Failure 是否不复发，以及哪些结论仍因真实 Provider/Reference 不完整而未知。
