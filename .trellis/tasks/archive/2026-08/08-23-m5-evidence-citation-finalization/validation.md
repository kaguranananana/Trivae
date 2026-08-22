# M5a Validation / Failure Attribution

## 1. Validation scope

本任务验证的是：

```text
search_messages Tool Result
→ current-run provenance
→ Agent final synthesis
→ Answer Artifact
→ Citation validation / trusted hydration
→ QueryResult.answer_artifact 或 explicit finalization_error
```

Conversation / Assistant Message durable commit 未在 M5a 实现，当前以 `QueryResult.answer_artifact` 作为可验证的提交前边界；M5b 必须只提交已通过该边界的 Artifact。

## 2. Deterministic evidence

### Measured facts

- `PYTHONPATH=src .venv/bin/pytest -q`：`113 passed`。
- `PYTHONPATH=src .venv/bin/ruff check src tests`：`All checks passed!`。
- `PYTHONPATH=src .venv/bin/mypy src`：`Success: no issues found in 38 source files`。
- `tests/test_evidence.py` 覆盖 Answer Artifact、claim binding、duplicate/dangling ID、relation/sufficiency、bounded text/value、malformed structured arrays、current-run provenance、old run、fabricated locator、scope violation、trusted message hydration、structured locator/value、Tool completeness 与 Evidence sufficiency 双轴。
- SQLite integration test 实际覆盖 `import → lexical index → search_messages → ToolResultRecord → structured final synthesis → MessageSource hydration → validated QueryResult`。

### Regression cases

| 分类 | 场景 | 期望行为 | 保护位置 |
| --- | --- | --- | --- |
| regression test case | Answer 引用不存在的 evidence ID | AnswerContractError | `tests/test_evidence.py` |
| regression test case | fabricated run/tool/result/item/message ID | AnswerFinalizationError，稳定 code | `tests/test_evidence.py` |
| regression test case | source 超出 trusted ExecutionScope | `SCOPE_VIOLATION` | `tests/test_evidence.py` |
| regression test case | 模型伪造 author/session/time/excerpt | 可信 projection 覆盖模型 metadata | `tests/test_evidence.py` |
| regression test case | structured locator 不存在或 value 不一致 | explicit unresolved/mismatch failure | `tests/test_evidence.py` |
| regression test case | Tool `partial` 与 Evidence `sufficient` 同时出现 | 两个维度分别保留 | `tests/test_evidence.py` |
| regression test case | Runtime failed/max-turn/aborted | 不进入 finalizer，不产生 successful Artifact | `query/orchestrator.py` 与 M4 runtime tests |
| regression test case | Tool execution 后返回裸文本 | `INVALID_ANSWER_ARTIFACT`，不丢 citation contract | `tests/test_evidence.py` |

这些是 deterministic regression cases，不宣称都是线上真实发生过的 Failure Case。

## 3. Failure attribution

- `INVALID_ANSWER_ARTIFACT`：final synthesis parser / Answer contract；不属于 Retrieval miss。
- `INVALID_PROVENANCE`、`UNRESOLVED_MESSAGE_SOURCE`、`MESSAGE_SOURCE_MISMATCH`、`UNRESOLVED_STRUCTURED_SOURCE`、`STRUCTURED_VALUE_MISMATCH`：Citation finalizer；不自动换 source。
- `SCOPE_VIOLATION`：trusted scope / finalizer boundary；不通过缩小或扩大模型参数静默修复。
- `TRUSTED_METADATA_UNAVAILABLE`：canonical projection 缺少人工复核所需字段；不采用模型 metadata 作为替代。
- `RUNTIME_ERROR` / `MAX_TURNS_EXCEEDED` / `RUN_ABORTED`：Agent Runtime；不伪装成 Evidence partial 或 successful answer。

## 4. Design rationale and deferred work

- 选择结构化 JSON + deterministic finalizer，而不是 `[1]` 文本 convention：只有结构化 identity 才能在渲染、持久化和验证之间保持 claim binding。
- 选择 current-run ToolResultRecord，而不是复用 prior assistant context 或 raw SDK item：避免旧答案成为当前事实来源，也避免 provider 类型泄漏。
- 不实现 Evidence Agent / Judge / `retrieve_evidence` Tool：Stage 1.8 已确认 Retrieval Candidate 与 Final Evidence 分层；semantic entailment 留给 M7 Evaluation。
- 不实现自动 repair/retry/fallback：invalid citation 的来源语义不能由系统猜测；真实运行若证明格式性 failure 高频且可安全恢复，再按 Stage 1.8 Reopen Conditions 重新设计。
- M5b：Conversation / Assistant Message persistence、历史 Evidence replay 和 fresh follow-up enforcement。
- M6：Trace backend；M7：Evaluation runner、semantic quality、citation precision/recall、bounds calibration。

## 5. Live DeepSeek smoke

状态：已执行独立 opt-in smoke；不会把 secret 写入 task、日志或 fixture。

### Measured smoke result

- provider/model：`deepseek / deepseek-v4-flash`
- termination：`completed`
- tool count / rounds / result count：`4 / 2 / 4`
- evidence / citation count：`0 / 0`
- validator：`failed`
- finalization error：`INVALID_ANSWER_ARTIFACT`，path 为 `null`；诊断信息是最终回答在工具执行后不是 JSON object
- usage：`requests=3`、`input_tokens=3742`、`output_tokens=372`、`total_tokens=4114`
- elapsed：`12409.1 ms`（临时数据库与本次 smoke）

### Failure attribution

第二次不打印正文的诊断确认：模型最终输出形状为 plain text，未满足 prompt 要求的单一 JSON object；不是 fabricated locator 被 validator 接受，也不是 source 被静默删除。Runtime 已正常完成，Orchestrator 按 contract 阻止成功 Artifact。这是当前 provider/model 的结构化 final-synthesis composition failure（或 prompt/structured-output compatibility issue），不是把它改成 fallback 的理由；若要恢复，应通过 provider structured-output 能力或后续 Evaluation 证明的 Prompt/adapter 改进重新设计，并继续保留显式 finalization failure。

以上字段已记录；不保存完整模型回答、聊天正文或任何 secret。
