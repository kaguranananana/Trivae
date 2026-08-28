# Final Answer Quality / Depth Failure Case

## 状态

`final-answer-brevity` 已通过真实 Web UI、Trace、Tool Result projection、candidate shape、Host finalizer 和 DOM 完成复现、定位、最小修复与重测。

结论不是“统一把回答写长”：原 Prompt 把 Evidence/Citation bookkeeping 的 bounded 目标直接施加到了用户可见的 `claim.text`，其中固定 grouped claim、concise claim 等要求使复杂问题容易被模型压成概述。修复只调整 final synthesis 的表达职责边界，并增加不含正文的 candidate shape Trace；没有提高 max tokens、改变 temperature、复制原始聊天或放宽 provenance/citation contract。

本记录只保存 bounded 元数据，不保存完整聊天正文、完整模型上下文、Provider 凭证或原始 Tool Result。

## 真实 Web 证据矩阵

字符数、claim 数和 URL 数是诊断指标，不是质量 pass/fail 条件。`projected/omitted` 是模型可见 Tool Result 的消息数；`final` 是 Host finalization 后的用户正文长度。

| Case | Trace | Retrieval → projection | Final / UI 观察 | 结论 |
| --- | --- | --- | --- | --- |
| AQ1 最近两天概览（基线） | `trace-1fda2d5ebf51428e8615f6f04eec4d8b` | 2699/2699，projection 1441，omitted 1258，projection truncated | final 717，6 个 evidence，42 citations，valid；页面覆盖多个主题 | 证据充分，基线回答尚可但仍有压缩空间 |
| AQ2 Agent / AI Coding | `trace-75d3506c55a44b069d1c415b240682e4` | 5000/15221，projection 1430，omitted 3570，partial/truncated | final 1536，7 个 evidence，62 citations，degraded；页面仍有多主题 | Retrieval partial，不能把遗漏全归因于 synthesis |
| AQ3 资源 / GitHub（失败复测） | `trace-2e914390d13046c5a13c97f32f843d52` | recent 2699/2699 + lexical 347/347；projection 1441+347；约 189248 tokens | Provider compatibility observation 后无可见 final text；Runtime completed 但 finalizer `INVALID_FINAL_OUTPUT` | 独立 Provider/长输入故障，不是 E/F 截断 |
| AQ3 资源 / GitHub（同条件成功重跑） | `trace-ceead8dc094d45918bc514498db11f22` | recent 2699/2699；projection 1441，omitted 1258；约 127882 tokens | final 1134，4 claims，19 citations，valid；页面列出项目、分类和链接 | 同问题结果有 Provider 方差；成功路径信息密度合格 |
| AQ3 资源 / GitHub（资源优先修复后） | `trace-11cea2531b6c4984b5c4dc2bf29c5456` | lexical 93/93；projection 93，0 omitted/truncated；Tool Result 约 17070 tokens，synthesis 输入 21613 | final 1999，7 claims / 7 blocks，49 citations，valid；页面按类别展示项目名称、链接和限制 | 资源问题不再先泛取 recent；HTTP 200/stop、非空 candidate，长输入触发条件已避开 |
| AQ4 成员近期主题 | `trace-2315d30f87b44a1d81307051afabb767` | find_members 完整；recent 5000/73863，projection 1430，omitted 3570 | 第二轮 Runtime failure，未进入 finalization | 成员检索后泛取 recent，触发独立 Runtime/Provider failure |
| AQ4 成员近期主题（sender scope 修复后） | `trace-48410dcce379492c81dbcd2566524f14` | find_members 后 recent 52/52；projection 52，0 omitted/truncated | final 676，5 claims / 5 blocks，36 citations，valid；页面覆盖 AI 编程、工具可靠性、开源等主题 | canonical sender filter 贯穿 Tool/Trace/Retrieval，未再读取全体 recent |
| AQ5 多方观点 | `trace-986e06c4e2334c2ba3e6de888e638e92` | lexical 50/36 + semantic 100/10；projection 无消息 omission；semantic partial | final 1228，5 个 evidence，21 citations，degraded；页面有多方观点与限制 | 有效覆盖尚可，partial 仍正确传播 |
| AQ6 讨论来龙去脉（基线） | `trace-794897e44b5046b0b53edde0defe7336` | semantic 100/20 partial + lexical 10/2 + context 41；projection 无 omission | final 549，4 个 evidence，17 citations，valid；页面约 4 段，起因/立场/结果较压缩 | 证据足够但回答深度不足，核心 Failure |
| AQ6 来龙去脉（修复后） | `trace-52f1fc16326b40759ea84597087cf71d` | semantic 100/10 + lexical 91/26 + 3 次 context；projection 无 omission | final 793，5 claims / 5 blocks，29 citations，valid；DOM 5 段长度与 Trace 一致 | 独立起因、双方立场、折中和旁证被展开，修复生效 |
| AQ7 搜索结果归纳（基线） | `trace-7d2d1ab6cdfe4af58dd8cf7569103b26` | recent 5000/73863 + lexical 91/26 + semantic 100/20；projection recent omitted 3570 | final 585，4 个 evidence，19 citations，valid；只给少量分类 | 证据足够但被过度合并，核心 Failure |
| AQ7 搜索结果归纳（修复后） | `trace-13b02f63aff84b9ea2a8a54e3afa21bb` | semantic 100/20 + lexical 26/26 + 2 次 context；projection 无 omission | final 1598，6 claims / 6 blocks，38 citations，valid；页面展示多类、关系和限制 | 分类、解释、噪声边界和代表结果均明显增加 |
| AQ1 概览（修复后一次降级） | `trace-90e32a6d328746579ef5dc4d4cae71b9` | 两次 recent continuation，2000/2699；projection 182727 tokens | candidate 4 条但只有第 1 条有 `text`；Host 丢 3 个坏字段，final 344，degraded | Provider 返回不完整 candidate；contract 正确拒绝坏 claim，不能静默补正文 |
| AQ1 概览（修复后成功重跑） | `trace-1c73b89e6cb44b0e87e94f47ea95d7d2` | recent 1000/2699 partial；projection 1000，无 projection omission | final 1295，7 claims / 7 blocks，39 citations，valid；DOM 7 段 | 修复后复杂概览可以自然展开；一次降级属于 Provider 方差 |
| 简单事实回归 | `trace-5401abd68fe24b0f8b7d0022f2eb3737` | lexical 10/2，projection 10，无 omission | final 219，1 claim / 1 block，2 citations，valid | 简单 yes/no 仍保持简洁，没有 universal verbose |

### 真实 Web 七类问题的逐层观测

- AQ1–AQ2 证明 recent retrieval 可能完整或 partial；Tool Result projection 的 omission 和 retrieval partial 都在 Trace 中可见，不能把 coverage 边界误判成 synthesis 遗漏。
- AQ5–AQ7 中，尤其 AQ6 修复前，模型可见 projection 没有省略核心消息，finalization 也 valid，但回答只保留少数归纳；这排除了 A/B 作为主要解释。
- AQ6 修复后 `candidate_claim_text_lengths` 为 `[210, 138, 129, 155, 153]`，`content_block_text_lengths` 完全相同；AQ7 修复后为 `[214, 338, 192, 258, 421, 165]`，同样完全相同。正文从 candidate 到 Host 和 DOM 没有被裁掉。
- `answer.finalization.completed` 现在只额外保存 claim 数和文本长度，不保存 candidate 正文；Trace 可定位“模型已经生成了多少可见内容”，同时避免把真实聊天或 Provider 输出复制进任务资料。

## A–G 根因判定

| 类别 | 证据判断 |
| --- | --- |
| A Retrieval 本身不足 | 不是 AQ6 的主因：semantic、lexical、context 都返回了与讨论相关的多组证据；AQ1/AQ2 的 partial 只解释覆盖边界。 |
| B Tool Result projection 丢信息 | 不是 AQ6/AQ7 的主因：核心 Case 的 projection omission 为 0；AQ1/AQ2/AQ7 的 recent omission 被 Trace 明确记录，并继续显示 limitation。 |
| C final synthesis prompt 主动压缩 | 已确认是基线 brevity 的主因：旧 Prompt 要求 compact、concise、固定 grouped claim，并把 `claim.text` 作为唯一用户正文。删掉这些固定压缩要求后，AQ6/AQ7 的独立 finding 和具体细节显著增加。 |
| D Answer Candidate / Evidence Contract 限制表达 | 结构性 contributing factor 已确认，但不是本轮实际硬截断：`ModelAnswerClaim.text` 直接进入 `AnswerContentBlock.text`，没有独立完整 prose 字段；字段上限和 40 block 上限均未命中。暂不重构 schema，避免无证据扩大契约。 |
| E Finalizer 编译丢正文 | 未发现正常路径证据：AQ6/AQ7 的 candidate 长度和 content block 长度一致，`user_answer_preserved=true`、finalization valid。对坏 candidate 丢字段是既有透明 contract 行为。 |
| F Web projection / renderer 截断 | 已排除：`chat.ts` 在 `answer.completed` 写入最终正文，`AssistantTurn.vue` 直接 Markdown 渲染；修复后 DOM 段落长度与 Trace content block 长度一致，没有 `slice`/`substring`。 |
| G Provider 偶发过短/空输出 | 作为独立故障确认：资源查询一次在约 189248-token Tool Result 后经过 `provider_compatibility` 仍返回空 final；同条件重跑又成功。修复后 Provider Trace 显示 200/stop 且 repair 前后均有非空 assistant message，说明资源优先检索避开了已证实的大输入触发条件；这不应通过吞错、伪造正文或放宽 Citation contract 修复。 |

## Prompt / Contract 调整

`prompt.py` 的 final synthesis 指令现在明确区分：

```text
Evidence / Citation metadata：bounded、少量 source handles、可审计
用户可见 Answer Content：按问题复杂度展开，覆盖独立 finding、代表细节、参与者/顺序/资源/限制
```

具体变化：

- 保留每条 evidence 的 source handle 上限、partial/truncated 事实、当前 run provenance、scope enforcement、trusted hydration 和“不复制 transcript”的要求。
- 删除固定“exactly one grouped claim”、固定总 URL 数和“为了闭合 JSON 缩短 claim text”等会直接压缩用户正文的要求。
- 增加资源库存与时间概览的选择边界：资源/GitHub/Skill/URL 清单即使带“最近”，也先用
  `lexical_search(github.com)` 收集 URL-bearing evidence，避免先把宽泛 recent 结果塞入 synthesis；普通时间概览
  仍使用 `get_recent_messages`。
- 暴露 `get_recent_messages.sender_user_ids`，要求模型使用 `find_members` 返回的 canonical `user_id`；成员过滤
  作为 typed query/cursor scope 进入 Trace，不改变 trusted session/time scope。
- 允许按独立 finding 分 claim，也允许把同一 finding 的相关事实分组；不为增加长度补充没有 evidence 的背景。
- 明确 `claim.text` 是用户正文，不是 finding label；`finding`、`criterion`、`limitation` 才是保持 concise 的 Evidence metadata。
- 没有改变 max output tokens、temperature、Citation Binding 生成方式或 Web renderer。

`orchestrator.py` 增加了有界 candidate shape metrics。`openai_adapter.py` 同时把真实复现的空 SDK final output 从“completed 后才让 Finalizer 报错”改为 Runtime 层显式 `INVALID_FINAL_OUTPUT / empty_final_output`；不添加新的 fallback 或静默 retry。

## ChatLab 对照

### 代码审计

直接读取的 ChatLab 仓库（HEAD `088d3ee5`）显示：

- 默认中文助手要求简单问题直接回答，复杂问题再分层说明；标题、列表、表格只在有助于理解时使用。
- tool result 之后只要求根据已获取信息自然、直接回答，没有 Trivae 旧 Prompt 的固定 compact/grouped claim 指令。
- EvidenceBlock 独立展示 evidence；普通 assistant text 独立 Markdown 渲染。ChatLab 的 tool result 4000 字符限制主要在持久化/history replay，并带有明确 truncation marker。

### 真实 Web 对照

本机历史数据要求 ChatLab runtime 至少 0.35.1，因此实际对照使用本地安装的 `chatlab-cli@0.37.0`；代码原则审计仍以仓库 HEAD 为准。两套产品使用同一批本地聊天数据，但“最近”默认时间语义并不完全相同，故不把以下结果当成严格同窗口 benchmark。

| 问题 | ChatLab 实际观察 | Trivae 实际观察 | 有效差异 |
| --- | --- | --- | --- |
| TDD 讨论来龙去脉 | 约 1575 个正文字符；内容有讨论背景、来龙去脉、补充背景和证据边界；Evidence 标签为 10/18 | 基线 549、4 claims；修复后 793、5 claims、29 citations；修复后保留了起因、双方立场、折中和未决项 | ChatLab 在相似主题证据下自然分层；Prompt 修复让 Trivae 的回答结构和信息覆盖接近该原则，同时保留 Trivae 的 current-run citation contract |
| 技术资源 / GitHub | 981 条跨对话 evidence、3 个对话；约 1932 个正文字符、3 个主题标题、29 个链接和 10 个代码项 | 一次 2 工具检索因 Provider 空 final 失败；同问题重跑只用 recent evidence 成功，4 claims、1134 字符、19 citations | ChatLab 在一次运行中给出更完整资源清单；Trivae 的差异同时受到不同 recent 窗口和 Provider/长输入方差影响，不能只归因于 Prompt |

ChatLab 的回答更长不是充分证据；本次 TDD 对照之所以记录为 Trivae Failure，是因为其相似证据下的基线回答确实遗漏了讨论起因、不同立场和收束关系，而不是因为字符数低。

## 回归

- `test_final_synthesis_prompt_adapts_answer_depth_without_compressing_prose`：旧 Prompt 下先失败，加入职责边界后通过；锁定不再固定 grouped claim，同时保留 Evidence metadata bounded 要求。
- `test_model_candidate_preserves_independent_answer_prose_and_citations`：两个独立 finding 的正文均保留，分别编译为 content block，并分别拥有 current-run citation。
- `test_answer_candidate_observation_keeps_only_shape_metrics`：Trace 诊断只保存 claim 数和正文长度，不保存模型正文。
- `test_empty_sdk_final_output_is_an_explicit_runtime_failure`：Provider/兼容修复返回空正文时，Runtime 显式失败，不产生 completed+空答案。
- 真实 Web 回归：AQ6、AQ7、AQ1 概览和简单事实问题均在修复后重测；复杂问题展示多个独立内容块，简单事实仍为一个短 claim，partial/truncated limitation 和 citations 仍存在。

最后一次 Trace 字段布局修复后，同一真实 Web server 的复测为：AQ6 `trace-d664f68f13824ade8ab209e153ccaa0e`，4 claims/4 content blocks，文本长度 `[161, 143, 157, 193]`，19 citations，valid，model-visible projection 156 条且 0 omitted/truncated；简单事实 `trace-461335012f294b14826ffb574041d53b` 为 1 claim/224 字符/2 citations，valid 且 0 omitted/truncated。最新 Trace 的 `answer.finalization.completed` 同时保留既有 `answer_text` 和嵌套 `answer_shape`，证明新增诊断没有再挤掉 normal CapturePolicy 的正文快照。

质量判断仍使用 finding coverage、specificity、explanation depth、useful detail、citation coverage 和 question completeness；answer length、claim count、source utilization 只作为诊断信息。

## 独立 Runtime / Provider 观察

资源类问题和成员类问题还暴露了两个不属于 brevity 的问题：

1. 多个大结果合并后，OpenCode Go / DeepSeek V4 Flash 有时在 compatibility repair 后返回空 final 或不完整 candidate；同一问题重跑可成功。修复后增加了 bounded Provider finish/response-shape Trace，并把资源库存的首选路径改为 lexical URL 检索，当前真实 Web 重测成功；没有通过放宽模型 contract 或全局压缩 evidence 来掩盖它。
2. 成员查询在 `find_members` 后让模型泛取大 recent 窗口，AQ4 进入 Runtime failure。现在 Agent-facing tool 暴露 canonical sender filter，并由 Input、cursor、Structured query、Trace 一起约束；真实 Web 重测只返回 52 条成员消息并完成回答。

这两个观察项保留为后续独立 Failure，不改变本轮已确认的 Answer Depth 根因和最小修复边界。
