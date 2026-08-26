# Technical Design

## 设计结论

本轮沿用 `Settings → OpenAIAgentsRuntimeAdapter → RuntimeContext/Tool adapter → Trace/Evaluation` 和 `RuntimeResult → QueryOrchestrator → Application/Conversation/CLI` 两条现有主链路，只把边界契约显式化。

```text
ModelSettings
  └─ ContextWindowResolver(explicit → verified registry → fallback)
       └─ ToolResultBudgetConfig
            ├─ per_call_tool_result_ceiling
            └─ run_tool_evidence_budget
                 └─ shared ToolResultBudgetPolicy
                      └─ each RuntimeToolCall + Trace snapshot

Runtime final output
  └─ strict finalizer
       ├─ valid AnswerArtifact
       └─ typed graceful finalizer
            ├─ bounded normalized AnswerArtifact (degraded)
            └─ FinalizationResult.failed (no artifact)
                 └─ QueryResult → commit/CLI/Trace/Evaluation
```

## 预算契约

### 配置与解析

- `config/limits.py` 只保存 per-call 与 run-level 的独立默认值。
- `config/model_capabilities.py` 提供 `VerifiedModelMetadata`、`ModelCapabilityRegistry` 和 `ContextWindowResolution`。注册表只返回人工/实验验证过的能力，不做 model string 猜测。
- `config/settings.py` 提供以下 typed 参数：`tool_result_budget_mode`、`model_context_window_tokens`、`per_call_tool_result_percent`、`per_call_tool_result_cap`、`run_tool_evidence_percent`、`run_tool_evidence_cap`、`run_tool_evidence_budget`。环境变量同名映射为 `TRIVAE_PER_CALL_TOOL_RESULT_PERCENT`、`TRIVAE_PER_CALL_TOOL_RESULT_CAP`、`TRIVAE_RUN_TOOL_EVIDENCE_PERCENT`、`TRIVAE_RUN_TOOL_EVIDENCE_CAP`、`TRIVAE_RUN_TOOL_EVIDENCE_BUDGET`。
- Adapter 构造时调用 resolver；显式 context 优先于注册表，注册表优先于 fallback。固定模式仍不消费 context，但其 snapshot 的 source 为 `not_used`。

### 计算与记账

`ToolResultBudgetConfig` 的 resolved 值：

- fixed：run pool 为 `None`，每次调用 16k；
- dynamic + known context：`per_call = min(context * per_call_percent // 100, per_call_cap)`；run pool 优先使用显式实验 budget，否则 `min(context * run_percent // 100, run_cap)`；
- dynamic + unknown context：per-call 和 run pool 都为 16k，resolution 为 `dynamic_fallback`。

`ToolResultBudgetPolicy.begin_call()` 先从共享余额预留本次 effective ceiling；`complete_call()` 依据实际 projection token estimate 退还未使用 reservation，并生成不可变 snapshot。预留/结算异常继续显式抛出，不伪造 Tool Result。

Snapshot 只使用语义明确的字段：`per_call_tool_result_percent`、`per_call_tool_result_cap`、`per_call_tool_result_ceiling`、`effective_per_call_tool_result_budget`、`projected_tool_result_tokens`、`run_tool_evidence_budget`、`remaining_run_tool_evidence_budget_before_call`、`remaining_run_tool_evidence_budget_after_call`。

## Graceful Finalization

### 类型

`query/evidence.py` 新增：

- `FinalizationStatus = Literal["valid", "degraded", "failed"]`；
- `FinalizationDiagnostics`：状态、用户答案保留、稳定错误码/path、degradation codes、丢弃字段/citation 数、规范化次数、validated citation 数；
- `FinalizationResult`：`artifact | None`、diagnostics、fatal `FinalizationErrorInfo | None`。

现有 `finalize_answer()` 和 strict contract 保持确定性、可单独测试；新增 `finalize_answer_gracefully()` 只捕获已知的 `AnswerFinalizationError`，按错误位置和可信边界分类。它不捕获未知 Exception，不调用模型，不重写可信 source。

局部恢复步骤：

1. 先运行 strict finalizer；成功直接返回 `valid`。
2. strict failure 若属于可恢复的模型候选/schema/citation 局部错误，解析 bounded JSON/plain text；核心 answer text 不存在则 `failed`。
3. `limitations` 字符串按确定性规则转成单元素 tuple，并增加 normalization 计数；超界或类型不可解释则丢弃该字段并记录。
4. 逐个构造 claim/evidence/source；单个 source 解析/handle hydrate 失败则丢弃该 source；scope、可信 provenance 或 canonical metadata 破坏则 `failed`。
5. 过滤没有有效 source 的 citation binding；若答案仍可读，返回无 fake citation 的 `degraded` artifact。

诊断只保存计数和固定 code/path，不保存 raw output。`AnswerArtifact` 仍是 Conversation commit 的唯一事实载体；degraded artifact 可以提交，failed 没有 artifact。

## 跨层传播

- `QueryResult` 增加 `finalization_status`、`finalization_diagnostics`、`execution_status`/`is_degraded`；`is_successful` 表示 runtime completed 且有可提交 artifact，valid/degraded 均可提交。
- `QueryOrchestrator` 使用 graceful finalizer；Trace 的 evidence/citation/finalization completed event 用 `outcome="partial"` 表示 degraded，并附 bounded diagnostics；fatal 仍发 failed。
- `Application` 对 degraded artifact 执行正常 commit，并把 `query.completed` payload 标为 `finalization_status=degraded`；failed 继续 query.failed。
- `QueryStreamAdapter` 和 CLI 从同一 normalized metadata 读取状态，CLI 在答案后展示有限验证提示；不在 renderer 中重新解释 raw payload。
- `evaluation/checks.py` 将 finalization state/citation state 区分为 `completed/degraded/failed`，degraded 不作为 citation grounded pass；snapshot 和 operational measurements 同步记录诊断与预算字段。

## 验证策略

- 单元：公式、source precedence、registry、unknown shared pool、reservation/settlement、finalization classification。
- 集成：ScriptedModel 运行 legal/degraded/fatal 三条 Query/Application/Conversation/Trace/CLI 链路。
- 回归：保留 strict parser/validator 的失败契约测试，新增 graceful behavior 测试；修正旧测试对“所有 finalization failure 都不提交”的过宽假设。
- 校准：任务目录中的 synthetic benchmark 和 real A/B/C runner 都记录具体配置、commit、Trace ID、provider/model、lifecycle close 和完整指标。
