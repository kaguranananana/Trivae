# GPT-6.1 Sol High Prompt 精简与消融实验报告

日期：2026-10-18（Asia/Shanghai）。本轮结论：**不推荐发布精简 Prompt，未替换生产 SYSTEM_PROMPT。实验在首条 Baseline 遇到 Provider SSE 协议不兼容后按停止条件收口。** 已完成工程适配、真实发送、失败定位与回归；质量 Baseline、B/C 对照和最终发布门禁未完成。

## 1. GPT High 配置与验证

初始 main：`5757327`。真实执行代码：`d093512`。Provider `chatgpt-plan`；账号实际目录包含 `gpt-6.1-sol`。SDK 固定 `openai-agents==0.22.0`，实际 `openai==3.5.0`、`httpx==0.28.1`、`httpx2==2.12.0`；无依赖升级。

- `settings.py`：新增 `TRIVAE_CHATGPT_REASONING_EFFORT=high` / `ModelSettings.chatgpt_reasoning_effort`。未配置时保留历史 Provider 默认；本轮只通过进程环境显式设置，没有修改用户 `.env`、OAuth 凭据或 Jev 配置。
- `model_capabilities.py`：精确允许 `chatgpt-plan / gpt-6.1-sol / high`；未知组合或其它档位显式失败。未登记未经验证的 GPT context 容量。
- `chatgpt_responses.py`：实际 payload 与安全 projection 同源，发送 `reasoning={"effort":"high","summary":"auto"}`。保留 store=false、stream=true、完整本地 replay、原工具 namespace 和严格 SSE 终态。
- `openai_adapter.py`：Runtime 构建同一个 Responses Model；GPT Router 和 Planner completion 都调用该 Model。Mock HTTP 三条路径已验证实际序列化 High；真实 smoke 固定 Standard，没有实际调用 Router/Planner，因此不能宣称两条路径已完成真实服务回归。
- `prompt_screening.py` / `run_prompt_screening.py`：GPT 的 `_provider_client=None` 根因已修复，在真实 httpx request hook 安装既有 ProviderCallBudget，覆盖多轮与失败 attempt，超额前阻断。总 ledger 固定120、单轮16；传统 Provider hook 保留。私有 reasoning replay 不进入 artifact；公开 effort/summary 保留。
- 冻结条件包含实际 Provider request projection；收尾进一步纳入 semantic index 身份/状态，失败 Baseline 禁止复用。未改旧 frozen artifact。

**验证边界：High 已在真实 HTTP body 发出，HTTP 200 和 SSE 已返回；但没有验证到 response.completed，所以完整服务接受/完成仍未通过。不能用 HTTP 200 宣布接入成功。** 本轮未进行 Medium、Low 或其它主模型实验。

## 2. 完整生产 Prompt 的 Baseline

本轮身份 `gpt-high-ablation-20261018`，独立总预算120，未继承/清零历史80预算。入口仍为 `TrivaeApplication.query()`，forced `standard_execution`，全部7个既有工具、3个 tool rounds、8个 turns，当前完整生产 Prompt 20450 字符；实际首请求 instructions 20643 字符（含生产动态预算后缀）。

使用历史固定 canonical snapshot：473236 messages，lexical 473236；当前四个 Case 的 canonical snapshot 预检均通过。未使用 unavailable seed 或封存 Holdout。

| Case identity | 场景 | 实际执行 | HTTP | 结果 |
|---|---|---:|---:|---|
| dev-lexical-chatlog-alpha@v2 | 精确事实与已人工裁决引用 | 是 | 1 | MALFORMED_STREAM，失败，无答案 |
| dev-para-ts-learning@v1 | 语义/学习路径查找 | 否 | 0 | 前条工程失败后阻止后续请求 |
| dev-context-mattpocock-1@v2 | 推荐、使用与后续反馈 | 否 | 0 | 未运行 |
| dev-zero-empty-1@v2 | UTC 空窗口与强否定边界 | 否 | 0 | 未运行 |

计划4条 smoke，实际尝试1条、成功0条、失败1条，另外3条未运行；没有扩展至约16条。没有形成有效 GPT 质量 Baseline，不能计算准确率或召回改善。

唯一真实 Query：端到端 **9534 ms**、模型 HTTP **1**、工具调用/轮次 **0/0**、Finalizer **skipped**、Token/费用 **unknown**（Provider 未返回可用终态 Usage，不能写0）。

## 3. 根因与停止证据

首个请求携带 High，服务返回 HTTP 200；读取到第29个非空 SSE 行时，事件 `response.metadata` 被 SDK typed union 拒绝：`union_tag_invalid`，上抛 `MALFORMED_STREAM`。没有 response.completed、有效工具执行或答案。Trace：`trace-cfbb0de15d9e4e199525bc737b38b555`；完整 run_id 与原始可见请求保存在本地 artifact。

这是 Provider SSE 与固定 SDK 事件契约不匹配，发生在 Runtime/External Service 边界；不是检索失败或 Prompt 语义退化，也无法据此证明 High 引发该事件。没有开展其它 effort 对比定位，也没有重试挑选成功结果。

任务明确要求不擅自升级 SDK 或改变已验证 Responses 协议边界，并允许 Provider 不兼容时保留生产 Prompt。故没有跳过未知事件、放宽联合校验、改 endpoint 或切换 Provider。新增 Mock 回归固定该失败透明性。恢复时应单独核实 metadata 的正式字段、必要性与当前协议约定，在获得明确兼容方案后再验证完整终态；不能直接加一个忽略事件分支。

另一个只读发现：历史 semantic index persisted chunker 为 `trivae-semantic-chunker-v1`，当前 main configured 为 `trivae-semantic-chunker-v2-forward`，状态 **stale**。消息数同为473236、revision同为0、54267 chunks，仍不代表语义合同相同。这不是本次 SSE 错误的原因（未执行工具），但后续语义对照必须先准备当前合同的独立索引快照，保持旧快照不变。初始脚本仅预检 canonical snapshot；收尾已将实际派生索引状态纳入 frozen conditions，拒绝未来跨身份复用。

## 4. Prompt 删减与 A/B/C

完整职责决定见 `policy-decisions.md`，沿用已有92条 Policy ID。

| 版本 | 内容 | 字符 | 真实 Query | 决定 |
|---|---|---:|---:|---|
| A | GPT High + Full Prompt | 20450 | 1（失败） | 无有效质量 Baseline |
| B 草稿 | 仅删除 P64 的 get_schema 无参数重述，其余原文保持 | 20419 | 0 | 草稿，未接受、未发布 |
| C | 验证 B 后逐组检索策略精简 | 未构造 | 0 | 前置门禁未通过 |

B 草稿只删除 `get_schema, send no arguments. `，31字符（0.151589%）。其机械约束已有工具 description、无参数 SDK 与 Host 参数拒绝测试承担；是否影响真实模型决策仍未验证。B 草稿保存在 ignored 实验目录，生产未更改。

其它 limit/context/type、SQL、重复语义只列候选，没有累计移除。权限、citation/provenance、作者身份、时间事实、partial/零结果与强否定、必要结构化输出契约全部保留。Host 可以保证合法参数和来源，不保证正文的推荐关系、时序、穷尽性或召回选择。

C 应先以 P13/P14/P16 检索选用/顺序作单组假设，再分别研究 GitHub-first 与窗口/停止；但工具 description 也包含选用策略，仅删 SYSTEM_PROMPT 不能称作完全自主检索。本轮没有真实工具选择，**无法回答 GPT High 是否已能自主替代这些策略**。

A/B/C 没有任何已执行配对，因而没有事实改善/持平/退化对照。质量改善0、持平0、退化0表示没有可评配对；唯一尝试为基础设施失败、质量不可评，不代表质量通过或没有风险。

## 5. 最终质量与效率

- 原 Prompt：20450；最终生产：20450；实际删除比例：**0%**。
- 离线 B 草稿：20419；不是最终通过候选，不以字符下降作为成功。
- 实际 HTTP：**1/120**，剩余119；成功推理0、失败1；目录读取不是推理请求。
- 请求/Token/延迟的 A/B/C 变化：**不可计算**。唯一失败耗时9534ms；输入/输出/推理 Token、缓存量与费用未知。
- 重大新增事实/来源/强否定错误：无答案可评，不能声称零回归。全链质量门禁、历史高风险案例回归、累计配对与独立新 Case 验收均未完成。
- 未使用或查看已有 sealed Holdout；本轮全部计划为已暴露 Development，不能作泛化结论。

## 6. 工程验证与交付

工程 checkpoint：`d093512 feat(eval): configure GPT High and meter Responses screening requests`。该提交是唯一真实请求执行版本；收尾修复与阻塞报告提交为 `e951680`，未重新发送请求。

回归过程：配置/HTTP新增测试先2 failed再通过；mypy 曾暴露 httpx/httpx2 具体客户端赋值类型冲突，已改为各具体分支安装同一 hook，无类型绕过。多轮HTTP、失败计数、跨实例总预算、effort drift、隐私捕获已验证。

真实失败另暴露 `frozen_baseline` 标签不足以证明成功：新增测试先红，随后修复候选复用检查；未来失败文件标记 failed_baseline，本次原件不改。strict response.metadata 失败与 semantic identity drift 均有回归。

最终验证数字见 `validation.md`，提交可由 Git 记录复核，统一 push 结果见本会话最终答复；工程验收不等同 Prompt 质量验收。

完整私有证据只在 ignored `data/evaluation/gpt-high-ablation-20261018/`：experiment、A首条原始 artifact、provider-ledger、total-budget、trace/conversation/evaluation SQLite、完整可见请求、stop-summary、semantic-status、post-stop-audit、B草稿和日志。没有提交私有聊天正文、数据库、完整 Trace、OAuth Token 或密钥。

复现命令与数据条件见 `reproduction.md`。历史失败/冻结/Holdout均未重写；未来任何运行继续使用本轮总ledger，不能重置已消耗1次。

## 7. 最终决定与剩余事项

**不推荐发布精简 Prompt；没有完成生产替换。** 本轮保留全部生产补偿规则，其原因是尚无有效 GPT High 语义验证，不能断言这些规则永远不可删除。

恢复顺序：核实并解决真实 response.metadata 协议不兼容 → 准备与当前 main 一致的独立 semantic index snapshot → 重新完成 High 真实终态与4条 smoke → 扩展 Development 与逐组 B/C → 审查实际答案和证据 → 同条件累计最终门禁。若缺独立新 Holdout，准确标注 Development 验收。

## Interview Defense Notes

- measured fact：实际 body High、HTTP200、unknown SSE事件、1次请求、9534ms、无工具/答案、stale chunker身份。
- regression test fact：SDK Mock HTTP 证明三路径参数、2轮计数、失败计数、跨实例上限、隐藏 replay 排除、失败 Baseline/effort/index drift 拒绝。
- engineering expectation：删除纯参数重述可能减少重复；尚无模型质量或效率收益证据。
- ownership：配置归 ModelSettings，发送归 Responses Model，预算归 HTTP hook，语义质量仍须答案/证据 review。
- trade-off：保留严格协议并停止，失去本轮质量结论，但没有把未完成/不兼容运行包装成成功。当前顺序实验无需并发 budget 状态机；未来并行实验需重新设计计数边界，不能直接并行使用当前 ledger。
