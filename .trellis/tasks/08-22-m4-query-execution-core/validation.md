# M4 Query Execution Core Validation

## Validation date

2026-08-23 (Asia/Shanghai)

## Dependency evidence

- Local virtualenv: `openai-agents==0.22.0`, `openai==3.3.1`。
- `pyproject.toml` pins `openai-agents==0.22.0` because the streamed/cancellation implementation was checked against that installed API。
- Repository had no Python lockfile before this task；本任务没有凭空生成带 hash 的 lockfile。
- Live smoke 使用 `.env` 中已有配置；密钥只在当前进程读取，未进入日志、结果或任务文档。

## Deterministic quality gates

| Command | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/pytest -q` | 98 passed |
| `PYTHONPATH=src .venv/bin/ruff check src tests` | passed |
| `PYTHONPATH=src .venv/bin/mypy src` | passed，37 source files |
| `PYTHONPATH=src .venv/bin/python -m trivae --help` | passed，CLI help rendered |
| `PYTHONPATH=src .venv/bin/python .trellis/scripts/task.py validate .trellis/tasks/08-22-m4-query-execution-core` | passed |
| `git diff --check` | passed |

新增 deterministic 覆盖 Router、Planner、Orchestrator、stream/content/tool/usage events、one-turn multiple tool calls、tool budget finalization、SDK max-turn backstop、secret-safe failure、before/during cancellation、provider/model close 和 Application query/lifecycle。

## Opt-in DeepSeek live smoke

Provider/model：`deepseek` / `deepseek-v4-flash`。所有密钥字段均省略。

### Text completion

- Status: `ok`
- Response: non-empty（只校验存在性，不记录正文）
- Elapsed: 2257.8 ms

### Real Agent + SQLite `search_messages`

- Status: `ok`
- Fixture: 临时 SQLite，单条消息包含 `alpha live smoke evidence`
- Scope: temporary fixture 的 `qq:100`，`max_results=20`
- Actual tool request projection: keyword `alpha`、limit `20`
- Tool status/code: `ok` / none
- Termination: `completed`
- Tool count: `1`
- SDK usage projection: `input_tokens=1436`、`output_tokens=185`、`total_tokens=1621`、`requests` 未由该 provider response 提供
- Elapsed: 3130.1 ms
- Provider/model warning: no warning；malformed args 未发生

### Failure cases observed during smoke setup

- 第一轮 Agent probe 忘记把 Application 的 `CapabilityRegistry` 注入 runtime，得到 `RUNTIME_ERROR`、tool count `0`；这是 smoke harness composition 错误，修正为 `OpenAIAgentsRuntimeAdapter(application.capability_registry, ...)` 后通过。生产 Application composition 已按修正路径实现。
- 另一次使用 `max_results=5` 的 fixture 中，模型默认提交 limit `20`，Capability 返回已知 `INVALID_ARGUMENT`（`requested limit exceeds trusted max_results`）ToolEnvelope；runtime 没有吞错，仍通过 finalization 完成。将 live fixture scope 调整到其明确允许的 `20` 后验证了成功 tool path。该观察保留了 Scope enforcement 与 known Tool error recovery 的真实边界。

## Remaining pending

Conversation persistence schema、M5 Evidence/Citation、M6 Trace backend、M7 Evaluation implementation、HTTP/SSE/UI 和真实 workload 参数校准仍未在本任务中实现。
