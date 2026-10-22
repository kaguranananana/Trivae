# 配置、索引与故障定位

基础安装、导入和 Web 启动见[本地上手](getting-started.md)。本文保留 Provider、OAuth、多账号、Jev、索引升级和真实链路验证的操作细节。命令中的 `<…>` 均为待替换占位，不包含真实账号或群聊标识。

## 配置加载与主模型

`web`、`chat` 和模型评测入口读取当前工作目录的 `.env`，Shell 已导出的同名值优先，包括空字符串。修改 `.env` 后重启进程；`chat` 可用 `--env-file`，`eval` 可在子命令前指定 `--env-file`，`web` 当前没有这个参数。库层直接调用 Application 时，由调用者负责加载环境。

主模型配置使用 `TRIVAE_MODEL_*`，不是 `TRIVIAE_MODEL_*`。建议沿用 [`.env.example`](../.env.example) 的 DeepSeek 示例：

```dotenv
# 主模型配置；密钥必须替换为自己持有的有效值。
TRIVAE_MODEL_PROVIDER=deepseek
TRIVAE_MODEL_NAME=deepseek-flash
TRIVAE_MODEL_BASE_URL=https://api.deepseek.com
TRIVAE_MODEL_API_KEY=<你的DeepSeek_API_key>
```

当前支持 `deepseek`、`opencode-go` 和 `chatgpt-plan`。API key 模式必须填写模型名及对应 Provider 的 base URL 和 key；使用 `opencode-go` 时由用户明确提供其端点与账号可用模型，不自动借用 DeepSeek 配置。DeepSeek 历史变量 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 仍受支持，但仅在对应新变量未出现时生效；新变量存在而为空会报错。只有未使用新 key 变量的旧 DeepSeek 配置保留默认 base URL。

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `TRIVAE_MAX_TURNS` | `8` | SDK 执行轮数上限 |
| `TRIVAE_MAX_TOOL_ROUNDS` | `3` | 工具轮数预算 |
| `TRIVAE_MAX_OUTPUT_TOKENS` | `16384` | API key Provider 的 Runtime 输出预算 |
| `TRIVAE_COMPLETION_MAX_TOKENS` | `2048` | Router / Planner completion 输出预算 |
| `TRIVAE_TOOL_RESULT_BUDGET_MODE` | `dynamic` | 工具结果预算模式，另可显式设 `fixed` |
| `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS` | 未配置 | 显式提供模型 context 元数据 |
| `TRIVAE_PER_CALL_TOOL_RESULT_PERCENT` | `50` | 单次工具结果占 context 的百分比 |
| `TRIVAE_PER_CALL_TOOL_RESULT_CAP` | `128000` | 单次工具结果预算上限 |
| `TRIVAE_RUN_TOOL_EVIDENCE_PERCENT` | `25` | 单次 Run 证据池占 context 的百分比 |
| `TRIVAE_RUN_TOOL_EVIDENCE_CAP` | `256000` | 单次 Run 证据池预算上限 |
| `TRIVAE_RUN_TOOL_EVIDENCE_BUDGET` | 未配置 | 显式覆盖单次 Run 的证据池预算 |

未知模型 context 使用现有 dynamic 预算的未知上下文边界，不按模型名称猜测窗口大小。这些是执行预算，不是答案正确性指标。

## Sign in with ChatGPT

```sh
uv run trivae auth login --provider chatgpt
uv run trivae auth status --provider chatgpt
uv run trivae auth models --provider chatgpt
```

登录命令打开系统浏览器，由本人完成 ChatGPT 登录与授权。实现采用动态客户端注册、PKCE 和 OIDC 验证；授权必须包含订阅调用所需 scopes。凭证只保存在本机受保护的 Auth Store，不写入 `.env`、Trace、Evaluation 或前端。access token 到期后在实际调用时刷新，失败时明确要求重新登录。

身份凭证的 `iat` / `nbf` / `exp` 校验固定允许 10 秒时钟偏差；这是针对已实测约 3.5 秒的服务端/本机时间差，签名、issuer、audience、nonce 和时间校验仍保留。若仍提示 `not yet valid (iat)`，应检查系统自动校时；超过容差的凭证仍会被拒绝。浏览器的 “Authorization received” 只表示收到授权回调，最终是否登录成功以终端结果为准。

从 `auth models` 返回的该账号模型目录复制真实 slug，再编辑 `.env`：

```dotenv
# 仅替换主模型 Provider 与模型名，不在此存放 OAuth token。
TRIVAE_MODEL_PROVIDER=chatgpt-plan
TRIVAE_MODEL_NAME=<auth_models返回的模型slug>
```

订阅模式使用 OAuth Bearer 和官方 `https://api.openai.com/v1` Responses API。已有 `TRIVAE_MODEL_API_KEY`、`DEEPSEEK_API_KEY` 与传统 base URL 不参与此调用，不会自动换到 API key 计费。服务端请求固定 `store=false`、`stream=true`，不发送 `max_output_tokens`、`max_tokens` 或 `temperature`；本地 `MAX_TURNS`、`MAX_TOOL_ROUNDS` 与工具结果预算继续有效。

可选变量 `TRIVAE_CHATGPT_REASONING_EFFORT` 按当前代码登记的 Provider / 精确模型组合校验；不支持的值显式失败。不要根据模型名称自行推断可用档位；不配置时保留 Provider 默认行为。

### 多账号与 workspace

再次登录默认复用所选注册身份。添加另一个账号或 workspace：

```sh
uv run trivae auth login --provider chatgpt --new-account
uv run trivae auth status --provider chatgpt
```

按 `auth status` 返回的已签发 client ID 选择本机会话，再核对模型目录：

```sh
uv run trivae auth select --provider chatgpt --account '<已签发client_id>'
uv run trivae auth models --provider chatgpt
```

运行中的 Runtime 绑定首次选定的注册会话。切换账号或添加账号后，重新启动 Web / CLI，并核对该账号的模型 slug，确保目录和 OAuth 会话一致。配置 readiness 只检查本地授权与 scope，不保证网络、额度或实际模型调用成功。

### 额度、退出与切回 API key

在 ChatGPT 的 **Settings → Usage** 查看订阅用量与应用管理。额度由账号和订阅条件决定；不要把单次错误解释为整个订阅耗尽，也不要据此推测重置时间。共享会话与额度规则以[官方说明](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)为准。

额度限制、授权撤销、scope 不足、流中断或协议错误会明确失败，不自动切换到收费 API key 或其他 Provider。使用 `auth status` 与该次 Query 的 Trace 检查原因；Trace 保存实际 provider/model、用量、配置和安全错误原因，不保存 OAuth token。

```sh
uv run trivae auth logout --provider chatgpt
# 如需退出其他本机注册会话，显式选择它。
uv run trivae auth logout --provider chatgpt --account '<已签发client_id>'
```

退出会撤销 renewable session 并清除所选会话的本地 token，保留注册身份和主机标识，方便再次登录。远端撤销失败会报告错误，本地 token 仍会清除；随后可在 ChatGPT Settings → Usage 管理对应应用。切回 DeepSeek 时，恢复本文开头的四个 `TRIVAE_MODEL_*` 配置并重启。

## 独立 Router Jev

Jev 只服务于 Router 的模糊决策，不替代主模型、Planner 或 Runtime。主模型切换不改变 Jev 配置，OAuth token 不会发给 Jev。

```dotenv
# 与主模型分离的 OpenRouter 凭据；值为占位。
OPENROUTER_API_KEY=<你的OpenRouter_API_key>
# 历史变量按现有契约保留 TRIVIAE 拼写。
TRIVIAE_ROUTER_JEV_ENABLED=true
TRIVIAE_ROUTER_JEV_MODEL=typesafe/jev-1.13
TRIVIAE_ROUTER_JEV_ENDPOINT=https://openrouter.ai/api/alpha/decisions
TRIVIAE_ROUTER_JEV_MODE=shadow
```

| 模式 | 行为 |
| --- | --- |
| `existing_llm` | 模糊决策由现有主模型 Router 处理，不创建 Jev transport |
| `jev` | 模糊决策使用 Jev；失败保留静态路由并记录原因 |
| `shadow` | 同时观测现有 Router 与 Jev，真实路由由现有 Router 决定 |

高置信规则直接返回，不额外请求上述 Provider。默认 `enabled=true / mode=shadow`；Jev 缺 key 不阻止启动，真正调用时以 `JEV_ROUTER_API_KEY_MISSING` 记录失败。只使用主模型时，明确设置 `TRIVIAE_ROUTER_JEV_ENABLED=false`。启用 Jev 会增加独立的外部请求及可能的 OpenRouter 费用。

## 语义索引与升级

默认嵌入模型是本地 `sentence-transformers / Qwen/Qwen3-Embedding-0.6B`，1024 维、last-token pooling、normalized，并为 query 添加检索 instruction。模型惰性加载；查看身份或启动 Application 不会主动下载模型。默认 Runtime 仍暴露语义工具，不能把未安装 `semantic` extra 理解为关闭该工具。

```sh
uv sync --extra dev --extra semantic
uv run trivae semantic status --database data/trivae.sqlite3
uv run trivae semantic rebuild --database data/trivae.sqlite3
```

默认语义库位于 Canonical 旁边的 `data/trivae.semantic.sqlite3`，不可与 Canonical 数据库相同。需要独立路径时，对 status、rebuild、smoke 一致传入 `--semantic-index <索引文件路径>`；Web 默认使用 Canonical 旁的标准路径，没有独立索引路径参数。

新旧版本、正文 revision 或模型 / 分块身份不匹配会显式报告 stale，不自动绕过。升级后应重建全文和语义索引，全文重建的 Application 命令见[上手文档](getting-started.md#已通过普通-import-入库的数据库)，无需重新导出或导入源文件。

长构建中断且来源与索引身份均未变时，可显式续建已完整保存的块：

```sh
uv run trivae semantic rebuild --resume --database data/trivae.sqlite3
```

若原构建指定独立索引路径，续建也指定相同 `--semantic-index`。来源水位或版本变化会拒绝续建；已完成索引不重复续建。`rebuild` 默认是完整重建；自动导入的 updater 则会按当前状态选择首次构建、同快照续建或增量更新，详见[增量索引机制](semantic-incremental-index.md)。首次格式迁移仍有一次全量成本。

合并转发的内部正文递归进入独立检索投影，引用保留子消息、外层父消息、嵌套路径、内部发送者与导出位置。群聊与时间范围按外层转发进入当前群的时间过滤，来源面板另显示内部原始时间。`messages=[]` 表示内部正文未展开，明确报告缺失，预览不替代原文；普通群消息数量和 SQL 统计口径不因内部投影而增加。

## 故障定位与真实链路验证

| 现象 | 检查与处理 |
| --- | --- |
| `trivae` 入口不可用 | 在根目录运行 `uv sync --extra dev --extra semantic`，再执行 `uv run trivae --help` |
| Web 首页缺失，API 仍可用 | 检查服务端 `WEB_DIST_MISSING`，运行 `pnpm -C web build` 生成 `web/dist` |
| 修改 `.env` 未生效 | 检查当前工作目录、Shell 中同名变量的存在性并重启，不输出密钥正文 |
| 主模型配置缺失或非法 | 核对 `TRIVAE_MODEL_*`、Provider、模型名与端点；新变量空值不会借用旧变量 |
| FTS5 缺失 / stale | 使用上手文档中的 `rebuild_lexical_index()`，查看失败是否为 SQLite 无 FTS5 |
| 语义 missing / failed / stale | 查看 `semantic status` 的身份和操作建议，按条件完整 rebuild 或 resume |
| 模型加载失败 | 安装 `semantic` extra 并读取原始加载错误；仅在模型已缓存时使用 `HF_HUB_OFFLINE=1`，不换模型掩盖问题 |
| 自动导入 pending 或失败 | 用 `import-once --status` 查看文件、批次、索引错误，参考[调度日志与恢复说明](qce-auto-import.md) |
| OAuth 或 Query 失败 | 查看 `auth status`、Web 过程和该次 Trace，区分授权、Provider、检索、引用及持久化错误 |

读取 Trace，命令中的 ID 替换为当前 Query 返回的 trace ID：

```sh
uv run trivae trace show '<trace_id>' --database data/trivae.sqlite3
uv run trivae trace export '<trace_id>' --database data/trivae.sqlite3 \
  --output data/traces/query.txt
```

Trace / Evaluation 可能含问题、工具结果及聊天摘录，导出后仍属于本地数据，分享前先审查内容。

### 合并转发核验

以下群聊 ID、关键词均为占位；替换为有权使用的数据中的实际内容，输出目录必须尚不存在：

```sh
uv run python scripts/verify_forward_retrieval.py \
  --database data/trivae.sqlite3 --session-id '<session_id>' \
  --keyword '<数据中存在的关键词>' --run-agent \
  --output data/evaluation/forward-new-run
```

脚本核验 FTS5、真实 embedding、Agent 实际工具调用、子消息引用和 Canonical 来源回读；`--run-agent` 调用当前主模型。默认模式明确要求实际调用全文与语义检索；增加 `--agent-query-mode natural` 可检查不指定工具与转发类型的日常问法。

### ChatGPT 真实生产 Query 核验

本人完成授权、确认模型目录并设置 `.env` 后，再执行四类真实 Query：

```sh
uv run python scripts/verify_chatgpt_plan.py --database data/trivae.sqlite3 \
  --topic '<自己的数据中存在的主题>' \
  --output data/evaluation/chatgpt-plan/new-run
```

每次使用新目录，脚本覆盖事实检索、复杂工具分析、多轮追问与结构化引用，并保存结果与 Trace。Mock 测试通过不等于真实授权、token 自然过期刷新、模型调用均已验证。历史本机曾完成 OAuth、模型目录与四类有效 Query 验证；自然过期后的真实刷新当时未执行，刷新和轮换由 Mock 覆盖。该记录证明接入链路，不构成模型质量 Benchmark 或检索提升结论。

生产 Evaluation 使用相同 Runtime，实际配置从 `runtime.configuration` Trace 派生。切换 Provider 必须建立新 Variant 和结果目录，不改写历史 frozen Variant / Baseline，也不能把模型变化归因于检索改善。独立 retrieval annotator 与 claim judge 当前使用 Chat Completions，明确拒绝 `chatgpt-plan`；运行时显式选用 DeepSeek 或 OpenCode Go 的配置文件，不借用 OAuth、不自动改变计费。完整实验方法见[Evaluation 文档](evaluation.md)。
