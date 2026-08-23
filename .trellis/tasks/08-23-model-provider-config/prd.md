# Generalize Model Provider Configuration

## Problem

当前 Runtime 只接受 `DeepSeekSettings`，并把 API key/base URL 绑定在
`DEEPSEEK_*` 环境变量上。这样 OpenCode Go 虽然同样支持 OpenAI-compatible Chat
Completions，却不能只通过本地配置切换。

## Goal

把 Provider 配置收敛为通用的 OpenAI-compatible Model Provider 配置，使 DeepSeek
官方 API 与 OpenCode Go 共用同一套 OpenAI Agents SDK Runtime Adapter。业务层只接触
provider、model、base URL 和 runtime budgets；Provider 差异不进入 Router、Planner、
Tool、Retrieval、Citation、Trace 或 Evaluation 语义。

## Requirements

- 支持 `deepseek` 与 `opencode-go` 两个 provider。
- 读取 `TRIVAE_MODEL_PROVIDER`、`TRIVAE_MODEL_API_KEY`、`TRIVAE_MODEL_BASE_URL`、
  `TRIVAE_MODEL_NAME` 及既有 runtime budget 变量。
- 新变量优先；当 provider 为 `deepseek` 且对应新变量不存在时，按字段兼容读取
  `DEEPSEEK_API_KEY` 与 `DEEPSEEK_BASE_URL`。新旧变量同时存在时新变量胜出；新变量
  显式为空时必须报错，不能静默回退。
- OpenCode Go 使用模型 ID `deepseek-v4-flash` 和 base URL
  `https://opencode.ai/zen/go/v1`，不使用 `opencode-go/deepseek-v4-flash`。
- 保持现有 `AsyncOpenAI`、`OpenAIChatCompletionsModel`、OpenAI Agents SDK loop、
  tool seam、lifecycle 和 Application composition 不变。
- `repr(settings)`、safe dict、Runtime result/event、Trace、CLI debug 和异常不能
  包含 API key；测试只使用明显的 fake key。
- Usage projection 若 Provider 提供 cached input/cache read 字段则归一化；没有字段
  时保持 unknown，不以 `0` 伪造。
- `.env` 继续被 Git 忽略，不创建带真实 token 的 `.env.example`；当前仓库的 `.env`
  运行约定（启动前导出到进程环境）保持不变。

## Acceptance Criteria

- [x] `ModelSettings`（或同等通用名称）不再把 Runtime 类型绑定为 DeepSeek。
- [x] OpenCode Go 与 DeepSeek 官方配置、优先级、legacy fallback、非法 provider 和
  缺失字段均有 deterministic tests。
- [x] Runtime adapter 能从配置得到正确 base URL/model，并共用同一构造路径。
- [x] safe repr/dict 与已有 Trace/CLI projection 不泄漏 secret。
- [x] usage/cache 字段归一化有测试，缺失字段不补零。
- [x] 完整 `pytest`、`ruff`、`mypy` 通过。
- [x] 若本地有 OpenCode Go credential，完成 basic completion、tool calling、streaming、
  citation/finalization 和 Trace safe-field smoke；未验证项明确记录。

## Non-goals

- 不改 Retrieval、Citation、Planner、Tool、Evaluation 的业务语义。
- 不新增第二套 Agent loop、provider fallback、retry、structured-output repair 或
  业务层兼容分支。
- 不把真实 key 写入源码、测试、fixture、Trace、日志、任务文档或 Git history。
