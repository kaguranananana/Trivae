# TLS 后核心 Case 复核与 UI 失败归因

范围：`tls-core-validation` 的书籍与 UI 两组 A/C01。独立 Codex Agent 模型复核，非人工裁决；只读真实 Case/GT、完整 `provider_requests.input`、Trace 与独立 Canonical，并使用无网络 SDK 工具复现。未向 Trivae 被测 Provider 增发 Judge 或实验请求，未改代码、GT、运行工件或预算。仅新增本脱敏记录。

## 运行身份与结论

四条真实运行均为既定 High / Standard 路径，A=20450、C01=19854 字符。每个 Case 内 A/C 的完整 frozen conditions 字典相等，API/auth 均记录 `AsyncConnectionPool`。本阶段实际 HTTP 为书籍 A4+C4、UI A4+C3，共15；全局账本仍由主任务统一维护，本复核不冻结并行追加中的全局数字。

| Case | A | C01 | 可得结论 |
| --- | --- | --- | --- |
| 书籍推荐 | completed，但未恢复具体材料及推荐者 | completed，但同样未恢复 | 共同未完成关键材料任务，不可因两侧一致而计高风险职责通过 |
| UI 推荐与他人评价 | completed；固定 direct 和 required_context 均送达并最终引用，语义通过 | 第三 HTTP 后本地投影失败，无最终答案 | 候选未通过此端到端门禁；不能将缺失答案评价成事实错误，也不能记持平或通过 |

书籍 Case 当前既有 `reference_findings` 为空，材料检查沿用历史 failure 的 Canonical witness，不新增 GT 或伪造固定 recall 分。UI 沿用原已裁决 direct/context 要求，没有放宽标准。

## UI A：固定 GT 与答案支持

- 固定推荐消息在第二次 lexical 结果完整送达，最终引用也绑定该消息。推荐用途、原链接、推荐者本人“跑过并认为不错”、与浏览器结合检查个人网站并生成报告，均与实际可见原文及 Canonical 一致。
- 固定后续评价在显式 context 完整送达并引用，附加的评价补充也完整可见。三条最终来源的作者、时间、全文逐项匹配 Canonical；推荐者和评价者确为不同 Canonical 用户，没有仅凭展示名推定不同人。
- 答案明确短评价不能证明亲自安装/运行，未把第三人的正面评价夸成已验证使用反馈。没有虚构功能细节或学习/使用效果，也没有强否定其它评价。
- context 受预算只送达 11/45 条，但本 Case 指定 direct/context 均已实际送达；不能因整体截断否认已可见 GT，也不能将目标恢复等同完整讨论覆盖。

## UI C01：准确根因与无网络复现

真实 Trace 中前两条完成结果分别消耗 **12530 + 3287 = 15817**，原动态共享池为16000，剩 **183**。第三条是合法的 lexical 调用：keyword 为 UI 与 skill 的联合词，limit=10、context_before=5、context_after=30。Capability 的检索已经开始并形成底层完成事实，但其结果没有完成模型投影和 Runtime 登记，因此 Runtime tool_count=2 不表示模型只调用了两个工具。

使用生产只读 Canonical/lexical adapter、同一参数与原16000策略，按真实前两次完成计量重放结算，准确得到183余额；没有扩大/缩小原预算或改默认参数。直接调用真实 SDK tool 得到：

```text
ToolResultProjectionError:
canonical tool result cannot fit the independent model token budget
```

再由本地 `ScriptedModel` 和真实 namespace SDK Runner 调用相同最后工具，异常链准确为：

```text
UserError: Error running tool lexical_search: canonical tool result cannot fit the independent model token budget
  caused by ToolResultProjectionError
```

根因路径为 `search_messages` → `_append_runtime_tool_result` → `project_tool_result_for_model`；最后在 `evidence.py` 的所有 direct hit 已省略仍不能容纳最小 envelope 分支显式失败。SDK 保留 cause 的包装与先前 matt 失败一致，不是 SSE metadata、TLS、namespace、非法参数或语义索引身份错误。

这是现有预算执行边界及错误分类的可复现缺口：`begin_call()` 只在余额≤0时拒绝，正余额183仍获准进入检索，但不足以容纳该结果最小模型 envelope；`ToolResultProjectionError` 独立于 Runtime 的 `ToolResultBudgetError` 类型，SDK 再将其包装为 `UserError`，最终 generic Runtime 只保留 `RUNTIME_ERROR`。检索策略消耗预算触发了这个边界，不能仅据此声称删文导致事实质量退化。

**最小合理修复建议**：在 Runtime 捕获实际 SDK 包装后，对明确的 Trivae `ToolResultProjectionError` cause 保留稳定投影/预算错误分类和已知余额，而非泛化复制 SDK 原始正文；继续保留失败，不吞异常、不返回伪成功、不扩池、不改默认窗。此举修复根因透明性，不声称让183 token容纳结果。若要在这类预算压力下转为正式有限证据回答，需要单独明确预算终态合同并验证，不能作为本轮即时 fallback。按本轮只读职责没有改生产实现。

UI 候选在失败前实际发送给模型的两个工具投影都未包含固定 direct/context，第三次结果又未送达。因此既没有最终回答可评，也没有完成高风险证据恢复；这条运行应保留为明确的运行失败，不能排除后宣称候选门禁通过。

## 新书籍 A/C01：共同缺口

两侧均定位原始提问，并进入同一 semantic→lexical→context 三轮工具链。A 先消耗11028+4022，context只剩950，最终送达5/78条；C01消耗11028+4030，context只剩942，送达4/68条。两侧所有实际 Provider 工具输入均未包含具体书籍推荐、同作者评价、提问者随后确认这三条历史见证，最终也没有引用。

A/C 最终引用分别4条和1条，作者/时间/原文均与 Canonical 一致并实际可见。A 正确区分邻近的无关实习生话题，C 明确只确认提问；二者都没有虚构推荐人或材料，没有把小窗升级成“无人回复/无任何推荐”。这种诚实边界值得保留，但无法完成用户要求的材料与推荐者核实，不能把共同漏召回当非劣通过。

该 C01 配对不能与旧 C02 的单次材料恢复跨运行条件拼接成 P33 独立收益。实际选词、窗口、共享预算及模型波动均需保持原记录；生产仍须等有效累计门禁，不因这两条 completed 就发布。

## 指标与边界

- 新书籍 A/C01 均4 HTTP，input=75339/74673，output=780/655，total=76119/75328，端到端=38798/36167ms；无实测货币费用，不将单次差异解释为稳定收益。
- UI A 为4 HTTP，input74620/output648/total75268，端到端37474ms。UI C01发出3 HTTP，Runtime目前仅保留2次 Usage：input28523/output125/total28648，端到端21434ms；该 Usage 是可见下界，不能冒充3次请求完整Token或据失败更快宣称效率改善。
- 本复核没有新增实验 Provider 请求或 Judge 请求，没有修改 Case/GT、模型参数、工具默认值或生产预算。Agent 模型复核仍不能替代既定人工 ReviewPolicy。
