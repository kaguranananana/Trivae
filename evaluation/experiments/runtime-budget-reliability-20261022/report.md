# Runtime Tool Result 预算可靠性修复（2026-10-22）

预算与 Collector 修复已通过本地回归；原私有失败可以确定性重放，修复后的 SDK 调用协议闭合并进入综合，Host Citation 校验通过。**后续已定位并修复 OAuth 时钟偏差问题，GPT-6.1 Sol Medium 通过真实工具协议验收，本地配置和 Web 服务已生效。** 这些结果不代表真实模型答案质量提升。

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
- 完整 `uv run pytest -q`：**1,224 passed、1 skipped、0 failed**。`uv run ruff check src tests scripts` 通过；`uv run mypy src` 通过（129 个源码文件）；`git diff --check` 通过。
- 额外 `ruff check .`：53 项既有错误，全部位于未改动的 `.trellis/` 脚本/归档；未把归档批量格式化混入本次修复。
- 极端低预算、模型一次声明过多调用导致控制结构无法准入、或独立模型/存储错误仍可使 Query 失败。证据不足仍由原 Finalizer 拒绝无依据答案；错误结果不能被判为完整空检索。

## OAuth 根因、Medium 核验与请求边界（08:43 后续完成）

初次目录核验被 `AUTH_OIDC: ID token validation failed: The token is not yet valid (iat)` 阻断。网页 “Authorization received” 只表示浏览器授权回调已收到；终端之后才交换并验证 ID Token，因此网页成功和终端拒绝可以同时发生。重复登录不能消除每次新凭证与本机的时间差。

后续对官方 discovery 的一次公开 GET 实测：本机 UTC `00:43:06.289`，官方 Date 为 `00:43:10`，往返约 0.411 秒，以请求中点估算服务端快 **3.462 秒**。未读取真实凭证正文。使用本地签名、固定时间的完整登录回归，`iat=now+3` 与 `now+10` 在修改前均复现同一 AUTH_OIDC（2 failed / 3 passed），确定零容差能造成该失败。

[chatgpt.py](../../../src/trivae/auth/chatgpt.py) 仅增加固定 10 秒的 PyJWT `leeway`，不关闭签名、issuer、audience、nonce 或时间校验，也不根据 HTTP Date 改系统时钟。`iat/nbf` 超过 10 秒、`exp` 超过容差的过期凭证继续失败且不落盘。5 项新增时间边界回归通过。[PyJWT 官方文档](https://pyjwt.readthedocs.io/en/stable/usage.html) 与 [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation) 允许小幅时钟偏差处理。

修复后既有 OAuth 会话、完整 CLI `uv run trivae auth models --provider chatgpt` 均成功。账号目录明确包含 `gpt-6.1-sol` 和 `supported_reasoning_levels[].effort=medium`。能力白名单仅新增该精确组合的 Medium；没有登记新的 GPT context 容量。Settings 与 HTTP Mock 新增参数化覆盖 Medium / High，证明 Runtime、Router completion、Planner completion 的实际请求体与安全投影同源，均显式传 `reasoning.effort=medium`，未知组合仍拒绝。

真实推理严格复用原四请求持久化账本，每个 HTTP request hook 在发送前写计数、实际 model/reasoning/store/stream 投影并 fsync；失败不回退计数，不自动重试。前两次预检在目录 GET 连接失败，推理为 0 次，均留失败工件。之后实际使用 **4 / 4**：

| 验证 | 推理 HTTP | 结果与证据边界 |
|---|---:|---|
| 极小 JSON completion 探针 | 1 | JSON 内容校验失败，保留失败，不重复。脚本未保存该失败的完整 response observation，因此该条 Usage 未知，不计为零，也不单凭它宣称验收成功 |
| 独立合成预算协议：seed 证据 → 不可裁剪结构 → 最终综合 | 3 | 真实 GPT-6.1 Sol Medium，3 次 response.completed；实际两工具轮，两个调用为 ok / 明确预算错误，工具投影 424 / 198 Token；无工具综合后 1 个 Citation binding 通过 Host 校验。成功用量为输入 15,647、输出 342、总 15,989（仅这三次，不含未知探针） |

四次实际 HTTP 投影均为 `reasoning={summary:auto,effort:medium}`。真实预算案例的消息/结构由本地 fixture 合成，不包含群聊内容，不冒充原私有 Case 重跑，也不据此声称答案质量改善。原私有 134 Token 故障的确定性重放仍见上表。

确认后，本地 ignored `.env` 已切换 `chatgpt-plan / gpt-6.1-sol / medium`；另将既有 `TRIVIAE_ROUTER_JEV_ENABLED=false`，避免本轮本地查询走独立 OpenRouter shadow（保留仓库既有变量拼写，不修改 Router 主体）。原无运行中 Web/Chat 进程，已按新配置启动本地 Web **127.0.0.1:8710**，`/api/readiness` 验证 provider=chatgpt-plan、model=gpt-6.1-sol、status=ready。未提交 `.env` 或复制 OAuth 凭证。真实 Runtime、预算退出及 Citation 已验证；Router/Planner 的共享参数由 Mock HTTP 验证，不宣称完成真实业务路由质量验收。

补充后完整回归 **1,224 passed / 1 skipped / 0 failed（27.52s）**；认证/订阅/共享参数/预算定向 **127 passed**；Ruff（src/tests/scripts）、mypy（129 文件）与 diff --check 通过。

维持 `max_tool_rounds=3`、`max_turns=8` 和 16k 未知 context 预算。请求上限已用满，不继续补跑；未重跑 10-21 实验、扩展 37 题、使用独立付费 Provider/Judge、触碰封存 Holdout/人工 GT 或重建语义索引。Context Expansion、reply 关系和 Conversation History 留待独立任务。

私有脚本、原始参数、完整结果/投影、时钟观测、模型能力摘要、请求账本、Web 启动/就绪记录与测试输出保留在 ignored `data/evaluation/runtime-budget-20261022/`。公开仓库只含合成测试与此脱敏报告。

## Git 交付状态

代码、测试、报告和状态记录已本地提交。按仓库约定执行 `git push`，但当前 SSH 配置的 `ssh.github.com:443` 无法解析；独立 HTTPS 检查 `github.com` 同样 DNS 解析超时（10 秒）。挂起推送已停止，**远端推送尚未完成**。未更改全局 DNS/SSH 配置或强制推送；待网络解析恢复后对当前分支执行普通 `git push`。任务开始前的两个未跟踪文件保持原样。
