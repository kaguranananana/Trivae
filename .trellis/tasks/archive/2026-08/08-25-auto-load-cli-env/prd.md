# Automatic CLI dotenv loading

## Goal

让用户从项目目录直接执行 `trivae chat`，无需先手动 `source .env`，即可使用项目配置的真实 Provider。

## Requirements

- `chat` 启动时默认读取当前工作目录下存在的 `.env` 文件。
- `chat --env-file PATH` 可以显式指定 dotenv 文件。
- 进程环境变量优先于 dotenv 文件中的同名变量；显式空值也必须继续交给配置校验并报错。
- dotenv 解析只处理文本赋值，不执行 shell 命令；空文件、注释和常见单/双引号值可用。
- 默认 `.env` 不存在时保持原有环境变量启动语义；显式指定的文件不存在或格式错误时显示可读错误并返回非零状态。
- `load_settings()` 和其他库入口不自动读取工作目录凭据，日志、Trace 和终端不打印密钥内容。
- 为自动加载、优先级、格式错误和 CLI 参数增加回归测试，并更新运行契约文档。

## Acceptance Criteria

- [x] 不执行 `source .env` 时，从项目根目录运行 `trivae chat` 能显示已配置 Provider 的 readiness。
- [x] shell 环境变量覆盖 `.env` 同名值，且 `load_settings(environ=...)` 行为不变。
- [x] 缺失/非法 dotenv 输入不被静默吞掉，CLI 返回 1 并给出不含密钥的诊断。
- [x] 现有 CLI、配置和全量测试通过。
- [x] 规格文档记录默认路径、显式路径、优先级和边界。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- This task changes a user-facing startup contract and crosses CLI/config/documentation boundaries, so design and implementation plans are recorded separately.
