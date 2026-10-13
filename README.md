# Trivae

Trivae 是基于群聊数据的分析 Agent。主模型驱动 Router、Planner 和工具执行，答案经过现有 Evidence、Citation 与 Provenance 校验。Web UI、会话和 Evaluation 共用生产 Query 链路。

## 安装与启动

在仓库根目录执行，需 Python 3.12+、uv，以及构建前端所需的 Node.js 和 pnpm：

```sh
uv sync --extra dev
pnpm -C web install --frozen-lockfile
pnpm -C web build
```

没有 `.env` 时复制示例；已有文件直接编辑，不要覆盖旧凭据：

```sh
cp .env.example .env
```

主模型变量是 `TRIVAE_MODEL_PROVIDER` / `TRIVAE_MODEL_NAME`，任务示例中的 `TRIVIAE_MODEL_*` 不是现有配置入口。独立 Jev 的历史变量仍拼写为 `TRIVIAE_ROUTER_JEV_*`。

## Sign in with ChatGPT

```sh
uv run trivae auth login --provider chatgpt
uv run trivae auth status --provider chatgpt
uv run trivae auth models --provider chatgpt
```

登录命令打开系统浏览器，由本人完成 ChatGPT 登录和授权。Trivae 使用官方动态客户端注册、PKCE 和 OIDC 验证；授权必须包含订阅调用所需 scopes。凭证只存于本机受保护 Auth Store，不写入 `.env`、Trace、Evaluation 或前端。到期 access token 在实际调用时刷新；刷新失败显式提示重新登录。

从 `auth models` 返回的账号模型目录复制实际 slug，然后编辑 `.env`：

```dotenv
TRIVAE_MODEL_PROVIDER=chatgpt-plan
TRIVAE_MODEL_NAME=<实际返回的模型slug>
```

此模式使用 OAuth Bearer 与官方公开 `https://api.openai.com/v1` Responses API。已有 `TRIVAE_MODEL_API_KEY`、`DEEPSEEK_API_KEY` 和 base URL 不参与订阅调用；不会切换到 API key 计费。服务端请求始终 `store=false`、`stream=true`，只发送允许的字段，不发送 `max_output_tokens`、`max_tokens` 或 `temperature`。`TRIVAE_MAX_TURNS`、`TRIVAE_MAX_TOOL_ROUNDS` 与本地 Tool Result 预算继续生效。没有经过验证的 GPT context 元数据时沿用未知模型的 dynamic 预算，不根据模型名称推测能力。

再次登录默认复用所选注册身份。需要添加另一个账号或 workspace 时，执行 `uv run trivae auth login --provider chatgpt --new-account`。多个本机注册会话可用 `auth status` 检查；用返回的已签发 client ID 选择会话：

```sh
uv run trivae auth select --provider chatgpt --account <已签发client_id>
uv run trivae auth models --provider chatgpt
```

运行中的 Runtime 绑定首次选定的注册会话。执行 `auth select` 或添加新账号后，重新启动 Web / CLI，再核对该账号目录和模型 slug，保证模型目录与 OAuth 会话一致。配置 readiness 只检查本地授权与 scope，不保证网络、额度或模型调用成功。

## 在 Web UI 提问

已有 Canonical 数据库时启动：

```sh
uv run trivae web --database data/trivae.sqlite3 --host 127.0.0.1 --port 8710
```

浏览器自动打开 `http://127.0.0.1:8710`。先选择来源范围，再提问；模型使用现有工具检索并生成带引用的答案。修改 `.env` 后重启进程；Shell 已导出的同名环境变量优先于 `.env`。`trivae web` 是准确命令，仓库没有 `webui` 子命令。

新数据库先放入 QQChatExporter JSON 并导入：

```sh
uv run trivae import --raw-dir data/raw --database data/trivae.sqlite3
```

Jev 仍使用独立 `OPENROUTER_API_KEY`，默认 enabled/shadow 行为不随主模型变化。OAuth token 不会发送给 Jev；如需调整 Jev 模式，显式编辑其专属变量。

## 额度、失败与退出

在 ChatGPT 的 **Settings → Usage** 查看订阅使用量和应用管理。Plus 的五小时总用量由所有接入应用共享，各应用不会获得独立额度；不从一次错误推断整个订阅已耗尽或重置时间。具体授权和限制以官方 [会话与额度说明](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions) 为准。

额度限制、授权撤销、scope 不足、流中断或协议错误会明确失败，不自动换到收费 API key 或其他 Provider。查看 `auth status` 和该次 Query 的 Trace；Web UI 可打开过程与引用。Trace 保留实际 provider/model、用量、配置和安全错误原因，不保存 OAuth token。

```sh
uv run trivae auth logout --provider chatgpt
```

退出会撤销 renewable session 并清除所选会话的本地 token，保留注册身份和主机标识以便重新登录；其他本机注册会话可通过 `--account` 明确选择。远端撤销失败会显式报告，本地 token 仍会清除；在 ChatGPT Settings → Usage 管理对应应用。切回 DeepSeek 时编辑 `.env` 并重启：

```dotenv
TRIVAE_MODEL_PROVIDER=deepseek
TRIVAE_MODEL_NAME=deepseek-flash
TRIVAE_MODEL_BASE_URL=https://api.deepseek.com
TRIVAE_MODEL_API_KEY=<你的DeepSeek_API_key>
```

## Evaluation 与验证

生产 Evaluation Query 使用同一个 Runtime，实际配置从 `runtime.configuration` Trace 派生；历史 frozen Variant / DeepSeek Baseline 不改写。切换 Provider 必须建立新的 Variant 和结果目录，不能把模型差异解释为检索改善。独立 retrieval annotator 和 claim judge 当前使用 Chat Completions，明确拒绝 `chatgpt-plan`；运行它们时显式选用 DeepSeek 或 OpenCode Go 的配置文件，不借用 OAuth、不自动改变计费。

自动化验证：

```sh
uv run ruff check src tests
uv run mypy src
uv run pytest
```

授权成功、目录确认和 `.env` 设置完成后，运行四类真实生产 Query 验证；每次使用一个新的结果目录：

```sh
uv run python scripts/verify_chatgpt_plan.py --database data/trivae.sqlite3 --topic Trellis --output data/evaluation/chatgpt-plan/new-run
```

脚本检查事实检索、复杂工具分析、多轮追问和结构化引用答案，保存结果与 Trace 证据。Mock 通过与真实授权、刷新、模型调用成功是不同事实；没有完成本人浏览器授权时，真实账号调用仍未验证。

2026-10-13 本机实测：官方 OAuth 和账号模型目录查询成功，实际选择目录中的 `gpt-6.1-sol`。四类查询全部 `valid`，分别产生 1 / 5 / 4 / 2 个 Citation binding；另一次 Web 查询返回完整 NDJSON 终态与来源，Provider SSE 均确认 `response.completed`。原始本机证据在 ignored `data/evaluation/chatgpt-plan/20261013-sol-06/`，可核验事实摘要见 [ChatGPT 接入事实记录](interview-docs/事实核验-ChatGPT接入.md)。自然过期后的真实刷新未执行，刷新与轮换由 Mock 覆盖。该运行验证工程接入，不构成模型质量 Benchmark 或检索优化结论。
