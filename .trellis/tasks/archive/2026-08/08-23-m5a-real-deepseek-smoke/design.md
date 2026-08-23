# Design: M5a real DeepSeek smoke stabilization

## Existing boundary

M5a 已有的 `AnswerArtifact`、current-run `ToolResultRecord`、Citation Finalizer、trusted MessageSource hydration 和 explicit finalization failure 保持不变。真实 smoke 只验证 provider 能否正确使用既有 contract，不降低 contract 以适配模型。

## Failure-first investigation

1. 在真实 canonical 数据上准备可重建的 FTS derived index。
2. 使用 M5A-S1 跑完整 Application `query()`，只保存 secret-safe run summary。
3. 分别观察 Router、Runtime termination、ToolResult provenance、最终输出形状和 finalizer 错误。
4. 若最终输出不是 JSON，先检查本地 OpenAI Agents SDK / `OpenAIChatCompletionsModel` 的 response-format 能力与 DeepSeek OpenAI-compatible API 支持，再选择最小 adapter/prompt 修复。

## Candidate fixes

- 优先使用 provider/API 原生 JSON 或 structured-output 能力，并验证它确实到达 DeepSeek 请求边界。
- 若 provider 已返回 JSON 但附带 markdown fence 或有限外层说明，只增加 bounded、确定性的格式解析，不改变 Citation/source 语义；该分支必须由真实 Failure Case 驱动并有测试。
- 不用自动重试、裸文本转成功 Artifact、自动补 citation 或“最相似来源”替换掩盖失败。

## Smoke harness

Harness 复用生产 `create_application()` / `TrivaeApplication.query()` 和真实 SQLite 数据；只负责显式选择 case、派生 `ExecutionScope`、调用 provider、输出无 secret 的 run summary。它不复制 Runtime loop，也不构造伪造 Answer Artifact。

## Success evidence

S1 的成功证据必须同时来自真实运行对象：`RuntimeResult`、`ToolResultRecord`、解析后的 `AnswerArtifact`、hydrated `MessageSource.snapshot` 和 `QueryResult.is_successful`。历史 deterministic fixture 或先前 smoke 结果不能代替本次 provider 结果。
