# 本地安装与使用

本文从一份 QQChatExporter 导出文件开始，完成安装、数据入库、索引构建与 Web 提问。所有命令在仓库根目录执行；模型与 OAuth 的高级选项见[配置说明](configuration.md)。

## 运行环境

| 依赖 | 要求与用途 |
| --- | --- |
| Python | 3.12+，由 `pyproject.toml` 声明 |
| uv | 安装 Python 依赖并运行 `trivae` CLI |
| Node.js | 建议 Node 22.12+（22 系列）或 24+；当前 Vite 7 / Vue 插件要求 `^20.19.0 \|\| >=22.12.0`，Vitest 4 的引擎范围不包含 Node 23 |
| pnpm | 安装和构建 `web/`；仓库未固定 pnpm 版本，安装时保持现有锁文件 |
| SQLite FTS5 | Python 所用 SQLite 必须支持 FTS5，构建全文索引时实际探测 |
| 模型访问 | 仓库默认查询 profile 使用 ChatGPT OAuth；也可切换到已登记的 API key profile。语义向量由本机 Qwen 模型生成 |

首次加载 `Qwen/Qwen3-Embedding-0.6B` 需要下载模型，预留本地磁盘、内存与构建时间。CPU / GPU 和数据量会影响耗时，本文不承诺固定的首次启动时间。

## 1. 安装与构建

```sh
# 安装开发工具和语义模型依赖，供后续完整检索链路使用。
uv sync --extra dev --extra semantic
# 按仓库锁文件安装前端依赖。
pnpm -C web install --frozen-lockfile
# 生成由 Python 服务托管的 web/dist。
pnpm -C web build
```

`semantic` 是可选依赖包，不是自动切换检索模式的开关。只运行 `uv sync --extra dev` 可以进行不加载模型的 CLI、数据导入和全文检索操作；默认 Runtime 仍注册 `semantic_search`，实际调用它需要语义依赖及就绪索引。缺失时会显式报错，不会自动改用全文检索。

## 2. 配置主模型

仅在没有 `.env` 时复制示例；已有文件直接编辑，保留原配置：

```sh
cp .env.example .env
```

仓库默认查询 profile `gpt-plus` 使用 ChatGPT OAuth。先登录并确认本机授权：

```sh
uv run trivae auth login --provider chatgpt
uv run trivae auth status --provider chatgpt
```

如使用 API key profile，则在 `.env` 中选择 `deepseek-flash` 并填写自己的 key（占位值）：

```dotenv
# 从 config/models.yaml 中选择已登记的 profile。
TRIVAE_MODEL_ID=deepseek-flash
DEEPSEEK_API_KEY=<你的DeepSeek_API_key>
```

Jev 是独立的可选 Router 实验。若只准备使用主模型，在 `.env` 中明确关闭它：

```dotenv
# 不调用独立 OpenRouter Jev；主模型 Router 与 Runtime 仍照常工作。
TRIVIAE_ROUTER_JEV_ENABLED=false
```

`.env.example` 默认保留 Jev `enabled=true / mode=shadow`，其凭据是独立的 `OPENROUTER_API_KEY`。只使用主模型时可在 `.env` 设置 `TRIVIAE_ROUTER_JEV_ENABLED=false`。profile 定义和覆盖顺序见[配置说明](configuration.md#配置加载与模型profile)；旧 `TRIVAE_MODEL_PROVIDER` / `TRIVAE_MODEL_NAME` 配置仍可覆盖 profile。Shell 已导出的同名变量优先于 `.env`，修改后重启进程。

本地优先指原始导出、数据库、索引和会话存于本机；模型分析仍会向配置的外部 Provider 发送问题、会话上下文和工具取得的相关内容。启用 Jev 还会向 OpenRouter 发送其路由上下文。请使用有权处理的数据；这不是全离线推理模式。

## 3. 导入数据并构建索引

当前导入器支持 **QQChatExporter JSON（V5 / 0.1.0 字段形态）**，包含 `metadata`、`chatInfo`、`messages`。它不是任意 JSON、其他聊天平台或图片 / 音频文件的通用导入器。媒体元素会保留来源结构，本流程不执行 OCR 或语音转写。

把导出完成的 `.json` 文件放入 `data/raw/`，与其他格式文件分开。普通 `import` 只扫描该目录第一层、小写 `.json` 后缀的文件。

```sh
# 创建数据目录，再将自己的已完成导出文件复制到此处。
mkdir -p data/raw
# 导入、确认文件稳定，并更新 FTS5 与本地语义索引。
uv run trivae import-once --raw-dir data/raw \
  --database data/trivae.sqlite3 --update-indexes
# 读取持久化的文件、批次及索引待办状态。
uv run trivae import-once --database data/trivae.sqlite3 --status
# 查看索引身份、来源版本与 readiness。
uv run trivae semantic status --database data/trivae.sqlite3
```

`import-once` 默认要求文件至少静默 60 秒，并间隔 5 秒采样确认稳定。刚导出的文件可能本次被推迟；待文件稳定后重跑同一命令即可。新增或变化的文件经过同一个导入器，已完成且未变化的文件不重复解析；索引工作持久化，失败后可继续处理。必须读取状态和错误，不能把进程启动、入库计数或 `completed` 单独当作检索已就绪。

首次 `--update-indexes` 会构建全文与语义索引，可能明显长于导入；后续语义更新会在满足版本与输入一致性条件时复用向量。机制和边界见[增量索引](semantic-incremental-index.md)。macOS 每天 10:30 / 22:30 的调度默认只准备，需显式启用，见[QCE 自动导入](qce-auto-import.md)。

### 已通过普通 import 入库的数据库

原有手工导入命令仍可使用：

```sh
uv run trivae import --raw-dir data/raw --database data/trivae.sqlite3
```

**普通 `import` 不自动构建 FTS5 或语义索引，也不创建自动导入的文件工作队列。** 此时不能用队列为空证明索引新鲜，需要显式构建；已有数据库升级后的重建同样适用：

```sh
uv run python - <<'PY'
from pathlib import Path
from trivae.bootstrap.application import create_application

# 通过 Application 装配，确保读写资源按上下文生命周期关闭。
with create_application(Path("data/trivae.sqlite3")) as application:
    # 重建全文和转发派生投影，保留 Canonical 消息与原始来源。
    print(application.rebuild_lexical_index())
PY
# 完整重建独立的本地语义索引；首次会加载嵌入模型。
uv run trivae semantic rebuild --database data/trivae.sqlite3
```

无需重新导出或重新导入 QQ 文件。中断续建、独立索引路径和版本失配处理见[配置说明](configuration.md#语义索引与升级)。

## 4. 在 Web UI 提问

```sh
uv run trivae web --database data/trivae.sqlite3 --host 127.0.0.1 --port 8710
```

浏览器默认自动打开 `http://127.0.0.1:8710`；加 `--no-open` 可手动打开。命令是 `web`，仓库没有 `webui` 子命令。

先选择来源范围，再输入问题。例如，在自己包含对应讨论的演示数据中提问：“这段时间大家讨论了哪些部署问题？请列出结论和原始依据。”等待回答完成后，点击引用复核原始消息与上下文；展开过程查看实际路由、计划和工具调用。多轮追问沿用当前会话，切换来源前确认提问范围。

需要终端界面时可执行：

```sh
uv run trivae chat --database data/trivae.sqlite3
# 使用纯文本流输出，便于终端记录与排障。
uv run trivae chat --database data/trivae.sqlite3 --plain --verbose
```

Web 服务目前面向本机使用，默认绑定回环地址。绑定其他地址会关闭 Finder 等本机集成能力，不代表已提供面向公网的用户认证或多租户部署方案。

## 5. 验证与排障入口

```sh
# 检查真实 CLI 入口；不调用外部模型。
uv run trivae --help
# 检查代码规范、类型与自动化测试。
uv run ruff check src tests
uv run mypy src
uv run pytest
# 检查前端类型、静态规则、测试与产物。
pnpm -C web typecheck
pnpm -C web lint
pnpm -C web test
pnpm -C web build
```

本地语义检索可单独核验，不调用主模型；把查询改成自己的数据中存在的内容：

```sh
uv run trivae semantic smoke --database data/trivae.sqlite3 --query "部署讨论"
```

Web 能打开、自动化测试通过、语义 smoke 命中，以及真实 Provider 返回带引用答案，是不同层次的验证。真实模型 Query 会产生对应 Provider 费用或消耗订阅额度。详细错误定位、合并转发和 OAuth 真实验证命令见[配置说明](configuration.md#故障定位与真实链路验证)；评测方法见[Evaluation 文档](evaluation.md)。
