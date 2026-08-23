# Model Provider Configuration — Implementation Plan

## Ordered checklist

- [x] 读取项目 AGENTS、backend/project spec、M4a ADR/research、当前 Settings、Runtime、
  Application、CLI、Trace、`.env`/`.gitignore` 和 DeepSeek tests。
- [x] 建立 baseline：clean branch、205 tests、ruff、mypy。
- [x] 将 `DeepSeekSettings` 收敛为通用配置对象，加入两 provider、new-first precedence、
  legacy DeepSeek fallback 和 safe projections。
- [x] 将 Runtime adapter 的构造 helper 与类型依赖改为 provider-neutral；不改变 SDK
  Runner、tool registration、streaming 或 lifecycle。
- [x] 扩展 usage projection 到真实存在的 cache-read 字段，保持缺失字段 unknown。
- [x] 补配置、adapter、usage 和 secret-safety tests，更新原有 DeepSeek assertions。
- [x] 运行 `PYTHONPATH=src .venv/bin/pytest -q`、`ruff check src tests`、`mypy src`、
  `python -m trivae --help`、`git diff --check`。
- [x] 若 credential 可用，运行 OpenCode Go basic completion、真实 `search_messages` tool
  call、streaming、citation/finalization 和 Trace projection smoke；不把 key/正文写入
  输出或仓库。
- [x] 运行 Trellis check/validation，记录 measured facts、兼容差异和 remaining unknown。

## Expected files

- `src/trivae/config/settings.py`
- `src/trivae/config/__init__.py`
- `src/trivae/query/runtime/openai_adapter.py`
- `tests/test_agent_runtime.py`（必要时拆出最小 settings test）
- 本任务 Trellis artifacts

## Rollback boundary

若验证发现 SDK 或 Provider 兼容问题，只回滚 config/adapter/provider-normalization
改动；不触碰 Retrieval、Citation、Planner、Tool、Evaluation 和 Trace contract。
