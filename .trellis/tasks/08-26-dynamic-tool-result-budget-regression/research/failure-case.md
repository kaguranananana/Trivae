# Research: Failure Cases

## Harness failure（已修复，不计入 A/B）

第一次真实运行在首个 cell 完成后触发了 `RuntimeError`：异步 `_run_all()` 中调用了同步 `application.close()`，导致 event loop lifecycle 错误，随后 provider/app 没有按预期关闭。

根因是 harness 的关闭 API 与调用上下文不匹配，不是 Runtime budget 或 provider 返回的业务结果。修复为每个 mode 复用一个 Application，并在 `finally` 中 `await application.aclose()`；修复后重新完成 24 个 cell，未把第一次错误样本混入报告。

## 真实 provider/model failure（保留并单独归因）

| case / mode / repetition | Trace | failure | 是否预算耗尽 |
| --- | --- | --- | --- |
| GitHub/Skills fixed/1 | `trace-0045abb9ff0f42f3b78800461d4aef19` | `INVALID_MODEL_CANDIDATE`: claim sources exceeds 20 items | 否 |
| GitHub/Skills fixed/3 | `trace-e7455c0e25e1493cb4192c14baa7ff26` | `RUNTIME_ERROR`: agent runtime execution failed after the first Tool result | 否 |
| Agent learning dynamic/2 | `trace-2a8db4985fd848588589ad83d15cb65e` | `INVALID_MODEL_CANDIDATE`: limitations must be an array | 否 |

三条 failure 都没有产生 `TOOL_RESULT_BUDGET_EXHAUSTED` 或 `TOOL_RESULT_BUDGET_ERROR`；它们是现有模型输出契约/Runtime 行为问题，不能被错误标记为 dynamic budget regression。修复范围保持在记录和归因，不增加 retry 或静默修复。

## 质量评审边界

真实答案按上一轮 review dimensions 做人工抽样：retrieval recall、evidence coverage、citation validity、claim-evidence entailment、enumeration completeness、overclaim 和可读性。`citation unresolved=0` 只证明 current-run source handle 可解析，不证明 claim 与证据的完整蕴含。

- GitHub/Skills：dynamic 三次成功运行都保留了 URL 和分组，fixed 只有一条成功样本完整结束，且成功样本更偏代表性名称；这是与更大 projection headroom 一致的观察，但 provider/tool strategy 仍会影响结果，不能单独证明因果。
- Agent learning：fixed 三次成功；dynamic 两次成功、一次 finalization schema failure。两种模式的成功答案都能保留已知 Agent 入门 URL，dynamic 没有稳定质量优势。
- taste-skill：两种模式均三次成功，均区分“想测试”与“实际使用”，没有触发 `INTENT_TO_ACTUAL_USE` 或 `REVIEW_TO_PERSONAL_USAGE`。
- DeepSeek：两种模式均三次成功；该 case 的 per-call projection 本来就在 fixed 16k 边界内，适合作为不应被 dynamic 计功的 control。两种模式都保留主要项目，但没有证明完整实体枚举。
