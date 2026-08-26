# Implementation Plan

## 1. 任务启动与基线

- 在当前分支检查 `git status`、HEAD、既有动态预算提交和归档验证事实。
- 使用本 PRD/design 启动 Trellis 任务；不创建或切换 Git 分支。
- 先执行一次当前测试/静态检查，记录基线失败与既有 expected contract。

## 2. 预算实现

- 重命名/拆分 limits、settings、budget config 和 snapshot 字段，删除当前产品代码中的 `max_tool_result_tokens` 语义。
- 增加 verified model capability registry 和 resolver，并在 OpenAI-compatible adapter 唯一入口注入 resolution source。
- 更新 Tool adapter、TraceCollector、Evaluation measurements 和所有调用测试。
- 覆盖 fixed、1M registry、explicit、unknown fallback、128k/256k run override、多 Tool 累计和并发 reservation。

## 3. Graceful finalization 实现

- 在 Evidence 层增加 typed diagnostics/result 以及 bounded deterministic recovery helper。
- 保留 strict `finalize_answer` 作为内部 contract；Orchestrator 改调用 graceful wrapper。
- 贯通 QueryResult、Application commit、Trace event、stream adapter、CLI、Evaluation。
- 只对证明可恢复的局部错误降级；trusted scope/provenance、空答案和不可读结果显式失败。

## 4. 规格与回归

- 更新 Agent Runtime、Evidence/Citation、Trace/Evaluation 的 spec/ADR amendment。
- 更新现有 tests，新增 graceful finalization、registry、Trace/Evaluation/CLI 集成测试。
- 添加 bug audit 表、synthetic benchmark 和 real A/B/C runner；所有 provider run 显式 `await application.aclose()`。

## 5. 验证与交付

- 运行 pytest、Ruff、Mypy、compileall、CLI help、Trellis validation、git diff check。
- 复核 source precedence、budget 字段命名、secret-safe diagnostics、Conversation commit boundary。
- 记录合成与真实实验的配置、Trace IDs、异常分类、结论和最终推荐；提交清晰的小步 commit 并完成 Trellis task。
