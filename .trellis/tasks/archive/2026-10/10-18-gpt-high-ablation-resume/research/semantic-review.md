# 真实答案语义复核

复核者为独立 Codex Agent，属于模型复核，**不是人工裁决**。本 Agent 未向 Trivae 被测 Provider 额外发送 Judge 请求，新增实验 Provider HTTP 为 0；Codex Agent 自身的模型审查不属于这份 120 HTTP 实验账本。本轮只读检查已完结 artifact、既有 Case/GT、实际 `provider_requests.input` 的完整工具投影，必要处以独立快照 Canonical 只读回查；未修改 GT、候选、数据或预算。完整私有引用、可见输入位置和 Canonical 对照保存在 ignored `resume-reviews/a-initial.json`。

## A 初始两条已完成 Baseline

| Case | 证据送达与引用 | 事实与语义检查 | 本次裁决 |
| --- | --- | --- | --- |
| chatlog-alpha 精确事实 | 两条 exhaustive lexical GT 均在实际模型输入，最终引用一个直接分享证据和同作者补充 | URL 精确、作者一致、UTC 时间与工具投影相同；补充来自同一 Canonical 作者且晚于分享，不误归邻近说话人。兼容性表述归属于分享者，未宣称独立验证 | 此 Case 通过，保留 partial / forward 未展开限制；存在性问题不要求引用每条命中 |
| ts-learning 语义改写 | 已裁决 partial GT target 完整进入实际模型输入并被引用；额外技术栈和讨论例子也有返回原文 | 视频/跟敲时长明确当作说话人估计，未变成掌握全栈保证；作者、建议与接受建议关系有支持，未声称已完成项目；未虚构具体课程或链接 | 此 Case 通过，不能推导 corpus-exhaustive recall 或整体 Baseline 通过 |

两条各有 2、3 次 Provider 请求，实际请求均为 `gpt-6.1-sol / high`；请求数、Usage 等效率数据由主任务统一汇总，避免重复计数。这是 A 单边检查，尚无 B/C 质量方向结论。

## 投影与边界

语义 Case 的显式 context 从 Canonical 返回 31 条，受剩余工具结果预算影响实际只投影 23 条。一个最终引用的后续回复不在第二次工具的可见投影内，但同一完整原文已在第一次 semantic 输出中送达，并保留在最终 Provider 请求历史。因此不能用 Trace 截断或单独最后一轮窗口判定“该事实未送达”。私有报告保留了这项工具引用位置差异；本次证明完整内容实际可见及引用事实有支持，不推断模型如何选择被省略消息的第二轮 handle。

另核对到两个群内展示名属于同一 Canonical 用户；答案用“另一个例子”区分讨论，没有声称是另一个人或汇总人数，因此不判作者错误。不得在后续比较中仅按展示名计数。

答案与 Artifact 保留检索 partial、无具体课程链接等边界，没有用局部结果宣称完整清单或强否定。Finalizer valid 仅作为结构/引用状态，以上语义裁决来自逐条内容核对。

## 排除与发布限制

本目录失败的 matt 请求仅是工程失败记录，本次不记质量通过，也不记质量失败。该高风险讨论 Case 仍须有效端到端结果后才能裁决。

当前结论只覆盖两条 A 的已完成输出；完整 A、B、C、累计门禁与最终发布建议仍由主任务汇总。没有因为这两条通过而允许替换生产 Prompt。

## A 空窗、UTC 统计与 B01 统计配对

继续复核的三条运行均已 completed。完整工具投影、结构化引用、只读 Canonical 验证和条件比较保存于 ignored `resume-reviews/b01-and-structured.json`；仍为 Agent 模型复核，0 新增实验 Provider 请求，未改 GT 或运行记录。

- **A empty-1：通过。** 实际调用 `get_recent_messages`，以请求指定 UTC 日期的当日零点（含）至次日零点（不含）查询；完整 Canonical 窗口 eligible/retrieved=0、has_more=false，无消息、partial=false、无截断。最终 `no_result_signature` 只说明查询档案内无发言及无可总结内容，保留未收录聊天边界。只读独立 Canonical COUNT 同为 0；实际空证明来自成功完整 recent retrieval，未以 SQL COUNT 代替。
- **A UTC-count：通过。** 实际 `get_schema {}` 后执行一次只读 SQL COUNT；日期上下界为所问 UTC 日期的完整半开区间。当前 Tool Result 的完整未截断结构化行给出 883，最终引用精确绑定该 `rows[0]` 与同一 SQL/scope；独立 Canonical 同区间只读计数为 883。答案未混入别日或其它范围事实。
- **B01 UTC-count：本 Case 与 A 持平。** 删除无参数主 Prompt 重述后，仍实际调用 `get_schema {}`，再执行与 A 相同 SQL，得到并正确引用 883，UTC 边界表述正确。后续 Provider 输入里的历史工具重放不计作再次调用。

A/B01 的完整 frozen conditions 字典逐项相等，涵盖模型/High、Case、scope、snapshot、route、SDK/工具合同、预算及语义身份等；B01 Prompt 与生产原文仅相差 manifest 声明的 35 字符 P64 删除。因而该配对确实触发并验证本组 get_schema 无参数职责，不能仅由单 Case 推广至整个 B01 或最终发布门禁。

观测效率：两侧均 3 HTTP，A/B01 input=26013/25986、total=26264/26207、端到端=14148/18747ms。B01 cached input=2944，A=0；本对实际输入少 27 token、总量少 57 token、耗时多 4599ms，缓存不同且只有单次，不能据此声称稳定节省或变慢。费用仍未知。

## A 高风险讨论运行：本地预算失败根因

该完整生产 Prompt 运行没有最终答案，保持工程失败，不能计语义成功或候选退化。独立只读生产 `SQLiteCanonicalReadRepository`、原 lexical 索引、同一参数及原动态 16000 共享池，先通过真实 SDK tool 直接执行，再通过本地 `ScriptedModel` + 真实 namespace SDK Runner 重放；没有模型网络调用、预算改变或数据写入。私有脚本与原始异常链保存在 ignored `resume-diagnostics/risk-budget-replay/`。

精确复现的消耗为：lexical 8546，第一 context 2615，第二 context 4705，累计 15866，剩余 **134**。第三个 context 的 Capability 检索已完成，但 `project_tool_result_for_model` 即使省略消息仍无法在 134 token 内容纳最小结果 envelope，抛出 `ToolResultProjectionError("canonical tool result cannot fit the independent model token budget")`。该调用没有完成 Runtime 结果登记，故 Runtime 的 tool_count=3 表示 lexical+两个完成 context；实际启动的是 lexical+三个 context，不能由完成计数误推仅生成了两个 context。

具体四次调用：lexical 使用 limit=100、before=3、after=5；三个 context 的 before/after 分别为 0/20、20/20、15/8。失败的是最后的 15/8 调用；私有结果保留真实 source handle 与 Canonical anchor 映射，不公开聊天定位符。

真实 SDK `tool_execution.py` 的 `_run_single_tool` 将原异常以 `raise UserError(...) from e` 包装；本地 Runner 捕获的 `UserError.__cause__` 明确仍为该 `ToolResultProjectionError`。这不是 SSE metadata 或 namespace/tool-call 协议缺陷，也不是 `ToolResultBudgetError` 被包装：原异常属于 Evidence 的 `ToolResultProjectionError`，与 Runtime budget 异常类型独立。

当前 Runtime 对该 SDK 包装落入 generic `except Exception`，对外只给 `RUNTIME_ERROR / UserError`，因此真实失败 Trace 丢失稳定预算/投影根因。最小修复建议是保留该失败和原预算，在 Runtime 边界识别 SDK 异常链中明确的 Trivae 投影/预算类型，以稳定、安全错误分类及可用预算事实暴露；不得吞异常、扩大池、重试或伪造成功答案。本 Agent 按本轮只读权限没有改生产代码。若主任务采用修复，应补实际 SDK 包装链回归，并记录后续运行代码版本变化。

主任务决定本轮仅记录该既有可观测性缺口，不修改运行路径，保持实验变量；后续独立修复再处理分类。该失败的预算与窗口参数保持原值，不能通过改默认窗或 GT 将它补记为成功。

## C01 当前真实候选：TS 配对与精确 Case 单边

本轮实际 C01 是 **19854 字符**：只累计 P64 的 35 字符，以及 P13/P14/P16 first-call 句的 561 字符删除；P56/P57 已恢复保留。与早期继承 B02 的 19690 字符草稿区分，不能混用结果。逐段删除与实际请求 Prompt 整串相等，工具描述中的选路指导仍存在。

TS 的 C→A 顺序有效配对，其完整 frozen conditions 字典相等，包含 API/auth 的 `AsyncConnectionPool` 网络身份、High、快照、预算与工具合同。独立 Agent 复核完整模型输入、所有最终引用，并逐条只读 Canonical 对照，私有结果见 ignored `resume-reviews/c01.json`。

- **A 未通过固定 target 要求。** 指定 GT target 不仅没有写进正文，实际各轮工具投影也没有送达，最终证据也未引用，target delivery/citation 均为 0/1。A 所选另一个视频学习讨论本身有原文支持，不能因它不是 target 就将相关事实判为错误；也不能据此改掉既有“须引用 target”要求。
- **C01 在该 Case 通过。** 指定 target 完整送达并被引用，delivery/citation 均为 1/1。4/8 小时区分视频时长与跟敲估算，没有保证短时掌握全栈；具体技术栈、AI 项目困难、建议者与提问者关系，以及新增参与者关于亲手应用/调试的归纳，均有实际可见全文和 Canonical 引用支持。正文把总结明确作为学习建议，没有写成已验证学习成果。不同展示名并未被说成不同人。

本对观察到固定 target recall 改善，但两侧首工具都为 semantic，语义 query 措辞、候选排名与 context 选择不同；不能归因为首次工具次序改变，也不能声称移除全部模型选路指导后获得自治。GT 为 partial target，仍不能据此推导全库完整召回。

TS 两侧均 3 HTTP；A/C input=52454/52386、output=845/852、total=53299/53238，cached input 均 2944，端到端=27810/33245ms。单次观察为 input 少 68、total 少 61、耗时多 5435ms，不构成稳定效率因果结论或完整发布门禁。

精确仓库 Case 的 C01 已完成：两条 exhaustive GT 都送达且引用，URL、分享者、另一参与者引用链接的后续消息与 UTC 均吻合。A 的两次尝试均在发送实验推理 HTTP 前失败、0 实验 HTTP：先局部 phase 上限阻止，后认证 TLS 失败。补跑 A 与 C 的条件虽完全相等，仍没有有效精确 Case 质量配对；不把工程失败记成质量退化，也不拿历史代理条件下 A 补对。所有失败原件保持不变。

## C02 高风险材料推荐恢复

当前 C02 为 **19764 字符**，在 19854 字符 C01 上仅再删 P33 的 90 字符数字示例句，P56/P57 保留。独立 Agent 对 `resume-c02-risk` 的已完成书籍 Case A/C02 做完整 Provider 输入、全部最终来源、Canonical 作者/时间/原文核对，私有证据保存于 ignored `resume-reviews/c02-reply.json`。A/C02 的完整 frozen conditions 相等。

**A 未完成材料恢复，边界表述诚实。** 已找到提问者、点名询问与部分后续讨论，但所有实际工具投影都没有具体书籍推荐、同作者书籍评价和提问者后续回应。显式 context 虽请求 after=80，因剩余投影预算 2135，只送达 17/83 条，实际可见结束于 12:45:03 UTC，早于 12:45:49 的推荐。答案只说尚未核实具体材料/推荐人，没有将有限窗口泛化为之后无人推荐；但没有完成用户要求的具体材料核实。

**C02 在这次材料恢复中改善，未发现新增语义错误。** 实际 context 送达被截短的书名推荐、同一作者“这本书很详细”和提问者后续确认，全部进入最终引用。Canonical 验证推荐者与被点名询问者不同，提问—推荐—后续回应时间顺序一致；答案正确区分，未把邻近作者当推荐者。书名完整关键部分在可见前缀，尾部确被投影截断；答案明确按可见名称记录，不补造版本、链接或内容。它只确认该书在这段求教程讨论中被推荐，对是否专门适用于 Agent 后训练保留不确定性，没有把推荐等同独立验证效果。

C02 对另一参与者的学习状态、概念说明及“不固定路线”的归纳也由本人消息支持；未虚构成熟学习路线，未宣称完整推荐清单，明确实际可见到 12:46:36 UTC且有省略。最终所有引用均与 Canonical 身份/时间/原文吻合；截短推荐的可见前缀也逐字吻合。

不能将该改善直接归为 P33：C02 请求 after=65，比 A 的 80 更小，但前置 semantic 投影消耗 9982，比 A 的 11650 少，最终留给 context 的预算为 3801，对应送达 34/68 条。两侧都为 semantic→lexical→context、3 工具轮、4 HTTP；本对是累计候选行为差异，不是请求窗口变大。用于隔离 P33 的 C01 父候选条件虽相等，仍因 ConnectError 在 1 HTTP 后失败，不能形成有效 C01/C02 增量对照，也不能据此独立接受 90 字删除。

本 Case 的既有 `reference_findings` 为空，本节使用历史已知失败对应的 Canonical witness 做 Agent 语义复核，不新增/改写 GT，不虚报固定 GT recall 或人工新裁决。C02 的 UI Case 在第二 HTTP 连接失败，无最终答案，不作语义质量裁决。缺少这项高风险有效对照，完整发布门禁仍未满足。

A/C02 input=73626/69677、output=774/992、total=74400/70669，cached input=0/2944，端到端=39467/53815ms。实际 total 少 3731、耗时多 14348ms；单对且缓存不同，不作为稳定成本/性能因果结论，金钱费用未知。

## A 资源清单最终核验与总口径

库存 A 已完成，独立 Agent 复核结果为此 Case 通过、保留覆盖限制。实际首个也是唯一工具为 lexical，keyword=`github.com`，start 为 2026-08-01T00:00:00.000Z，limit=5000、context=0/0；Host 继承指定单群与截至 2026-08-16T01:36:30.001Z 的半开上界，没有丢用户起点或扩大群范围。

本次实际返回 10 条消息；同 scope/时间内只读 Canonical 枚举也为 10 条，最终全部引用，正文的作者及 10 个 UTC 时间均逐字匹配实际投影和 Canonical。重复分享合并为 6 个仓库路径；Issue 页面被明确说明为通过 Issue 出现的仓库，推导出的仓库根路径没有冒充直接分享主页。账号主页另列，不计具体仓库；项目数据和推荐价值保留“分享者当时说法、未独立验证”的界线，未捏造功能。bounded lexical 返回本身无 partial/truncated，但 forwarding coverage 仍为 partial；答案明确转发未展开、未覆盖纯名称消息、不保证全量，未作强否定。

私有完整来源与核验结果保存于 ignored `resume-reviews/a-inventory.json`。同一文件包含只读运行库存和逐 phase 账本对账：按 run_id 去重，新派生快照共有 **23 个运行记录，11 completed**；实际向被测 Provider 发送过请求的 **8 个 distinct Case**。完整 phase ledger 合计 **52**，与总 ledger **52/120** 一致；freeze 别名、重放请求历史及多轮工具不会重复计数。

截至停止时只有 **3 个有效局部质量配对**：B01 SQL 持平，C01 TS 指定目标恢复改善，累计 C02 书籍材料恢复改善，即 **改善2／持平1／退化0**。该“退化0”仅指这三对，不代表未完成高风险项无回退，也不是最终门禁通过。B02、精确 C01、UI 和 C01→C02 增量都缺有效完整配对；不得独立接受 P33 示例句删除，或据局部结果发布最终候选。连续 TLS 外部阻塞停止后，本 Agent 仅只读复核；生产完整 Prompt 保留。
