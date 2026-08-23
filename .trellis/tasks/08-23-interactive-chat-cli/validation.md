# Validation

## Automated

- `./.venv/bin/pytest`: 167 passed。
- `./.venv/bin/ruff check src tests`: passed。
- changed files 的 `ruff check`: passed。
- `./.venv/bin/mypy src`: passed。
- `python3 -m compileall -q src tests`: passed。
- `git diff --check`: passed。

`ruff check .` 仍会报告仓库已有 `.codex/hooks`、`.trellis/scripts` 代码的 lint 问题；本次没有修改这些无关路径，`src` 与 `tests` 已单独通过。

## Deterministic CLI Evidence

- 新增 CLI 测试覆盖 parser/default database、Application session read、单群/All chats scope、formal QueryRequest、Conversation 复用、`/new`、final answer、Trace、退出、EOF/Ctrl+C、Settings error 和 Runtime/Retrieval 边界。
- 测试使用 fake Application 和 scripted result，不调用真实 DeepSeek。

## Local Smoke

- `data/trivae.sqlite3` 存在，`trivae chat` 实际列出 7 个 session；选择一个 session 后可进入交互循环，EOF 正常退出。
- 发送一个问题实际经过 CLI/Application 初始化，但环境缺少 `DEEPSEEK_API_KEY`，命令展示分类错误并带 Trace ID 后退出。
- 未宣称真实 DeepSeek Query 成功；由于缺少 `DEEPSEEK_API_KEY` 和 `TRIVAE_MODEL_NAME`，未执行两轮真实 provider smoke test。

## Scope Review

修改仅涉及 CLI、既有 Canonical Read adapter、Application read facade、CLI 测试和本任务记录；未修改 Router、Planner、Runtime、Retrieval、Evidence、Conversation Store、Trace Store 或 Evaluation 语义。
