# Model Provider Configuration — Technical Design

## Change boundary

最小行为差距位于 `config/settings.py` 与 `query/runtime/openai_adapter.py`：配置模型
和环境变量仍以 DeepSeek 为中心，Runtime adapter 的构造 helper 也使用 DeepSeek
命名。Trace 已有 provider/model/usage 的 provider-neutral projection，业务执行链不
需要改动。

本任务只修改：

- `src/trivae/config/settings.py` 与 `config/__init__.py`：通用配置类型、环境变量解析、
  legacy 兼容和 secret-safe projection；
- `src/trivae/query/runtime/openai_adapter.py`：把 client/model 构造收敛为
  OpenAI-compatible seam，并扩展已有 usage normalization；
- 配置与 Runtime deterministic tests；
- 本任务 Trellis 的 PRD、设计、执行和 validation 记录。

明确不修改 Retrieval、Citation、Planner、Tool、Evaluation、QueryOrchestrator、
Trace event schema 或 Agent loop。若验证发现 Provider 需要业务层补丁，应停在
adapter/config 边界并记录事实，不扩大范围。

## Configuration contract

```text
TRIVAE_MODEL_PROVIDER       deepseek | opencode-go
TRIVAE_MODEL_API_KEY       required secret
TRIVAE_MODEL_BASE_URL      required for new generic configuration
TRIVAE_MODEL_NAME          required model id
TRIVAE_MAX_TURNS           positive integer, default 8
TRIVAE_MAX_TOOL_ROUNDS     positive integer, default 3
TRIVAE_MAX_OUTPUT_TOKENS   positive integer, default 16384
TRIVAE_COMPLETION_MAX_TOKENS positive integer, default 2048
```

`deepseek` 保留既有默认 provider。为避免破坏只配置 legacy key 的旧 DeepSeek
workflow，若新 API key/base URL 变量均不存在，则分别读取 `DEEPSEEK_API_KEY` /
`DEEPSEEK_BASE_URL`；legacy-only DeepSeek 仍保留已有默认 base URL。只要新 generic
变量出现（包括空值），该字段就以新变量为准并按 required contract 校验。`opencode-go`
不读取任何 `DEEPSEEK_*` fallback。

配置对象可以保留一个简单 `DeepSeekSettings = ModelSettings` alias 作为外部导入的
短期兼容，但生产 Runtime 只引用 `ModelSettings`。repr 和 safe dict 只暴露 key
configured 状态，绝不保存或格式化 key 正文。

`.env` 仍由启动命令显式 export 到进程；Settings 的 mapping 注入 seam 保持纯函数式、
便于测试，也避免测试因为工作区存在本地 `.env` 而隐式读取真实 credential。

## Runtime seam

```text
ModelSettings
    -> AsyncOpenAI(api_key, base_url)
    -> OpenAIChatCompletionsModel(model, openai_client)
    -> existing Agent / Runner / SearchMessages SDK tool
    -> existing RuntimeResult / RuntimeEvent / Trace projection
```

Provider name、model name 和 base URL 只作为 adapter/config 的普通 metadata。两种
provider 都使用同一个 Chat Completions path，不复制 adapter，不在 Router/Planner/Tool
中分支。OpenCode Go 的 provider-facing model value 是 `deepseek-v4-flash`。

## Usage normalization

已有 Runtime/Trace contract 使用 `input_tokens`、`output_tokens`、`total_tokens`。
Adapter 在同一 provider boundary 读取 OpenAI Chat Completions 常见的
`prompt_tokens_details.cached_tokens`、`input_tokens_details.cached_tokens` 或
等价的 cache-read field，并只在真实字段存在时投影为 `cached_input_tokens`。
没有该字段时不写入 key，不把 unknown 变成零。`requests` 继续按已有语义保留。

## Security and observability

- `AsyncOpenAI` 只在 Runtime 构造时创建，key 只留在进程内 client；不进入 prompt、
  RuntimeResult、RuntimeEvent、Trace payload、CLI renderer 或 Exception message。
- 当前 Trace 继续记录 provider/model 和 normalized usage；base URL 不进入现有 Trace
  schema，避免扩大 event contract。Settings/adapter tests 验证 base URL 传到 client。
- Trace 的已有 redaction 与 bounded projection 继续作为最后安全边界；本任务不把
  provider raw response、Authorization 或完整 exception body 加入 Trace。

## Verification rationale

先用 deterministic settings/adapter tests 固定 precedence、model ID、base URL、usage
projection 和 secret safety，再运行完整质量门禁。若 `.env` 有本地 OpenCode Go key，
用命令级环境覆盖执行真实 basic/tool/streaming/citation/Trace smoke；输出只保留状态、
provider/model、termination、usage keys/counts 和 Trace safe facts。
