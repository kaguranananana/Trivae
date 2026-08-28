# Exploratory E2E matrix

本矩阵用于真实浏览器执行，不是 fake fixture 的自动化脚本。每个问题执行前记录当前 Conversation、可见 Scope 和 request/trace 关联；执行后只保存 bounded 结果元数据、Failure 证据和必要截图，不把完整真实聊天正文复制到任务文档。

## 自然问题分组（目标 24 个）

| 编号 | 主题 | 自然问题示例 | 重点观察 |
| --- | --- | --- | --- |
| T1 | 最近窗口 | 最近两天大家都聊了些什么？ | 时间解析、recent messages、coverage/partial |
| T2 | 最近窗口 | 最近一周关于 AI 编程工具的讨论有哪些？ | 多群窗口与回答边界 |
| T3 | 时间边界 | 最近一个月群里推荐过哪些 Agent 学习资料？ | 大窗口、分页/截断、Sources |
| T4 | 时间边界 | 最近两周大家讨论过哪些开源项目或 AI 工具？ | 时间锚点、跨群归纳和重复来源 |
| L1 | 精确词 | 群里谁推荐过 GitHub 项目，给出链接？ | 中文/URL lexical 命中、结构化结果 |
| L2 | 精确词 | 群里有没有人分享过觉得好用的 AI Skill、插件或工具？ | 词法证据、评价与来源归因 |
| L3 | CJK 词法 | “推荐”相关的消息有哪些值得关注的内容？ | 中文 bigram 索引、无 LIKE fallback |
| L4 | 资源 | 找出群里推荐过的学习资源，并按类别列出。 | 宽结果、Tool transport limit |
| S1 | 语义 | 大家对 AI 编程工具的看法有没有从前期到后期的变化？ | semantic recall、跨时间综合 |
| S2 | 语义 | 哪些讨论包含可执行的 Agent 学习建议？ | 语义与证据充分性 |
| S3 | 宽泛总结 | 这段时间群里聊了什么？ | 无有效窗口时的诚实失败 |
| S4 | 宽泛总结 | 最近有什么值得关注的技术观点？ | 限制说明、sources 与回答一致性 |
| M1 | 成员 | 成员 2867277364 最近有什么有价值的技术观点？ | find_members、成员 scope |
| M2 | 成员 | 最近一个月哪些成员最常分享 Agent 资料？ | 成员统计与证据边界 |
| M3 | 跨群 | 比较不同群对 Claude 订阅的看法。 | 多 session 聚合与归因 |
| M4 | 指定群 | 在“星河社（星河大学）”里最近讨论了什么？ | 指定 Source Session |
| N1 | 证据不足 | 群里有没有明确推荐过学习方法？如果有，具体是什么？ | complete zero-result、模糊命中与不编造 |
| N2 | 证据区分 | 最近有没有人分享过 GitHub 仓库？请区分“只是提到”和“明确推荐”。 | no-result/弱证据区分与链接证据 |
| N3 | 自然时间边界 | 上周末群里有没有值得关注的技术讨论？ | 相对时间解析、空窗口和回答边界 |
| C1 | 追问 | 先列出最近讨论的 AI 工具，再问：其中哪两个有明确 GitHub 链接？ | 多轮上下文、同一 Conversation |
| C2 | 追问 | 先找推荐过的学习资料，再问：第一项消息前后都说了什么？ | source context drill-down |
| C3 | 追问 | 先比较两个群的观点，再问：差异来自哪些具体成员？ | 上下文与来源复用 |
| C4 | 追问 | 先做一个宽泛总结，再要求只保留有直接证据的结论。 | finalizer/answer artifact 一致性 |

问题可以根据实际 Provider 运行时长和 readiness 结果分批执行，但总数需保持在 20–30 之间；不得为了绕过慢、错或 partial 结果改写成只命中单个样例的问题。

## Answer Quality / Depth 独立 Failure Case 矩阵

以下问题专门用于验证“证据充分但 Final Answer 过度概述”。执行时优先选择实际返回多个独立主题、人物、观点或资源的 Case；若检索本身为空或 partial，仍记录为 Retrieval/coverage 事实，不把它误判为回答深度 Failure。

| Case | 自然问题 | 需要比较的语义属性 |
| --- | --- | --- |
| AQ1 | 最近两天大家聊了什么？ | 主要主题、时间边界、参与者、代表性细节、重要遗漏 |
| AQ2 | 最近大家主要讨论哪些 Agent / AI Coding 相关内容？ | 不同子主题、观点/事实、代表消息、重复与差异 |
| AQ3 | 最近有哪些值得关注的技术资源或 GitHub 项目？ | 资源名称、repo/URL、类别、推荐语境、未找到链接的限制 |
| AQ4 | 某个人最近主要聊了哪些事情？ | 成员身份、主题覆盖、近期时间范围、代表性发言和证据边界 |
| AQ5 | 大家对某个技术问题分别有什么观点？ | 多方观点、分歧/共识、提出者上下文、双方 citation |
| AQ6 | 某段讨论的来龙去脉是什么？ | 起因、讨论发展、转折、结果/未决项、时间和上下文关系 |
| AQ7 | 请对这组搜索结果进行归纳、分类和解释。 | 独立类别、每类代表结果、解释关系、重复/遗漏、来源覆盖 |

每个 AQ Case 与 Trace 一起记录：retrieved evidence volume、Tool Result model projection、是否 truncation、最终 synthesis evidence、claim 数和 `claim.text` 信息量、Answer Content、Sources/limitation、UI DOM 以及重要证据遗漏。AQ3/AQ5/AQ6/AQ7 是优先候选，因为最容易区分“字数变长”和“有效信息覆盖变多”。

## UI / 生命周期检查

1. 首次打开：readiness、空输入 disabled、历史列表、页面无 console error。
2. New Chat：创建草稿但未发送时不产生无依据的回答；首次发送后 Conversation 显示在侧栏。
3. Scope：从全部聊天切到一个真实群，再切到另一个真实群；确认 selector 不修改已有 Conversation 的 trusted scope，必要时创建新草稿。
4. 输入：普通 Enter 发送，Shift+Enter 保留换行，中文 IME 组字期间 Enter 不误发送，空白输入不发送。
5. 流式回答：观察 route/plan/thinking/tool/answer 的时间顺序、过程折叠、最终正文和限制信息。
6. Sources 与上下文：展开来源、点击可用上下文，确认回到 canonical message 且 session/time/source handle 可解释。
7. Trace：复制 Trace ID/Path，打开 Trace 或本地 reveal 入口；失败必须在 UI 显示原因。
8. Stop：运行中点击 Stop 或按 Esc，确认请求终止、UI 显示已停止、Conversation 不提交伪成功 turn。
9. 切换/刷新：运行中切换 Conversation，再返回；刷新后确认历史恢复和中断提示，不发生跨 buffer 串流。
10. 侧栏：重命名、删除 AI Conversation，确认不影响 canonical Source Session；删除当前项后页面可继续发起新草稿。

## Failure 记录模板

- `id`：例如 `F-01`。
- 场景/前置：问题编号、Conversation、Scope、浏览器操作。
- 复现步骤：最少步骤，避免复制完整聊天正文。
- 期望/实际：明确到可观察 UI、HTTP、NDJSON 或 Trace 字段。
- 证据：时间戳、HTTP status、request_id、trace_id、事件类型/序号、console/network 摘要。
- 根因：前端状态、Web adapter、Application、runtime、retrieval、数据或环境，并注明排除过程。
- 修复边界：最小文件/逻辑范围；说明为何不加 fallback/特殊规则。
- 回归：测试文件/用例与真实浏览器原始步骤。

## 本轮实际执行账本

以下是 20 个原始自然问题运行的 bounded 结果；AQ6/AQ7 后续又在修复后重跑，AQ1、AQ3 和简单事实问题也做了复测。Trace 中保留完整审计链，任务文档只列状态与关键计数。

| Case | Trace | 结果摘要 |
| --- | --- | --- |
| AQ1 最近两天概览 | `trace-1fda2d5ebf51428e8615f6f04eec4d8b` | completed；2699 retrieved，1441 projected，717 final |
| AQ2 Agent / AI Coding | `trace-75d3506c55a44b069d1c415b240682e4` | completed/degraded；5000/15221，1430 projected，1536 final |
| AQ3 技术资源 / GitHub | `trace-f2218e5b183846da937e82def3d25dba` | Runtime failure；两路检索后 compatibility repair，未形成 final |
| AQ4 成员近期主题 | `trace-2315d30f87b44a1d81307051afabb767` | Runtime failure；find_members 后泛取 5000/73863 recent |
| AQ5 多方观点 | `trace-986e06c4e2334c2ba3e6de888e638e92` | completed/degraded；lexical+semantic，1228 final |
| AQ6 讨论来龙去脉 | `trace-794897e44b5046b0b53edde0defe7336` | completed；projection 无 omission，549 final，brevity Failure |
| AQ7 搜索结果归纳 | `trace-7d2d1ab6cdfe4af58dd8cf7569103b26` | completed；recent projection omitted 3570，585 final，brevity Failure |
| T3 Agent 学习资料 | `trace-df2a8b301c0147689c436f13e21cf0db` | 用户点击 Stop；UI 已停止，Trace aborted，未伪造成功 |
| T4 开源项目 / AI 工具 | `trace-9f80787c7e2b4192bc0d33316e326393` | completed；partial recent，1215 final |
| L1 GitHub 推荐人和链接 | `trace-3a2deed52a9e47329224c186d94f4b67` | completed；lexical 347，408 final |
| L2 好用 Skill / 插件 / 工具 | `trace-e0fa71b91a8d4cfb9bbdad7b9fd71def` | completed；多路检索，842 final |
| L3 推荐相关消息 | `trace-fc9e4e7e3d4a4089a92e5b8fe5f7ca39` | completed；lexical 1596，projection omitted 561，690 final |
| L4 按类别列学习资源 | `trace-fc7af4af91ca4563a3fddfe4fcbb9dd3` | completed；lexical+semantic，1353 final |
| S1 AI 编程工具观点变化 | `trace-5cb4733d40ab442086a0cdc6d3f9a616` | completed；semantic+recent，484 final，深度候选 |
| S2 可执行 Agent 学习建议 | `trace-df59799e11304f3fa76c7beebaf94fd6` | completed；semantic+lexical，741 final |
| S3 这段时间群里聊什么 | `trace-4ebd921ac72f4010b2ef185b234fb787` | completed；recent partial，729 final |
| S4 值得关注的技术观点 | `trace-4c0fc2b1a25e4e0bbe88b36a2cc0e53e` | completed；recent projection omitted 1258，1014 final |
| M1 成员技术观点 | `trace-8cdf0dbafeaa40e9af3731dac6b33915` | completed；member+semantic+SQL，397 final |
| C1 多轮工具清单追问 | `trace-46ffcc4cf9764fcaabe3db8dbd6fd58b` → `trace-e92ada6f9cd544cf8f4fd2c0bc9c3937` | 同一 Conversation 完成首问与链接追问，421 → 192 final |

后续 Answer Quality / Depth 重测：

- AQ6：`trace-52f1fc16326b40759ea84597087cf71d`，5 claims/793 final/29 citations，DOM 5 段。
- AQ7：`trace-13b02f63aff84b9ea2a8a54e3afa21bb`，6 claims/1598 final/38 citations，DOM 多段分类回答。
- AQ1：`trace-1c73b89e6cb44b0e87e94f47ea95d7d2`，7 claims/1295 final/39 citations；另有一次 `trace-90e32a6d328746579ef5dc4d4cae71b9` 因 candidate 缺少 3 个 `text` 而 degraded。
- AQ3：`trace-ceead8dc094d45918bc514498db11f22` 成功重跑，4 claims/1134 final/19 citations；同问题另有空 final 失败，作为 Provider 方差记录。
- 简单事实：`trace-5401abd68fe24b0f8b7d0022f2eb3737`，1 claim/219 final/2 citations，证明没有 universal verbose。

最后一次 Trace 字段布局修复后又在同一真实 Web server 重测：

- AQ6：`trace-d664f68f13824ade8ab209e153ccaa0e`，Runtime completed，3 个 retrieval/tool calls，model-visible projection 156 条消息、0 omitted/truncated；`answer_shape` 为 4 claims/4 content blocks，文本长度 `[161, 143, 157, 193]`，finalization valid、19 citations。
- 简单事实：`trace-461335012f294b14826ffb574041d53b`，1 lexical tool，1527 estimated tokens、0 omitted/truncated；`answer_shape` 为 1 claim/1 content block、224 字符，finalization valid、2 citations。
