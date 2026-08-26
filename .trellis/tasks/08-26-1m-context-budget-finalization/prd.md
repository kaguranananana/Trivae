# 1M Context Dynamic Budget + Graceful Finalization

## 目标

在当前分支继续完善 Trivae 的 Agent Runtime：让已验证的 `opencode-go / deepseek-v4-flash` 1M context 能力真正进入动态 Tool Result 预算决策；把单次 Tool Result 安全上限和一次 Run 的累计 Evidence pool 分成两个独立契约；同时修复模型输出局部 schema 不合法时整轮答案丢失的问题。

本任务必须保留 `TRIVAE_TOOL_RESULT_BUDGET_MODE=fixed` 作为回归、调试和评测基线，但默认模式切换为 dynamic。未知模型或未知 context 不猜测能力，而使用单次 16k、共享 Run pool 16k 的可观测安全边界。

## 产品需求

### 1. 动态预算

- context window 来源优先级固定为：显式 `TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS`、已验证模型能力注册表、fallback；Trace 中使用精确的 `explicit_config`、`verified_model_registry`、`fallback`。
- 已验证注册表至少包含 `opencode-go / deepseek-v4-flash → 1_000_000`，Runtime 不允许散落模型名称特判。
- 单次 Tool Result ceiling 与 Run-level Tool Evidence pool 使用不同参数、不同计算和不同 Trace 字段：
  - per-call：`min(floor(context * 50%), 128000)`；
  - run-level：独立的百分比、上限和可选显式实验值；默认候选为 `min(floor(context * 25%), 256000)`，1M context 解析为 250k，实验可精确覆盖 128k/256k。
- unknown dynamic context 的 per-call 和 shared pool 都为 16k；多次调用不得各自获得独立 16k。
- 每次调用必须记录 ceiling、effective budget、projection estimate、run pool 前后余额、omitted/truncated，并能区分固定基线和动态来源。

### 2. Graceful Finalization

- 最终化公开 `valid`、`degraded`、`failed` 三种状态。
- 对可恢复问题严格保持可信边界：保留可读答案，丢弃不安全的局部字段或 citation；`limitations` 为字符串时只在有界、确定性规则下规范化为单元素数组，并记录规范化事实。
- 单个 invalid citation 只丢弃该 citation；保留其他合法 citation。全部 citation 无法验证时仍可返回答案文本，但必须标记 degraded，且 Evaluation 不得把它计为 grounded/passed citation。
- 无可读文本、空答案、无法抽取用户答案、可信 provenance/scope/security 边界错误必须 failed；不得用 catch-all Exception、静默吞错、第二次 LLM repair 或伪造来源掩盖。
- 保存/Trace/Evaluation 只允许 bounded、secret-safe 的诊断：状态、稳定 error code/path、丢弃字段和 citation 数、规范化次数、validated citation 数、用户答案是否保留；不得保存 provider raw payload、hidden reasoning、secret 或无界 invalid body。

### 3. 回归审计与校准

- 对 Agent learning limitations schema、GitHub/Skills source 数量、GitHub/Skills runtime error、async-close/harness lifecycle、OpenCode Go tools/JSON、dynamic accounting、multi-tool cumulative pool、graceful finalization 完成 BUG / contract failure / provider nondeterminism / harness issue 分类审计。
- 合成基准覆盖 Agent/https 的 100、300、1000 命中规模，比较 fixed16k、dynamic128k、dynamic256k（可附 historical64k），记录总命中、canonical/visible messages、tokens、omitted/truncated、per-call/run effective budgets、latency 和可获得的 memory。
- 真实 provider 只改变预算变体：四个固定问题、fixed16k / dynamic per-call128k+run128k / dynamic per-call128k+run256k，各 3 次，共 36 次；记录完整 Trace ID 和每个 case 的完成、质量、成本/延迟/不稳定性。

## 非目标与约束

- 不创建新 Git 分支，不切换 `main`，不 merge/force-push。
- 不重做 Retrieval、Provider 通用适配或 Evidence provenance 模型；只扩展现有契约。
- 不为了旧字段增加无依据兼容别名；删除当前产品代码中的含义不清的 `max_tool_result_tokens` 配置/Trace 字段。归档任务文档作为历史事实保留。
- 所有新代码加入简体中文注释，预算和最终化关键逻辑逐行解释；错误必须显式、可追踪。

## 验收标准

- [x] 默认 settings 为 dynamic；fixed 开关可复现旧 16k 基线。
- [x] 1M registry、显式 context、未知 context 三种 source 均有单测和 Trace 断言。
- [x] per-call ceiling 与 run pool 在配置、policy、RuntimeToolCall、Trace、Evaluation 中字段独立；多 Tool 累计不超共享 pool。
- [x] graceful finalization 对合法、limitations 字符串、缺失 optional metadata、单个/全部 invalid citation、空答案、provenance 错误分别有回归测试。
- [x] degraded 答案可展示并提交 Conversation；failed 答案不提交；CLI 有明确 degraded 提示。
- [x] Evaluation 不把 degraded citation 当作 grounded success，且 snapshot/operational measurements 包含 finalization 和预算诊断。
- [x] 规格/ADR、PRD、design、implement、bug audit、benchmark 和 real A/B/C 报告已更新。
- [x] 实际运行并记录 `pytest -q`、`ruff check src tests`、`mypy src`、compileall、CLI help、Trellis validation、`git diff --check` 的结果。

验收说明：真实 A/B/C 已执行 36/36 个 cell 并保存 36 个 Trace ID；但 32 个 cell 超过 30 秒实验 harness timebox，只有 3 个 completed valid 和 1 个明确 Runtime failed，因此报告对答案质量、成本和稳定性保持“证据不足”结论，不把 timeout 当作产品成功或 graceful degradation。
