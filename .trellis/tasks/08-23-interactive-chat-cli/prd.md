# Interactive chat CLI

## Goal

为真实人工体验提供 `trivae chat` 交互式 CLI：用户先选择 Canonical Store 中的群聊，再通过正式 `TrivaeApplication.query()` 连续提问，保持可信的 session scope、Conversation、最终答案和 Trace 可见性。

## Requirements

- 基于已合并 M7 的 `main` 实现，不改变 Evaluation 的生产 Query 语义。
- `trivae chat` 使用现有 Composition Root / Application；默认数据库为当前项目约定的 `data/trivae.sqlite3`，支持已有 CLI 风格的显式数据库参数。
- 启动时通过正式 Application / Read Contract 读取实际 session 列表，展示稳定可读名称，并提供 `0. All chats`。
- 选择单个 session 后，整个 CLI 生命周期固定 `ExecutionScope(allowed_session_ids=(id,))`；All chats 使用 `allowed_session_ids=None`。
- 普通输入转换为正式 `QueryRequest`，调用 `await application.query(request)`，不在 CLI 直接调用 Runtime、Capability、Retrieval 或 SQLite。
- 首轮不传 `conversation_id`；后续复用 `QueryResult.conversation_id`；`/new` 只清空 conversation，不改变 scope；`/exit`、`/quit`、EOF、Ctrl+C 正常退出。
- 成功回答只展示 `result.final_answer` 和 Trace ID；不得使用 `runtime_answer` 作为 fallback。预期业务错误应可读，未知错误保持可诊断性。
- 不新增 Web/TUI/streaming/历史浏览/动态切换等非本次范围能力。

## Acceptance Criteria

- [ ] `trivae chat` 被现有 CLI parser 识别，并保留 import、trace、evaluation CLI 行为。
- [ ] 可从真实 read/application boundary 读取 session，正确构造单群与 unrestricted `ExecutionScope`。
- [ ] 可连续调用正式 Query path，验证首轮/后续 Conversation ID、`/new` 和稳定 scope。
- [ ] 成功路径展示 `final_answer` 与 Trace ID；没有正式答案时不输出 runtime 原始答案。
- [ ] `/exit`、`/quit`、EOF、Ctrl+C 无长 traceback。
- [ ] 新增测试不依赖真实 DeepSeek；完整 `pytest`、`ruff check .`、`mypy src` 通过，或记录仓库真实命令/现有阻塞。
- [ ] 若环境提供数据库、API Key、模型配置和网络，完成至少两轮真实 smoke test；否则明确列出缺失条件。

## Scope Boundary

实现集中在 `src/trivae/interfaces/cli.py`、必要的 `src/trivae/bootstrap/application.py` read facade，以及 CLI 相关测试。QueryOrchestrator、Router、Planner、Runtime、Retrieval、Evidence、Conversation Store、Trace Store 和 Provider composition 不重构、不复制、不改变生产语义。
