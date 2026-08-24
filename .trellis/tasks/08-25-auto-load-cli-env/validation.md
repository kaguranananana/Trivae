# Validation: Automatic CLI dotenv loading

## 1. Problem / Motivation

用户必须先在 shell 执行 `source .env` 才能启动真实 Provider；直接执行 `trivae chat` 时，Provider 配置缺失，人工启动路径与项目实际配置脱节。问题归属 CLI 启动边界：`load_settings()` 被多个库入口复用，不应因为 CLI 便利性而增加工作目录文件系统副作用。

## 2. Design Rationale

```text
manual shell source only
  -> rejected: every user must remember an extra shell step
settings scans .env implicitly
  -> rejected: library/tests acquire hidden filesystem and credential side effects
CLI-only dotenv loader before Application creation
  -> selected: fixes the real startup path while preserving settings purity
```

`config/dotenv.py` 先解析完整文件，再用 `setdefault` 注入缺失环境变量；这样 shell 环境变量（包括显式空值）保持优先，格式错误不会留下半份配置。

## 3. Why not

- 不引入第三方 dotenv 依赖：当前需求只需要有限、可审计的 `KEY=VALUE` 语法，依赖扩展没有当前证据支持。
- 不向父目录递归寻找 `.env`：当前 CLI 的数据库路径和用户意图都以当前工作目录为边界；需要其他位置时使用显式 `--env-file PATH`。
- 不将 `.env` 自动应用到 `import`、`trace` 或库 API：这些入口没有本任务要求的 Provider-backed chat startup contract。

## 4. Failure Cases

| 分类 | Scenario | Root cause / handling | Validation |
| --- | --- | --- | --- |
| regression test case | malformed assignment after a valid line | parser previously could have injected partial state; implementation parses all assignments before mutation | `tests/test_dotenv.py::test_parse_errors_are_reported_before_any_assignment_is_injected` |
| regression test case | process env contains an empty required value | `setdefault` must not treat empty as missing; `load_settings()` remains the owner of the explicit-empty error | `tests/test_dotenv.py::test_existing_environment_values_win_including_empty_values` |
| regression test case | library caller runs with a local `.env` | hidden file discovery would violate settings purity | `tests/test_dotenv.py::test_load_settings_does_not_read_default_dotenv_implicitly` |
| measured test failure | macOS temporary-directory path compared through `/var` vs `/private` symlink | test asserted spelling instead of canonical file identity | assertion now compares resolved paths; focused suite passes |

## 5. Evaluation / Evidence

- measured fact: focused dotenv + CLI suite passes with 29 tests.
- measured fact: full project suite passes with `291 passed`.
- measured fact: `.venv/bin/ruff check src tests` passes.
- measured fact: `.venv/bin/mypy src` reports no issues in 80 source files.
- measured fact: from the repository root, a real CLI process ran with `TRIVAE_MODEL_PROVIDER`, `TRIVAE_MODEL_API_KEY`, `TRIVAE_MODEL_BASE_URL`, `TRIVAE_MODEL_NAME`, `DEEPSEEK_API_KEY`, and `DEEPSEEK_BASE_URL` removed from the process environment. Without `source .env`, startup reported `Provider: ready (opencode-go, deepseek-v4-flash)` and the existing database reported `sessions=7, messages=473236`; stdin was closed, so no Query was issued.
- no API key, endpoint credential, or `.env` value was recorded in this artifact.

## 6. Observability / Debugging

`DotenvError` reports only file path, line number, format, or OS read diagnosis. `_run_chat_command()` maps it to the existing `Error: ...` CLI projection and returns 1 before Application creation. The loader does not log values or return them in a report; Provider readiness remains the Application-owned safe projection.

## 7. Scale / Performance

The loader reads one small configuration file once before Application creation. No performance benchmark is warranted for this path; current real startup remains dominated by existing database/semantic initialization, not dotenv parsing.

## 8. Boundary / Ownership

```text
CLI parser / _run_chat_command
  owns command arguments and startup ordering
config/dotenv.py
  owns bounded text parsing and process-environment injection
config/settings.py
  owns Provider validation and remains filesystem-pure
Application
  owns Provider/client, database, semantic index, Query, Trace, and lifecycle
```

The loader depends only on the standard library and is imported by the interface layer. It does not read SQLite, create a Provider client, or participate in Query execution.

## 9. Evolution

If real configuration files require multiline values, interpolation, encrypted stores, or a second startup entry point, record that concrete failure first and extend the parser contract with dedicated tests. Until such evidence exists, the bounded parser and explicit `--env-file` boundary remain the smallest supported surface.

## 10. Interview Defense Notes

- Q: 为什么不把 `.env` 读取放进 `load_settings()`？
  Evidence: `config/settings.py` remains mapping-only; `test_load_settings_does_not_read_default_dotenv_implicitly`.
- Q: 如何证明 shell 配置不会被覆盖？
  Evidence: `setdefault` implementation and `test_existing_environment_values_win_including_empty_values`.
- Q: 如何证明真实启动不再需要 `source`？
  Evidence: no-manual-source smoke in this validation; Provider readiness reports configured `opencode-go` / `deepseek-v4-flash` before EOF exit.
- Q: 配置错误如何定位？
  Evidence: typed `DotenvError`, path/line diagnostics, CLI non-zero mapping, and malformed-file tests.
