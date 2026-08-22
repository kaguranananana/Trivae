# Implementation plan

## Ordered checklist

1. [x] 创建 `pyproject.toml` 和 `src/trivae` 最小 distribution；`PYTHONPATH=src python3 -m trivae --help` 作为 M0 smoke check。
2. [x] 创建 Canonical dataclass/model 与 QQ export Adapter，覆盖 V5 和 0.1.0 字段差异、群号解析、时间戳、sender、reply、content/raw 保真。
3. [x] 创建 SQLite Canonical Store，初始化 M1 最小 schema、唯一约束、ImportBatch、variant/conflict 和 error 记录。
4. [x] 创建 Shared Importer 与 Application/bootstrap 入口：按文件批次导入、按稳定 session/message identity 合并、幂等重跑、显式报告 partial/error。
5. [x] 创建薄 CLI `trivae import`，支持 `--raw-dir`、`--database` 和可核对的 JSON 摘要。
6. [x] 添加 unit/contract/integration tests：文件名 identity、两种源格式、fallback identity、duplicate/conflict、跨 session 同 ID、transaction/幂等。
7. [x] 运行测试与真实数据导入，查询 SQLite 统计 14 文件、7 session、494,628 received、473,236 unique inserted，并核对重复/冲突/每批状态。
8. [x] 若真实导入暴露 schema/normalization failure，先保存复现、定位根因，再做最小主链路修复；不修改原始数据或用样例特判。

## Validation commands

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m trivae --help
PYTHONPATH=src python3 -m trivae import --raw-dir data/raw --database data/trivae.sqlite3
PYTHONPATH=src python3 -m trivae import --raw-dir data/raw --database data/trivae.sqlite3
```

第二次导入用于验证幂等性；真实数据库计数和 ImportBatch 摘要必须能解释 duplicate/variant/conflict，而不是只看命令 exit code。

## Validation results

- Unit tests：6 tests passed；`compileall` 与 CLI help passed；ruff/mypy/pyright/pytest 未安装，因此使用仓库可用的 stdlib unittest 验证。
- 首次真实导入：14 files、494,628 received、473,236 inserted、21,392 duplicate、2,775 conflict、0 error；7 sessions，全部 completed。
- SQLite final counts：`sources=14`、`chat_sessions=7`、`messages=473236`、`message_sources=494628`、`message_variants=21392`、`import_errors=0`。
- 第二次真实导入：0 inserted、494,628 duplicate；上述 message/source/variant 行数保持不变，28 个 ImportBatch 全部 completed。

## Risk and rollback points

- 高风险点是 V5/0.1.0 对同一 stable ID 的结构差异；先通过 variant/conflict 记录暴露，再决定是否需要后续 mutation semantics，不在本任务静默覆盖。
- 高风险点是旧 V5 文件没有 `peerUid`；只使用文件名中明确的群号，解析失败即暴露，不按群名猜测。
- 生成的 SQLite 是本地可删除的派生导入产物；原始 `data/raw` 永不修改。若 schema 需要调整，只删除生成数据库后重跑，不回滚原始文件。
- 不触碰用户已有 `.gitignore` 意图；仅补充明确的本地 SQLite 产物忽略规则（如需要）。

## Review gates before start

- [x] 用户已批准本任务规划摘要及稳定 ID 冲突处理方式。
- [x] `prd.md`、`design.md`、`implement.md` 已通过 requirement convergence。
- [x] 相关 project/backend/guides 规范已读取。
- [x] `task.py start` 已完成，现已进入 implementation phase。
