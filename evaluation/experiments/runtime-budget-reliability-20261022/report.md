# Runtime Tool Result 预算可靠性修复（2026-10-22）

预算与 Collector 修复已通过本地回归；原私有失败可以确定性重放，修复后的 SDK 调用协议闭合并进入综合，Host Citation 校验通过。**GPT-6.1 Sol Medium 核验被现有 OAuth 会话阻塞，没有真实推理请求，也没有启用 Medium。** 这些结果不代表真实模型答案质量提升。

## 根因与改动

调用链为 Agent Tool Call → Runtime Adapter → 预算预留 → Capability → 模型投影 → SDK → Finalizer。

1. 原系统已有 `begin_call()`，但只拒绝零余额。原失败前三结果记账 8,546 + 2,615 + 4,705 = 15,866，16,000 共享池剩 134 时仍准入第四次 Capability；结果的不可省略结构无法容纳，抛出 `ToolResultProjectionError`。SDK 用 `UserError` 包装后，Runtime 泛化成 `RUNTIME_ERROR`。
2. 另外确认投影 `estimated_tokens` 原先在增加 metrics/meta 字段之前计算，漏计投影自身的开销。本次按完整 UTF-8 payload / 既有 ratio=3 收敛计算；仍是 Host 估算，不冒充 Provider Token。
3. 预算策略新增最小准入、受限预留及未发送投影的退款。Runtime 在模型声明本轮全部调用后，先在**原共享池内**为各调用预留合法预算错误结果，再分配数据预算。控制结果不另外扩池，也不绕开单次上限。整轮控制结果都放不下时，在任何 Capability 执行前明确失败。
4. 已有真实失败证明必要的预算退出仅处理 `ToolResultProjectionError` / `ToolResultBudgetExhausted`：返还失败数据投影预留，返回显式 `TOOL_RESULT_BUDGET_EXHAUSTED` 工具错误，记录根因类型及 Capability 是否执行。后续同轮调用不再检索，各自返回合法响应；整轮结束后清除工具，使用先前证据综合。其他异常原样失败。保留 canonical Evidence、Host Finalizer 和 Citation 契约。
5. 无法安全闭合的预算错误仍终止 Runtime；沿 SDK 异常链区分 `TOOL_RESULT_BUDGET_EXHAUSTED`、`TOOL_RESULT_PROJECTION_ERROR`、`TOOL_RESULT_BUDGET_ERROR`，保留包装异常类型和原始分类。没有无限重试或通用降级。

实现涉及 [budget.py](../../../src/trivae/query/runtime/budget.py)、[openai_tools.py](../../../src/trivae/query/runtime/openai_tools.py)、[openai_adapter.py](../../../src/trivae/query/runtime/openai_adapter.py)、[evidence.py](../../../src/trivae/query/evidence.py)、[contracts.py](../../../src/trivae/query/runtime/contracts.py)。未修改 `SYSTEM_PROMPT` 主体；动态终止提示和事件明确区分 Token 池耗尽与工具轮次耗尽。模型输入窗口、输出上限、Tool Result 池和工具轮次继续分别记账。

## 可复核对照

原重放使用 10-18 留存的独立 canonical 快照与原工具参数，SQLite 只读。模型输出由 SDK `ScriptedModel` 重放，**不是重新让模型回答，也不是用合成消息冒充真实 Trace**。修改前结果已先行保存在本轮 ignored 目录；历史原件未覆盖。

| 输入条件 | 预算状态 | 工具执行 | 实际投影 | Runtime 终态 | Evidence / Citation | 错误分类 |
|---|---|---|---|---|---|---|
| 原私有参数，修改前 | 16,000 池，完成 3 结果后剩 134 | 第四次 Capability 仍执行 | 第四结果最小结构装不下 | SDK UserError；历史 Runtime 失败 | 前三结果存在，整次查询未交付 | 内层 ProjectionError 被泛化 RUNTIME_ERROR |
| 同一私有快照/参数，修改后完整 Runtime | 同为 16,000；完整投影记账合计 15,758，最终剩 242 | 原 4 次 Capability 均执行 | 8,614 / 2,682 / 4,264 / 198；前三合法结果、最后明确预算错误；中间结果按既有规则裁剪 | completed，2 工具轮后转无工具综合；共 3 次本地 SDK 模型调用 | 先前来源保留，测试候选 1 个 Citation binding 通过 Host 校验 | 预算错误返给 Agent，meta 保留 ToolResultProjectionError |
| 严格对应 15,866 已消费、134 剩余的合成账本边界 | 不足控制结构 | Capability 执行 0 次 | 无非法结果 | 调用前显式拒绝 | 既有证据不被删除 | TOOL_RESULT_BUDGET_EXHAUSTED |
| 合成同轮三调用：有效证据 → 不可裁剪元数据 → 后续调用 | 3,000 总池，预留覆盖各调用控制结果 | 前两次执行，第三次跳过 | 一份证据、两份预算错误；3 Tool Call 均有返回 | completed，1 工具轮后综合 | 原来源 Citation 通过；预算错误附为限制 | 第二次根因 ProjectionError，第三次 BudgetExhausted |
| 合成整轮控制结果也放不下 | 300 总池，三调用 | 执行 0 次 | 不向下轮发送不完整 Tool Call 对话 | failed，无下一次模型调用 | 不制造证据或零结果结论 | TOOL_RESULT_BUDGET_EXHAUSTED |

第二行第四次检索仍执行，不能宣称消灭所有无用检索：是否包含额外、不可裁剪元数据，需要拿到 Capability 返回才能确定。修复保证这类已知投影失败在控制预留足够时不会丢掉此前整次运行。完整原始失败之后的真实模型综合质量没有重新验证。

## Collector 与 Usage

[collector.py](../../../src/trivae/observability/collector.py) 仅依据实际完成工具调用的轮号及 Runtime 终态计工具轮，不把下一模型事件或最终综合编号算作额外工具轮。同轮多个调用只计一轮。

[usage.py](../../../src/trivae/query/runtime/usage.py) 汇总已观察响应：完整字段保留总量；有缺失时使用 `known_input_tokens` / `known_output_tokens` / `known_total_tokens` 等表示已知下界，缺失字段不填零；整份响应 Usage 缺失时记录 `responses_without_usage`，全未知仍为 `None`。在途响应同样保留未知，工具准入失败前已完成模型响应的用量不丢失。

[projection.py](../../../src/trivae/observability/projection.py) 使用新 Trace 的 Runtime 终态累计快照替换逐响应统计，避免重复相加；保留旧 Trace 原有字段读取。失败终态、Trace metrics 和 Evaluation 的 Usage/轮次一致。历史工件没有回写或补造未知用量。

## 验证与限制

- 新增 [test_runtime_budget_reliability.py](../../../tests/test_runtime_budget_reliability.py)：16 项通过，覆盖正常结束、中断、同轮多调用、部分 Usage 缺失、终态 observer 异常、最小准入、刚好用尽、并行预留/退款、不可裁剪结构、SDK 包装归因、控制结果、跳过能力、无依据 no_result 被拒绝、Citation 与 Trace/Evaluation 一致。
- 原有 [test_tool_result_budget.py](../../../tests/test_tool_result_budget.py) 的预算上限/余额预期按新增控制预留契约调整；未削弱累计实际消费断言。原有投影裁剪与模型可见来源一致性测试继续通过。
- 完整 `uv run pytest -q`：**1,217 passed、1 skipped、0 failed**。`uv run ruff check src tests scripts` 通过；`uv run mypy src` 通过（129 个源码文件）；`git diff --check` 通过。
- 额外 `ruff check .`：53 项既有错误，全部位于未改动的 `.trellis/` 脚本/归档；未把归档批量格式化混入本次修复。
- 极端低预算、模型一次声明过多调用导致控制结构无法准入、或独立模型/存储错误仍可使 Query 失败。证据不足仍由原 Finalizer 拒绝无依据答案；错误结果不能被判为完整空检索。

## Medium 核验与请求边界

通过生产 `ChatGPTAuthManager.list_models()` 使用既有 OAuth 会话核验账号目录，在认证层遭遇：`AUTH_OIDC: ID token validation failed: The token is not yet valid (iat)`。没有绕过 OIDC、读取/复制/输出凭证，不能由此断言服务端不支持 Medium。

因此尚未完成账号目录确认、Medium 最小真实请求、`reasoning.effort=medium` 实际 HTTP 投影及真实 Runtime/Router/Planner 验证。按用户要求“验证成功后扩展”，**未修改能力白名单、Settings 或本地 `.env`，未用 High 代替，也未重启成一个未经确认的配置**。现有本地运行配置仍为原 DeepSeek 配置；本轮没有调用它，未发现运行中的 Trivae Web/Chat 进程。

本轮推理 HTTP 为 **0 / 4**。ignored `http-ledger.json` 已保存上限、零计数和阻塞原因；没有自动重试，也没有绕过生产认证另外发送请求。后续先恢复有效 OAuth/时间声明校验，再以本轮持久化账本计数执行最多四次 Plan 推理；之后才能扩展 Medium 校验、补配置测试、切换本地配置并重启验证。

维持 `max_tool_rounds=3`、`max_turns=8` 和 16k 未知 context 预算。未重新运行 10-21 实验、未扩展 37 题、未使用独立付费 Provider/Judge、未触碰封存 Holdout、人工 GT 或语义索引。Context Expansion、reply 关系和 Conversation History 继续留待独立任务，不据本轮协议成功宣称答案质量收益。

私有脚本、原始参数、完整结果/投影、认证阻塞、请求账本、测试输出保留在 ignored 的 `data/evaluation/runtime-budget-20261022/`。公开仓库只含合成测试与此脱敏报告。
