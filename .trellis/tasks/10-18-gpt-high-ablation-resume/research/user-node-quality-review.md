# 用户切换节点后的 A/B01 质量复核

独立 Codex Agent 模型复核，非人工裁决，不替代既定 ReviewPolicy。只读原 Case/GT、独立 Canonical、完整实际 Provider 工具投影、最终答案及引用；未向被测 Provider 增发 Judge 或实验请求，未改代码、Prompt、Case/GT、候选冻结或原运行工件。本记录不含私聊原文、作者身份或来源定位符。

## 最后四条既有 Development：实际均完成

`user-node-final-b01` 的四组均为完整 A/B01 配对，共8个 completed run、18实验HTTP。各组完整 frozen conditions 字典相等；B01 与 A 整串比较仅删除 P64 的35字符，字符20450→20415，没有累计其它未确认策略。比较只在同一新网络 epoch 内进行，不借用旧节点结果补对。

| Case | 原 GT / 实际证据核验 | 质量分类 |
| --- | --- | --- |
| archify context | 两侧固定 direct 与 required_context 均完整送达且最终引用；A10/B9条最终来源的作者、时间、全文与 Canonical 相等并在实际模型输入可见；推荐、正面评价及操作说明没有错归作者或倒置先后 | 固定 GT 恢复持平；共同轻微确信度边界见下 |
| forge exact | 三条 exhaustive 精确 GT 两侧全部送达；最终 URL、分享者、项目流程与后续使用自述有支持。每侧2条最终来源均 Canonical/实际可见全文吻合 | 持平通过此 Case；存在性问法无需最终逐条引用全部重复命中 |
| intern paraphrase | 固定 partial target 两侧均未送达、均未最终引用，0/1；A7/B8条其它实习经历来源均 Canonical/可见全文吻合 | **共同不足**：原 critical 要求未满足，不能计为合格持平通过 |
| empty-2 | 两侧完整成功 recent retrieval，指定 UTC 半开区间、eligible/retrieved=0、has_more=false、无 partial/truncated；只读 Canonical 同区间为0；最终 no_result_signature 与 archive 限定一致 | 持平通过此 Case |

### Archify 共同表述边界

两侧都把一位参与者关于安装后如何调用的提问理解为已安装。该口语理解可成立，但“明确已安装”的确信程度略高于可见文字能独立保证的安装完成事实；没有额外成图或安装完成证据。两侧同时明确前期好评只是初步认可、不是深入试用或独立效果评测，没有把意向/简评升级成生成质量证明。

这是共同的轻微校准点，不能归因于 P64 删除，也不能因固定 direct/context 通过就隐去。若最终报告称此 Case 持平，应保留这项边界；本复核未发现 B01 新增的重大作者/时序/强否定错误。

### Intern 共同缺失是发布门禁事实

原 target 讨论的是理解实际项目设计思路、场景复现与设计决策等困难；A/B01 均召回了其它相关的重复劳动、任务负担等经历，没有送达指定 target。原 GT 明确允许其它主题相关消息，不应将这些有证据的替代内容判成事实错误；但原 critical 同时要求最终引用 target，不能在本轮据替代答案改写或放宽。

因此两侧都有支持的答案，不等于原任务完成。四条全部 completed 只能证明工程执行完成，**最后四条质量门禁仍未通过**。该共同缺口不证明 B01 导致退化，也不能被其它三组持平抵销，不能据此替换生产 Prompt。

### 效率事实

以下为 A/B01 单次观测，非稳定性能因果结论；HTTP阶段合计18，均有本轮 Usage。

| Case | HTTP | input | output | total | cached input | 端到端ms |
| --- | --- | --- | --- | --- | --- | --- |
| archify | 3/3 | 38966/37479 | 651/642 | 39617/38121 | 9984/0 | 30554/24545 |
| forge | 2/2 | 19102/19488 | 384/372 | 19486/19860 | 0/2944 | 15638/14926 |
| intern | 2/2 | 28347/27119 | 680/636 | 29027/27755 | 0/0 | 30793/27886 |
| empty-2 | 2/2 | 15391/15373 | 147/148 | 15538/15521 | 7040/2944 | 12971/14231 |

不能将输出内容、检索结果与缓存造成的差异全归于35字符删除；费用未实测。以上四条在本阶段没有调用 get_schema，P64 的实际无参职责仍以此前 SQL 定向配对为动态证据，本阶段只检验跨任务行为回归。

## 原剩余核心 Case

`user-node-remaining-core` 因第一条独立 Baseline 的输出合同失败提前停止；后续其它 Case 在独立 `user-node-core-rest` 执行。不会因新增核心 Case 的通过改变上述 intern 固定 target 缺失事实，也不会把 Agent 模型复核记为人工接受。

### zero-excalidraw：A 输出合同失败，阶段提前停止

实际仅 A 发送2 HTTP，两次 TLS/Responses 均成功；B01及该阶段后续 Case 未执行。`run.terminal_status=completed` 仅表示 Runtime 已产出模型文本；Query 的 execution_status=failed、is_successful=false、finalization_status=failed，错误为 `INVALID_FINAL_OUTPUT`，没有正式 answer 或 AnswerArtifact。不能将这条计为端到端成功、空结果通过或完整 A/B 质量配对。

已从真实 Trace 读取最后模型 JSON，并以同一生产严格 parser 与原只读检索路径无网络复现：JSON 语法及 no_result 字段形状本身合法；工具确为成功零命中、没有结果事实，但其当前覆盖限制为 `coverage:partial` 与 `unexpanded_forward_content`。因此 `has_verified_zero_result_evidence` 明确为 false，strict finalizer 精确拒绝：

```text
INVALID_FINAL_OUTPUT:
zero-result final answer lacks verified complete-and-empty retrieval evidence
```

原 graceful finalizer 对该稳定错误也保持 fatal 拒绝，artifact=None，未自动恢复。模型虽然在文字中保留了未展开转发的边界，仍选择了要求完整 positive proof 的 no_result 形状；谨慎措辞不能替代该 Host 契约。这是 Baseline 独立的输出合同/证据充分性失败，不是 TLS 或 SSE 故障，也不是 B01 删文退化。

本地复现未修改 coverage、GT、Finalizer、测试或 Prompt，没有新增实验 Provider 请求；不得为了让此 Case 通过而把 partial 重标完整、放宽 no_result 断言或重跑挑选结果。原 Case 的 empty GT 与当前 retrieval 完整覆盖证明是两层事实，本轮保持原件并如实记录未完成。

### cite-archify：A/B01 持平，固定引用要求通过

`user-node-core-rest` 的此 Case 两侧均2 HTTP并端到端完成；完整 frozen conditions 相等，Prompt 串仅 P64 的35字符差异。两侧唯一 lexical 参数完全相同，实际结果投影均33条消息；固定 exhaustive GT 三条均送达并最终引用。各侧7条最终来源（含重复引用）的全文、作者、UTC 时间均与只读 Canonical 一致，且全文在实际 Provider 输入中可见。

两侧均能连接数量里程碑、功能进展、集成公告与赞助陈述；把数量理解为 Star 明确保留语境推断和非实时核验限定，没有将群内发布升级成独立安装测试、当前实时指标或赞助规模证实。所有事实分组有正确引用绑定，没有发现新增作者、时序或引用蕴涵错误。此 Case 的 Agent 质量结论是持平通过，既定 blind human ReviewPolicy 仍 pending。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 2/2 |
| input/output/total | 19712/914/20626；19695/979/20674 |
| cached input | 7168/2944 |
| 端到端ms | 41649/28195 |

这是单次观测，不能把缓存差异或回答组织差异算作35字符删除的稳定因果收益，费用未实测。

### resume-advice：A 共享工具投影失败，B01 未执行

同阶段此 Case 仅 A 发送2 HTTP 后 `RUNTIME_ERROR`/`UserError`，没有最终答案或 AnswerArtifact。前两条工具完成投影：semantic=12192、lexical=3691，合计15883/16000，剩117；实际第三条 get_message_context 以 before=2、after=35 执行，Capability 已成功返回38条上下文，随后投影失败。因此 `tool_count=2` 只计已完成投影的工具记录，不能说模型只调用两条或第三工具未执行。

已用原只读独立 Canonical、原第三条解析后参数、真实前两条预算结算及未改动的生产 SDK adapter，在本地直接调用和 ScriptedModel Runner 两条路径复现。直接异常为 `ToolResultProjectionError: canonical tool result cannot fit the independent model token budget`；SDK 原始链为 `UserError → ToolResultProjectionError`。该117额度连最小合法 envelope 也无法承载，与之前预算耗尽后的结果投影路径一致；不是 TLS、SSE metadata 或终态协议故障。

这是完整生产 Prompt 的独立工程/端到端失败，不是 B01 语义退化证据，也不能评作事实回答失败后再计 B 胜出。Usage 仅回收第一 HTTP 的7270 input、48 output、7318 total，第二次虽 HTTP 成功，但异常路径未汇总完整 Usage，所以这些只是下界；端到端30127ms。严格保留预算、工具窗口、GT与实现，不扩池、不改分类绕过，本次本地诊断0新增实验 Provider 请求。阶段共6 HTTP（引用配对4、简历 A2），没有完整简历 A/B质量配对。

## 最终 B01 的 UI 高风险配对

`user-node-ui-b01` 两侧完整端到端完成，A 为4 HTTP、B01为3 HTTP；frozen conditions 整字典相等，仍仅 P64 的35字符差异。A 使用 semantic→lexical→context，B01 使用 semantic→context，不据工具数量减少就判质量提高。

原 GT direct 与 required_context 两侧均在完整实际模型工具输入中送达，并均进入最终 evidence。推荐者自己的使用反馈与另一位参与者的效果评价没有混淆；两侧都明确，第三方简评不足以证明该人亲自安装运行，也没有把有限评价变成全部参与者共识或高水平设计效果保证。A 的补充报告链接只确认分享，明确未验证外链正文及可访问性。

A5条最终来源的作者/UTC/完整来源快照均与只读 Canonical 相等：其中4条全文直接可见；报告来源正文被截为 URL 前缀，但同一实际消息的结构化 `urls` 保留完整 URL，所以该链接 claim 仍有实际投影支持。B01最终3条来源全文、作者、UTC 均与 Canonical 和实际模型输入一致。固定上下文恢复与引用要求持平通过，未见重大事实或边界退化；这仍是 Agent 模型复核，不是 blind human 接受。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 4/3 |
| input/output/total | 74109/712/74821；54421/638/55059 |
| cached input | 0/2944 |
| 端到端ms | 60475/57720 |

上述为单次实测，工具参数及返回量、缓存均有自然变化；能记录本次请求少1次及 Token 降低，不能单独归因为35字符删除的稳定收益。费用未实测，原总体门禁及人工 ReviewPolicy 均不因此自动通过。

## 额度分类修复后的 B01 书籍配对

`user-node-book-140-recovery` A4/B01 3 HTTP 均完整端到端成功。两侧 frozen conditions 完全相等，代码共同包含同一 nested quota 补丁，Prompt 仍只删 P64 的35字符；没有以旧失败 A 拼接新 B。

A 找到提问及部分后续观点，但第三次 context 请求 before=2、after=100，加 anchor 后103超过既定100条合同，Host 显式返回 INVALID_ARGUMENT。历史独立 Canonical 中已确认的三条材料推荐见证均未送达，最终只谨慎承认未完成材料及推荐者核实，没有强行否定存在推荐。A3条最终来源全文、作者和 UTC 均在实际投影及 Canonical 中一致，因此是有支持但任务不完整的答案。

B01以 lexical→context（after=65）送达三条材料推荐见证，三条全部最终引用；共11条最终来源的全文、作者、UTC均与 Canonical 和实际工具投影吻合。具体材料与推荐人归属正确，没有把提问者或另一位概念答疑者误当推荐者；没有将该书升级为专门后训练教程。作者/版本/链接未证实及另一人未在已核对片段推荐具体材料，均保持片段范围和不确定性，没有扩大成全库不存在其它推荐。该 Case 原 reference_findings 为空，本轮仍按历史 Failure Case 的 Canonical 见证作 Agent 语义审查，不伪造新增人工 GT 或标准召回分数。

本次局部结论为 **B01改善材料恢复**；单次自然工具选窗/参数合规差异不能证明删除无参提示直接导致该改善，也不能替代既定人工 blind 评审或总体质量门禁。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 4/3 |
| input/output/total | 70234/635/70869；50969/882/51851 |
| cached input | 0/0 |
| 端到端ms | 42191/28573 |

费用未实测。此前书籍 HTTP 200 内嵌 quota 的失败保留为独立外部额度失败；本次明确恢复验证使用用户追加授权后的同一累计账本，没有重置、覆盖旧失败或修改每 Query 工具额度/回合数。

## 140 上限下的零结果与时间配对

### empty-1：完整正向证明，持平通过

`user-node-zero-time-140` 此 Case 两侧各2 HTTP，均端到端完成且正式 answer_form=no_result_signature；conditions 完全相等，仅删除 P64 35字符。相同 get_recent_messages 参数覆盖 UTC `[2025-08-11T00:00:00.000Z, 2025-08-12T00:00:00.000Z)`；原只读 Canonical 同区间 count=0。两侧真实工具投影均 status=ok、messages=[]、eligible/retrieved=0、coverage=complete、has_more=false、partial/truncated=false，无省略消息或工具错误。

因此确有 Host 完整且为空的 positive proof，满足原 critical，不是单靠模型宣称空结果。最终均限定当前可查询档案，没有编造讨论或跨越未收录范围。Agent 判定持平通过，human ReviewPolicy 仍 pending。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 2/2 |
| input/output/total | 15391/149/15540；15373/153/15526 |
| cached input | 0/2944 |
| 端到端ms | 14184/10622 |

单次观测，费用未实测；不能把缓存差异当作删文稳定性能收益。

### temporal-7d：覆盖及事实边界持平通过

同目录时间概览 A/B01各3 HTTP，均端到端完成；conditions 相等，仍仅 P64 删除。两侧真实 get_recent_messages 参数、原 next_cursor 的逐字段回传均相同，没有根据当前墙钟改变 archive_latest anchor。固定半开窗口为 `[2026-08-09T02:34:48.000Z, 2026-08-16T02:34:48.001Z)`，只读 Canonical 同窗15221条。两次 retrieval 实取200条，实际模型展示100+26条，第二次因剩余额度省略74；不能把 Artifact covered_units=200 写成模型完整读到200条。

两侧 Artifact 正确声明 partial、truncated、has_more；答案明确只是窗口末段精选，不是完整周报、全周热度排序或穷尽总结，满足原 coverage critical。两侧各22条最终来源的全文、作者、UTC 均与 Canonical 及实际模型投影一致。套餐讨论保留个人体验/担忧而非官方政策，资源问题保留环境线索而非普遍产品缺陷，工具/配置为使用者自述，意向没有写成已经采用，求职关切不升级为招聘行情。

A另选一个有证据支持的参考站分享，B01选择五组其它主题；原 GT 只要求真实 partial 边界而未规定穷尽主题列表，不能仅据 A为6组、B01为5组精选判断退化。未发现 B01新增重大事实或证据错误，Agent 结论为本 Case 持平通过；人工 blind ReviewPolicy 尚未完成。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 3/3 |
| input/output/total | 53594/1820/55414；53567/1736/55303 |
| cached input | 2944/2944 |
| 端到端ms | 48253/50267 |

单次观测，费用未实测，没有据 token 字符减少自动接受生产删文。

## 最后其它核心 Case 的最终 B01 配对

### GitHub inventory：持平通过

`user-node-other-core-140` 的 GitHub清单 A/B01各2 HTTP并端到端完成，conditions 完全相等，仅删 P64。两侧相同 lexical 参数以真实8月1日UTC起点搜索，Host 保持指定单群及原上界；只读 Canonical 同条件原生匹配10条，两侧实际送达10条且最终全部引用。两侧各10条最终来源全文、作者、UTC 与 Canonical 及实际模型投影一致，未错归分享者、倒置时序或丢失重复分享。

两侧清单均覆盖6个仓库路径，其中一项来自 Issue URL，均明确区分实际分享的 Issue 与派生仓库根路径；账号主页单列且不冒充仓库。群内陈述未升级为独立产品质量/指标验证，保留未展开转发的 partial 覆盖边界，没有声称覆盖转发内部所有链接。Agent 结论为持平通过此库存 Case，非人工裁决。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 2/2 |
| input/output/total | 16964/1504/18468；16946/1522/18468 |
| cached input | 0/0 |
| 端到端ms | 41063/38436 |

单次观测，费用未实测。

### Chatlog exact：持平通过

同阶段 Chatlog精确查询 A/B01各2 HTTP并端到端完成，conditions 完全相等、仅 P64 删除。原 exhaustive GT 两条两侧均完整送达且最终引用；各侧最终2条来源的全文、作者、UTC 与 Canonical/实际模型输入一致。仓库 URL 正确，直接分享者与随后追问者区分清楚，时间先后正确；partial 转发边界仍保留，没有将存在性问法扩大成全部仓库功能验证。Agent 判定持平通过，人审 pending。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 2/2 |
| input/output/total | 16741/217/16958；16723/206/16929 |
| cached input | 0/7040 |
| 端到端ms | 19058/12758 |

费用未实测，单次缓存与时延差异不代表稳定删文收益。

### TS learning：B01 固定 target 退化，最终候选门禁拒绝

同阶段 TS A/B01各3 HTTP，均端到端完成；conditions 完全相等，代码一致、仍只删除 P64。已独立核对固定 partial GT 的目标全文、作者、UTC，以及本次所有实际 Provider 工具输入和最终引用：A 首次 semantic 的目标完整送达，并最终引用，1/1；B01目标从未送达、最终未引用，0/1。不是只根据最终正文是否提到特定数字判断，也不是被 Trace 截断误导。

A 的7条最终来源与 B01 的10条其它来源，全文/作者/UTC均与 Canonical 及实际工具投影吻合；其它主题相关建议依原 negative 不能判事实错误。但原 critical 明确要求答案引用 target，B01未满足，A已满足，因此这条是 **B01本次观察到的固定 target 退化**，不能合并成合格持平或共同不足。B01的部分相关答案、谨慎覆盖声明或更少 Token，均不能抵销关键要求缺失。

实际检索差异是 A semantic limit=8，B01=6，查询措辞有自然变化，后续都扩展另一段相关讨论。它们不是实验参数调优，而是同条件模型自然工具决策；本次证据不能证明删除 P64 直接导致召回变化，但已经足以拒绝这轮候选的质量门禁。不得为补过重新挑答案、改目标或以旧 C01/TS改善配对替代此最新 B01退化。

| 指标 | A/B01 |
| --- | --- |
| HTTP | 3/3 |
| input/output/total | 54496/727/55223；52452/847/53299 |
| cached input | 9984/0 |
| 端到端ms | 30271/31592 |

费用未实测。

## 本复核覆盖的最终 B01 方向计数

只统计本文用户切换节点后、同候选20415字符且每对条件相等的完整端到端配对，**12 pair**：

- 改善1：书籍材料恢复。
- 持平且满足该 Case 核心要求9：Archify context、Forge exact、empty-2、cite-archify、UI context、empty-1、temporal-7d、GitHub inventory、Chatlog exact。
- 共同不足1：intern paraphrase，两侧固定 target 缺失，不能写成合格通过。
- 退化1：TS learning，A固定 target恢复、B01缺失。

以上方向均为 Agent 模型复核；既定 blind human ReviewPolicy 仍 pending，不能称人工接受。此12对不包含早期不同网络 epoch 的 SQL定向B01配对，也不包含旧 C01/C02；若主报告汇总早期 SQL，应单列来源与分母，不把 C组改善混成最终B01收益。

另有独立 Baseline 失败未形成完整质量配对：zero-excalidraw 的严格输出合同失败、resume-advice 的共享工具投影失败及早期书籍 quota。它们保留原失败事实，不计入上述12对好结果。最后阶段只读账本为139/140；总账与所有其它历史目录的最终对账由主 Agent 完成。**存在共同 critical 缺失、明确退化及人工评审未完成，生产 SYSTEM_PROMPT 应保留原版。**
