# Provider Migration：OpenCode Go → Official DeepSeek

> 状态：Confirmed（2026-09-11）
>
> 目的：把当前 Runtime、Planner/Router completion、Benchmark Judge 和 retrieval blind annotator 的新执行身份切换为 DeepSeek 官方 API，同时保留历史 OpenCode Go 运行材料的事实边界。
>
> **历史配置快照**：本文的“当前”和 `TRIVAE_MODEL_*` 示例只描述 2026-09-11 的迁移方案，不是当前默认配置。现行模型 profile 与覆盖顺序以 [`config/models.yaml`](../../../../config/models.yaml) 和 [docs/configuration.md](../../../../docs/configuration.md) 为准。

## 1. 结论

新运行配置使用：

```text
TRIVAE_MODEL_PROVIDER=deepseek
TRIVAE_MODEL_BASE_URL=https://api.deepseek.com
TRIVAE_MODEL_NAME=deepseek-flash
TRIVAE_MODEL_API_KEY=<local secret, never commit>
```

`.env` 已被 `.gitignore` 忽略；代码、测试、Trace、日志、Evaluation artifact 和本文不保存 key 正文。
`load_settings()` 在 CLI、Web/Application、Evaluation、Judge 和 retrieval annotator 的调用边界读取同一套
generic `TRIVAE_MODEL_*` 配置。运行时不在模块导入阶段创建 client，因此配置变更在下一次调用
`load_settings()` 后生效；已创建的 Application/runtime 不会静默热切换 provider。

当前官方资料：

- [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)：正式模型名为
  `deepseek-flash`；旧 `deepseek-v4-flash` 是已退役模型的兼容别名，仍会路由到当前 Flash 服务；官方
  OpenAI-format base URL 是 `https://api.deepseek.com`，context 为 1M，且列出 JSON Output 与 Tool Calls。
- [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)：thinking 默认 enabled/high，OpenAI
  format 支持 `reasoning_effort=low|high|max`；工具请求的后续轮次必须回传之前所有
  `reasoning_content`。
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)：使用
  `response_format={"type":"json_object"}`，prompt 必须明确 JSON，输出预算必须足够闭合。
- [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)：标准 OpenAI-compatible tools 请求可用。

## 2. 身份与能力表

| provider / model | 角色 | context | reasoning 请求 | JSON + tools | headers |
|---|---|---:|---|---|---|
| `deepseek / deepseek-flash` | 当前官方运行身份 | 1,000,000 | exact registry → `low` | 保留标准 `response_format`；由真实 smoke 验证组合 | 不发送 OpenCode Go 头 |
| `opencode-go / deepseek-v4-flash` | 历史运行身份 | 1,000,000 | exact registry → `low`，保持历史预算行为 | 仅该 provider 去掉 tool turn 的 `response_format`，并保留已验证的有界 JSON repair | 发送 `x-opencode-session` 与 `User-Agent` |

能力和传输分开处理：

- `model_capabilities.py` 只按 `(provider.casefold(), model.casefold())` exact lookup 返回 context 和已验证
  reasoning 档位；unknown 组合不从字符串猜测。
- `openai_adapter.py` 只在 `opencode-go` 选择兼容 subclass 和 session headers；官方 DeepSeek 使用普通
  observed Chat Completions model，所以 tools 与 JSON mode 不进入 OpenCode workaround。
- Judge 和 retrieval annotator 使用同一 reasoning resolver；它们只按 provider 选择 OpenCode headers，
  不复制 Runtime 的 tools/JSON compatibility branch。

## 3. Reasoning / multi-turn contract

官方 thinking mode 的默认是 high，但 Trivae 的 `max_tokens` 同时覆盖 provider reasoning 和最终 JSON。
因此 `deepseek/deepseek-flash` 和历史 `opencode-go/deepseek-v4-flash` 都由 registry 显式请求 `low`，这是
可审计的预算策略，不是模型名称猜测。

`openai-agents==0.22.0` 的 Chat Completions converter 已处理 DeepSeek 的公开 `reasoning_content`：stream
delta 进入 SDK reasoning item；当下一次请求含 tools 时，converter 把前一轮 reasoning summary 回放成
assistant message 的 `reasoning_content`。仓库回归测试用真实 SDK converter 断言了“reasoning item + function
call + tool result”输出的 assistant message 含 `reasoning_content`。因此没有新增手写 agent loop、重试或
伪造 hidden CoT；Trace 只保留 bounded output shape/计数，不落 reasoning 正文。

## 4. JSON / tool / completion contract

- Runtime final synthesis 仍使用 JSON mode 和独立 `max_output_tokens`；Planner/Router completion 仍使用
  JSON mode、独立 `completion_max_tokens` 和相同的 exact reasoning resolver。
- 官方 DeepSeek path 让 SDK 原样发送 `response_format` 与 tools；OpenCode Go 的 workaround 只存在于
  `_OpenCodeGoChatCompletionsModel`，不能被 provider-neutral 代码复用。
- Judge 的 max output 使用 `settings.max_output_tokens`，不回退到 Router/Planner 的短预算；retrieval
  annotator 也使用同一独立预算。
- Provider failure 保持显式失败；没有静默 fallback、应用层 retry、切换 provider 或吞掉 error body 的
  兼容分支。

## 5. Evaluation boundary

旧 benchmark 材料保持原样：

- 历史 Development 为 37 cases × 5 variants = 185 runs，身份是
  `opencode-go/deepseek-v4-flash`。
- v1 holdout 的 90/90 `SettingsError` 是已封存的一次性运行事实，没有 provider request/answer/quality
  metric；不删除、覆盖或重新运行它。
- v2 recovery 是独立 identity 的已暴露 holdout recovery，不改写 v1 claim。

任何基于官方 DeepSeek 的新 Evaluation 必须先创建新的 provider/model identity、environment manifest、
freeze/registration 和独立输出目录；执行 worktree 显式传入 `--env-file`。不得把新 identity 的结果追加到
旧 `opencode-go/deepseek-v4-flash` 目录，也不能把新结果宣称为旧 benchmark 的可比 continuation。

## 6. Validation matrix

确定性回归：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
git diff --check
```

覆盖点：generic official settings/base/model；exact context/reasoning registry；official model 无 OpenCode
headers；official JSON + tools standard path；Router/Planner、Judge、盲标 reasoning 一致；SDK
`reasoning_content` replay；旧 OpenCode header/workaround 不回归；secret-safe settings/Trace projection。

真实 smoke 必须是 bounded 且只输出 safe metadata：A no-tool；B single-tool；C multi-turn tool calling；D
JSON finalization；E long tool result。每一项记录 provider/model、status、finish reason、tool round/count、
usage 是否存在、context source/budget 和错误 category；不输出回答正文、工具正文、Trace 正文、key 或
provider raw response。Smoke 不等于 benchmark，不修改任何旧 Evaluation artifact。

## 7. Real bounded smoke result（2026-09-11）

本机 `.env` 已配置 generic key；以下请求均实际走 `deepseek / deepseek-flash`，只保留安全元数据：

| case | status | tool calls / rounds | model turns | 关键事实 |
|---|---|---:|---:|---|
| A no-tool | `completed` | 0 / 0 | 1 | 1 reasoning item；usage present |
| B single-tool | `completed` | 1 / 1 | 2 | Trace `complete`；context `verified_model_registry` / 1,000,000 |
| C multi-turn tools | `completed` | 2 / 2 | 3 | `lexical_search → get_message_context`；Trace `complete`；usage present |
| D JSON finalization | `completed` | 0 / 0 | 1 | `finalization_status=valid`；Artifact present |
| E long tool result | `completed` | 1 / 1 | 2 | Host estimate 61,218 tokens；347 messages projected；0 message truncation |

最终安全元数据采集（不含回答、工具正文、Trace 正文或 key）如下：

| case | trace id | latency ms | usage | finish | error category |
|---|---|---:|---|---|---|
| A no-tool | `trace-8ea830f07b3b41c3ab137d62d5c4e098` | 4,394 | present | `stop` | none |
| B single-tool | `trace-89eb7e6bec5d4b36af0865b6ceb865df` | 8,084 | present | `stop` | none |
| C multi-turn tools | `trace-8335da4a75284b15b635aff45f76c2a8` | 14,373 | present | `stop` | none |
| D JSON finalization | `trace-b3a2a2fd4bf84203a32271d12a154f02` | 4,697 | present | `stop` | none |
| E long tool result | `trace-58331998ad8942389943ba54c65f8bc1` | 9,232 | present | `stop` | none |

五条请求的 `trace_completeness` 均为 `complete`、`finalization_status` 均为 `valid`、Artifact 均存在；B/C/E 的
context source 均为 `verified_model_registry`、context window 均为 1,000,000。E 的
`host_tool_result_estimated_tokens=61,218`、`projected_messages=347`、`omitted_messages=0`、
`projection_truncated_count=0`。

另执行 1 条官方 Judge smoke：`completed`、1 atomic claim、0 citation、
`llm_assisted_provisional`。Judge 使用官方 model/base URL，未发送 OpenCode Go headers。
上述 smoke 没有重跑旧 benchmark，也没有写入旧 Evaluation 目录；临时 Conversation/Trace/评测数据库均在
临时目录中清理。

随后为验证 async lifecycle 又执行了一次同样的 bounded A–E 复核；五条请求均在首轮模型响应前以
`APITimeoutError` 结束（约 26 秒、无 model/tool turn、无 usage），单条 direct Runtime 复现了同一外部超时。
该复核没有加入重试、fallback 或 provider 切换；上表保留的是先前完整成功的 A–E 运行事实，外部超时作为独立
的可见失败事实记录，不改写为成功。
