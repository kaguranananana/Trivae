# DeepSeek Tool / Provenance 修复验证

## Baseline 与证据

- 业务代码修改前相关测试：`64 passed`。
- Agents SDK：`0.22.0`。
- 真实数据使用临时 SQLite；复制导入 `73014` 条真实消息，canonical 数据库未修改。
- 修复前 Trace：模型多次提交 `limit=20/10`，trusted `max_results=5`，产生 `INVALID_ARGUMENT`；一次失败把无 message 的 Tool Call 5 父级 identity 与 Tool Call 6 的 message item 混合，产生 `UNRESOLVED_MESSAGE_SOURCE`。

## 修复内容

- provider-facing `search_messages` schema 现在携带本次 trusted result bound、`minimum=1`、动态 `maximum`、bounded default 和字段说明；`strict_json_schema=False` 保持不变。
- `SearchMessagesInput` 在边界严格校验所有 string-list filter，不做隐式修正。
- 每个 `message_sources`/`structured_sources` entry 携带完整 parent identity；Prompt 禁止跨 Tool Result 拼接或在空 source 列表上造 citation。
- M5 Citation Finalizer、ExecutionScope、Conversation commit boundary 未放宽；未重开 M5 contract。

## Deterministic validation

- Runtime / Capability / Evidence targeted tests：`59 passed`。
- `ruff check src tests`：通过。
- Regression 覆盖动态 schema、非法 provider 参数、expanded provenance、跨 Tool Result locator 拒绝和现有 trusted hydration。

## Real DeepSeek smoke

同一次临时真实数据快照上执行 4 个 case：

| Case | Query success | Tool errors | Finalization | Conversation messages | Trace |
| --- | --- | --- | --- | ---: | --- |
| simple keyword | true | 0 | completed | 2 | completed / complete |
| trusted session filter | true | 0 | completed | 2 | completed / complete |
| context expansion | true | 0 | completed | 2 | completed / complete |
| no result | true | 0 | completed | 2 | completed / complete |

其中 simple keyword 有 partial Tool Result，但 partial limitation 被保留；no result 没有生成消息 Evidence；两者均未放宽 Citation 校验。

## Quality gates

- `PYTHONPATH=src ./.venv/bin/pytest -q`：`136 passed in 1.48s`
- `./.venv/bin/ruff check src tests`：通过
- `./.venv/bin/mypy`：`Success: no issues found in 47 source files`
- `git diff --check`：通过
- `python3 ./.trellis/scripts/task.py validate deepseek-tool-provenance`：通过
