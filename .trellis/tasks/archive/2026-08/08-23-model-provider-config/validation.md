# Model Provider Configuration — Validation

## Validation date

2026-08-23（Asia/Shanghai）。所有真实 credential 只存在于本机 `.env` 和当次命令进程；
本文、源码、测试、Trace、日志和 Git diff 不包含 key 内容。

## Deterministic quality gates

| Command | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/pytest -q` | **214 passed** |
| `PYTHONPATH=src .venv/bin/ruff check src tests` | **passed** |
| `PYTHONPATH=src .venv/bin/mypy src` | **passed; no issues in 58 source files** |
| `PYTHONPATH=src .venv/bin/python -m trivae --help` | **passed** |
| `git diff --check` | **passed** |

新增 deterministic evidence：

- `opencode-go` 与 generic DeepSeek 配置能加载；OpenCode Go 的 model value 为
  `deepseek-v4-flash`，没有 `opencode-go/` 前缀。
- 新 `TRIVAE_MODEL_*` 同时存在时覆盖 `DEEPSEEK_*`；新变量显式为空时不 fallback。
- DeepSeek legacy-only 配置继续读取 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`，并保留
  旧默认 URL；OpenCode Go 不读取 legacy DeepSeek 字段。
- provider、model、base URL、API key 缺失/非法均在 provider 请求前显式失败。
- `repr(ModelSettings)`、`to_safe_dict()`、adapter request projection 和已有 Trace
  projection 均不包含 fake/real API key；Trace metrics 只投影 provider/model/usage，
  当前 Trace schema 不保存 base URL。
- Chat Completion usage 的 `prompt_tokens_details.cached_tokens` 被归一化为
  `cached_input_tokens`；Provider 没有 cache 字段时该 key 缺失，不补 `0`。

## OpenCode Go real smoke

### Configuration

使用本机 `.env` 中已有 credential，通过命令级环境覆盖切换到：

```text
provider: opencode-go
model: deepseek-v4-flash
base URL: https://opencode.ai/zen/go/v1
protocol: OpenAI-compatible Chat Completions
```

没有修改 `.env` 文件，也没有输出 credential。

### Basic completion

- **passed**：`Trivae -> OpenAI Agents SDK Agent/Runner -> OpenAIChatCompletionsModel -> AsyncOpenAI -> OpenCode Go`。
- termination：`completed`；final output non-empty。
- normalized usage keys：`requests`、`input_tokens`、`output_tokens`、`total_tokens`、
  `cached_input_tokens`。

### Tool calling / streaming / citation / Trace

在临时 SQLite fixture（单条 synthetic message，未修改项目 canonical database）上运行
正式 `TrivaeApplication.query`：

- **passed**：`search_messages` tool call count `1`，tool status `ok`。
- **passed**：tool result 回到模型，最终 Runtime termination `completed`。
- **passed**：stream event 包含 tool started/completed、answer delta/completed 和
  query completed。
- **passed**：validated answer、`1` 个 citation binding、`1` 个 evidence item、`1`
  个 evidence source。
- **passed**：Trace terminal `completed`、completeness `complete`；记录 provider
  `opencode-go`、model `deepseek-v4-flash` 和 normalized usage；Trace safe projection
  不包含 API key。

### Provider compatibility difference found

真实 endpoint probe 得到以下事实：

1. `tools` + `response_format={"type":"json_object"}` 在 OpenCode Go 上返回
   `finish_reason=stop`、无 tool call；即使 `tool_choice=required` 也如此。
2. 去掉 JSON mode 后同一模型返回 `tool_calls`；这是 Provider protocol combination
   差异，不是 Retrieval/Citation 语义问题。
3. Runtime Adapter 增加了 provider-boundary model-settings projection：OpenCode Go
   在有 tools 的请求中移除 `response_format`，无 tools 时保留；最终 Answer Artifact
   仍由现有 prompt + deterministic Finalizer 校验。没有增加 retry、fallback、repair
   或第二套 Agent loop。

## DeepSeek official live smoke

未执行 DeepSeek 官方 API 的真实 smoke；本次本地 credential 被用于 OpenCode Go 验证。
DeepSeek 官方路径已由 generic configuration、legacy fallback、同一 adapter 构造和
既有 deterministic Runtime tests 覆盖，但不能据此宣称 DeepSeek 官方本轮 live
tool/streaming/citation 通过。

## Architecture principle

> Trivae 的 Agent Runtime 依赖模型协议能力，而不依赖具体模型厂商。对于支持
> OpenAI-compatible Chat Completions 的 Provider，应通过配置和 Runtime Adapter 接入，
> 不让 Provider 差异泄漏到 Router、Planner、Tool、Retrieval、Citation、Evaluation
> 等业务层。

本次实际验证的 OpenCode Go / `deepseek-v4-flash` 差异被限制在 config 与 Runtime
Adapter；业务执行链、Citation contract、Trace contract 和 Application composition
保持不变。

## Remaining unknowns

- 本次只观察到 OpenCode Go 返回可归一化的 input/output/total/cache-read usage；未测量
  更大 workload 的 cache hit rate、成本或答案质量。
- DeepSeek 官方与 OpenCode Go 的长期 stochastic tool/structured-output 行为仍需在
  各自 credential 和固定 Evaluation Snapshot 上独立校准。
