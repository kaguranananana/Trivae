# 2026-10-22 · Plan Medium 后续可靠性实验

本轮四条 Development Query 均完成；其中 Archify 在真实模型调用中触发两个显式预算错误，SDK 四个工具调用全部获得响应，最终综合与 Citation 校验成功。另发现并修复 Collector 漏传 canonical ToolResult 限制标记的问题。此结论是协议与可追溯性验证，不是答案质量提升或 A/B 收益。

原始故障、预算修复与 OAuth/Medium 首轮验证见 [前轮报告](../runtime-budget-reliability-20261022/report.md)。本报告只补充用户授权继续后的实验与新增修复。

## 条件与请求计数

- 仅使用本机已有 OAuth 会话、ChatGPT Plan / gpt-6.1-sol / medium；每次实际 HTTP 发送前检查模型和 effort、预扣并 fsync，失败也计入。无自动重试、Judge、独立付费 Provider 或隐式切换。
- 旧轮次 4/4 账本保留。追加轮次最初 12 次 / 每 Case 4 次；用户再次授权后调整为 24 次 / 每 Case 8 次，调整时已有 9 次全部保留，并保存原账本与授权记录。实际追加 **12 次**，实验门禁阻断 **0 次**，与旧轮次累计 16 次。
- 四个 Case 本轮各运行一次；没有为更好结果补跑。Matt 使用原 10-18 的 473,236 条独立快照，其余使用 10-21 的 811,892 条快照。逐个核对 Case 的原 Snapshot 身份与现有完整索引，不重绑 GT、不重建索引、不读取 Holdout。
- 固定原 Prompt、七种生产工具、强制 Standard 路径，关闭独立 Jev shadow；不调用 Router/Planner 模型。生产预算仍为 16,000 Tool Result Token、3 工具轮、8 SDK turns。
- 前三条使用产品提交 `6b212b8`；实验脚本和门禁测试在请求前保存冻结副本。Archify 使用新增修复提交 `d4cf513`，单独冻结修复后清单，不覆盖原清单。
- 请求投影与 Provider 观测均确认 Medium，12 个响应均为 `response.completed`。输入 190,897 / 输出 3,345 / 合计 194,242 Token；Runtime、Trace、Evaluation 与逐响应之和一致。这是多次模型输入的累计 Usage，不能与单次查询的 16k Tool Result 池混淆。旧探针未知用量仍未知，不计作零。

## 真实结果

| Case | HTTP / 工具轮 / Tool Call | 投影 Token 总量 / 余额 | SDK 工具状态 | Query / Citation 绑定 | 检查结果 |
| --- | --- | --- | --- | --- | --- |
| Matt | 3 / 2 / 4 | 15,768 / 232 | ok ×4 | completed / 5 | 硬性均通过；限制保留诊断失败 |
| Miner | 3 / 2 / 2 | 11,866 / 4,134 | partial、ok | completed / 2 | 硬性均通过；限制保留诊断失败 |
| Written | 3 / 2 / 2 | 15,754 / 246 | partial ×2 | completed / 2 | 硬性均通过；限制保留诊断失败 |
| Archify（修复后） | 3 / 2 / 4 | 15,762 / 238 | ok ×2、预算 error ×2 | completed / 4 | 14 passed、1 not_applicable、0 failed |

四条均为两次工具响应轮加一次最终综合模型响应；综合没有被统计成第三工具轮。Matt、Written、Archify 的 finalizing 都明确为 `tool_result_tokens`。所有有效 Citation 保留，记录的 dropped_citation_count 均为 0。这里的 partial 是原 Capability 的覆盖事实，不是预算错误，也不是已证明检索为空。

Archify 的可核对调用链：

1. 第一轮 lexical 结果投影 14,628 Token；剩余 1,372。
2. 第二轮模型声明三个 context 调用；Runtime 在执行前为三个合法控制结果预留预算。
3. 第一个 context 执行并裁剪为 738 Token；后两个 SDK 响应分别为 198 Token 的 `TOOL_RESULT_BUDGET_EXHAUSTED`。
4. 实际 Capability 共执行三次（lexical 一次、context 两次）。其中第二个 context 已执行但无法产出合法数据投影，使用预留控制结果返回；最后一个 context 未执行。不能宣称消除了所有无用检索。
5. 最终 SDK 输入完整包含四个结果 `[ok, ok, error, error]`，没有悬空 Tool Call；累计 15,762，余额 238。
6. Runtime 与 Query 均 completed，保留四组 Citation 绑定、18 个通过验证的引用；预算错误未被泛化为 RUNTIME_ERROR，也未被当成空检索。

## 新增 Collector 修复与离线对照

前三条 Case 的最终 Artifact 均有 `coverage:partial` 和 `unexpanded_forward_content`，但 Collector 的 `runtime.tool.completed` 只传 payload/failure，遗漏了 canonical record.limitations。Evaluation 因而正确报告 Trace 丢失限制；不是答案丢失或 Evaluation 误报。

最小产品改动只有 `collector.py` 的一次 emit：把现成 `event.tool_result.limitations` 原样写入对应 Trace 事件。未修改检索、Prompt、Router、Planner、GT 或检查阈值。两个确定性测试覆盖正常结果与预算错误结果的限制传递。

保存 Matt 原始 SDK 输出序列、完整参数、最终答案与原快照，使用 ScriptedModel 做零 HTTP 重放。重放后全部检查通过，limitation_preservation 由 failed 变为 passed；规范 Evidence（排除新运行身份）、最终答案、Citation 绑定一致。各调用投影由 `[7919,2682,3267,1900]` 变为 `[7920,2682,3266,1900]`，差异来自实测 latency_ms 与其派生的 estimated_tokens/token_budget，总量均为 15,768。

首次离线比较的“投影逐项字节数/绑定直接相等”断言失败：耗时元数据会变化，且 asdict 的 tuple 与 JSON list 不能直接比较。保留该失败工件；随后按保存后的相同 JSON 表示比较稳定事实并逐路径核对变化，没有修改产品以迎合比较。原三份付费 Evaluation 保持原诊断失败，未回写为通过。

## 验证与运行状态

- 完整 pytest：**1,229 passed / 1 skipped / 0 failed**，30.38 秒。
- 相关定向测试：34 passed；Ruff `src tests scripts` 通过；mypy `src` 通过（129 文件）；git diff --check 通过。
- 新增三个请求账本测试：连接失败发送前已持久化计数、Case/总量门禁、拒绝 effort 漂移。新测试均不联网。
- 前轮预算准入、刚好耗尽、并行预留、SDK 包装归因、未知 Usage 和异常中断统计回归包含在完整测试中。四条真实响应均正常结束，**未自然复现流式坏 JSON**，不能把本轮当作真实异常流的复验。
- 本地 ignored 配置继续为 Plan / Sol / Medium，Jev shadow 关闭。已将本任务 Web 从旧进程 29549 重启到 31153，8710 readiness 返回 Plan / gpt-6.1-sol / ready，加载新 Collector；健康核对未调用推理。
- 本次前置普通推送仍受 GitHub 网络问题阻塞，最终推送结果见开发日志和交付说明。没有改全局网络配置、amend 或 force push。

## 边界与工件

本轮不是因实验配额用尽结束：24 次授权中实际使用 12 次，已取得真实预算退出、离线修复对照和完整回归证据。未扩大到 37 题或再做质量 A/B；少量 Case 不足以支持质量提升、统一五轮或扩大产品 16k 池。

预算不能保证任何情形都成功：若同轮全部合法控制结果也无法预留，仍必须显式失败；若最终证据不足，Finalizer 仍应拒绝无依据答案。可变元数据只有 Capability 返回后才完全已知，仍可能发生一次无法返回有效数据的检索。前轮原故障重放与本轮 Archify 均保留这些边界。

公开代码/门禁测试位于 `scripts/run_runtime_budget_followup.py`、`tests/test_runtime_budget_followup.py`、`tests/test_runtime_limitations_trace.py`。完整私有 Case、Trace、SDK 投影、冻结清单、原始失败、请求账本及调整、离线对照和汇总都在 ignored `data/evaluation/runtime-budget-followup-20261022/`，不提交正文、凭证或完整私有数据。
