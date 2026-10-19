# GPT High Prompt 消融实验续跑报告

已完成严格 SSE metadata 修复、独立 v2-forward 索引与真实 GPT High 多轮验证。本次继续排查确认：TLS 握手 EOF 在 HTTP/SSE 之前发生，IPv4/IPv6 都可复现，绕过 HTTP CONNECT 仍经过本机 TUN。原节点同时阻断真实推理与独立 HTTPS；用户亲自切换已有节点后恢复真实实验。源码新增脱敏异常链诊断，**没有关闭 TLS 校验、引入重试或更换 SDK**。

C01 的 UI 高风险端到端门禁失败，因此恢复 P13/P14/P16 首检索指导；最后受测 B01（删 P64 无参重复句35字符，20415字符）又在 TS 固定目标召回/引用上退化，**最终否决精简发布，生产 SYSTEM_PROMPT 保持20450字符，实际删文0**。以下1–3节为已交付合同，4–8节保留52次停止点的历史实验依据，9–10节记录本次续跑与最终预算、质量结论。

最终账本为 **139/140**：用户明确授权把原120上限提高到140，已用次数与历史失败从未重置，剩余1次保留不用。私有答案、工具投影、完整Trace与数据库均留在 ignored 实验目录，不提交Git。Agent复核不能替代既有human/blind ReviewPolicy。

## 1. GPT High、代码与 SDK 合同

固定 Provider=`chatgpt-plan`、Model=`gpt-6.1-sol`、`reasoning={effort:high, summary:auto}`，仅使用 Standard 路径做 Prompt 单变量实验。真实业务入口仍为 `TrivaeApplication.query()`，复用 `run_prompt_screening.py`、EvaluationRunner、Frozen Baseline、ReviewPacket、Trace 与 HTTP 发送前预算钩子，没有第二套 Agent Runtime。

配置与预算基础实现已在 d093512/e951680；本轮协议修复提交为 **b669bcc**。截至52次的Prompt质量运行使用该运行代码，随后只补中文注释；本次aa47c3f另增加传输异常安全观测，不改变成功推理、工具和SSE合同。用户切换节点后的首阶段启动于aaf97bb并带同一诊断增量，后续阶段使用已提交aa47c3f；各组A/B同一实际代码，旧失败身份不改写。Agents SDK **0.22.0**、OpenAI SDK **3.5.0** 保持原版本；无 Medium/Low 对比，无 Jev 或检索算法调整。Runtime、Router、Planner 的实际请求记录均携带 high；完成响应返回的 actual_model 与配置一致。

Router/Planner 独立生产组件回归没有全部成功：Router 一次 ConnectError 后，一次显式重测收到完整 HTTP200/completed/metadata/Usage，但返回内容未通过原 JSON 合同，记录 `ROUTER_COMPLETION_INVALID`；Planner 真实请求触发原 20 秒 `completion_timeout`。未改解析器、超时或路由策略。这些请求计入原累计总账（初始上限120，最终经授权140），不混入固定 Standard 的质量比较。

## 2. SSE 根因、最小修复与验证

原失败是 HTTP200 后，Provider 在工具 `arguments.delta` 与 `arguments.done` 之间发送合法订阅扩展 `response.metadata`，而 Python SDK 的 `ResponseStreamEvent` 联合类型没有这个 tag，导致 `union_tag_invalid → MALFORMED_STREAM`。诊断捕获的真实 wire 后面存在 completed 与 Usage，所以不能归因于 HTTP 错误或缺终态。

核对官方 Codex 已明确处理此旁路事件；安装版本及核对的新版 Python union 均未包含它，盲目升级不能解决。采用 Provider 边界的独立严格 Pydantic 合同：固定 type、非空 response_id、严格非负 int sequence_number、JSON object metadata，禁止额外顶层字段；验证同流 metadata ID 一致，并与 completed Response ID 核对；failed/incomplete 保持原错误分类。仅记录安全根键和关联身份，不把它当作输出、工具、Usage、Reasoning 或成功终态。

未知 tag、畸形 metadata、缺必需字段继续明确失败；`response.completed` 和 completed status 仍是成功条件，failed/incomplete、缺终态、取消、工具参数、缺 name 的关联恢复、Usage 与跨轮 Reasoning replay 均保留原链路。未引入忽略未知事件、重试或降级。

回归先复现为 2 failed/5 passed，修复后相关 **68 passed**；static **415 passed**，Ruff/mypy（128 源文件）通过；全量 **1171 passed、1 skipped**。独立审查还完成真实 metadata 本地重放及 metadata 后取消；候选相关合同/fixture 另有 **245 passed**。这些检查后未改变运行行为；最终补充中文注释的代码与b669bcc通过AST完全等价检查。

修复后的第一组真实三轮全部 completed，metadata、函数调用与终态 Usage 正常。但当时工具索引未 ready，答案明确无法确认，不能作为质量 Baseline。新索引就绪后又完成了本报告后续真实答案与证据检查。

依据：[官方 Codex SSE 实现](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/codex-api/src/sse/responses.rs)。详细核验见 `research/sse-compatibility.md`、`research/protocol-review.md`。

## 3. 独立当前版本快照

历史冻结语义索引为 `trivae-semantic-chunker-v1`；当前为 `trivae-semantic-chunker-v2-forward`，不能改标签复用。生产 v2 索引对应另一份 797278 消息快照，也不能整库拿来冒充同条件实验。

通过 SQLite 只读 backup 复制历史 Canonical，在 ignored `resume-snapshot` 中使用原 Application Builder 重建。原生 **473236 条消息全部 24 字段、14 条来源全部 8 字段**与历史源逐行相等，差异/新增/删除均为 0。历史 Evaluation Snapshot、Case、GT、索引与封存 Holdout 原件未写入。

词法也存在旧合同：缺 current forward projection/revision/count 标记。现有 `rebuild_lexical_index()` 正确生成 **476736 FTS 行 = 473236 原生 + 3500 forward occurrence**，因此新 DatasetSnapshot 的 lexical 行数身份如实变化，不伪装成旧 snapshot。仅副本改 WAL 解决已复现的读写锁冲突，然后继续生产 resume。

语义采用原 `Qwen/Qwen3-Embedding-0.6B`、1024 维、last-token、normalized 与原 query instruction，未改精度、模型加载器或算法。完成状态为 completed，原生/forward 水位 **473236/3500**、revision0 均匹配；**54651 metadata chunks 与 54651 vectors**一一对应，missing/orphan 均0；32向量及32范围回读抽样均有效，最大 norm 偏差约 5.08e-9。

按完整模型身份和输入全文相等复用真实持久向量，未命中走原 Qwen。跨轮真实计算16540、精确缓存38111，合计54651；16093“必须新算”与实际计算差447，是首轮尚未使用缓存时已真实算过447个本可命中的输入。最后一次 resume 实测5429044.72ms，不能当作包含前面轮次的总构建时间。索引大小378036224字节。

新 Case 显式命名 `gpt-high-<parent-id>@v1`，保留原问题、scope、事实、证据位置、partial/exhaustive、质量约束和 review_policy；仅新派生 finding/evidence provenance 绑定新 snapshot，原裁决完整保存在私有 binding manifest。16条离线核验通过：全部已标注 locator 可回读，三个精确全集相等，指定负例仍为空；UTC日计数883，相对7天仍由 archive_latest 锚定、15221条且 partial。派生没有新增人工标注。

## 4. 候选与真实删减决定

原 P01–P92 责任审计继续复用，未重新发明分类。精确删除片段与父链公开在 `experiment/candidate-edits.json`，完整实际 Prompt 在私有每次运行工件中。

|版本|实际字符数|本轮动作与结论|
|---|---:|---|
|A|20450|原完整生产 Prompt|
|B01|20415|删P64的get_schema无参重复句35字符；Schema/Host承接，SQL定向配对持平；仅允许继续累计验证|
|B02|20251|再删P56/P57参数合法性164字符；TLS中断，无有效答案对照，**恢复保留**|
|C01实际版|19854|从B01删P13/P14及P16首检索句561字符，P56/P57仍保留；TS定向改善，但本次UI门禁失败，恢复这组删文|
|C02实际版|19764|在C01再删P33数字示例90字符；累计书籍Case改善，但父控制与UI失败，不能独立接受P33，**恢复保留**|

早期19690/19600字符草稿继承了未确认的B02，未用于上述真实C结果，不混为一版。52次停止点的累计候选为19854字符，少596字符（2.9144%）；本次因UI门禁失败退回B01的20415字符，少35字符（**0.1711%**）。生产实际删减为0。

保留访问范围、Evidence/Citation/Provenance、作者/时间、partial、零结果/强否定、失败表达、结构化输出和讨论恢复指导。没有证据支持让Host替代这些模型语义职责。C01工具 descriptions仍包含同类首次选路指导，因此最多证明主Prompt重复段落在部分样本可删，不能宣称模型在无策略提示下自主检索。

## 5. 历史阶段：截至52次请求的质量差异

新快照共尝试8个不同Case、23个运行工件，其中11个端到端completed、12个未完成；不是23条独立问题。已完成运行不自动等于事实或召回通过。人工既有GT继续使用；本轮由主Agent和独立Codex Agent核对完整Provider工具投影、Canonical、引用与答案，**不是新增人工盲审**，也没有向被测Provider增加Judge请求。

|Case|实际完成情况|质量结论与限制|
|---|---|---|
|chatlog-alpha|初始A完成；C01完成；新网络条件A因TLS/局部门禁未完成|两条精确GT进入候选，URL/作者/UTC有支持；C为单边通过，不能用不同条件旧A补新pair|
|ts-learning|初始A通过；新A/C01完整配对|新A相关事实有证据，但固定target未送达/引用；C01 target完整送达/引用，1/1；partial target上的改善，不推导全库recall|
|empty-1|A完整recent→no_result|UTC半开窗口、eligible/retrieved=0、无更多/截断；未把SQL COUNT当空证明；无累计C有效结果|
|UTC-count|A/B01均schema→SQL→最终答案|实际get_schema都是{}，同一SQL区间得到883并绑定本轮rows[0]，质量持平|
|GitHub inventory|A完成，B02在前一Case中断而未执行它|资源列表、起点、来源/作者/UTC等按实际工具投影复核；没有有效B/C清单对照，不能宣称清单召回精简通过|
|matt context|网络失败后一次真实A执行到工具投影失败|完整Prompt也未完成该高风险Case；不是SSE复发，不计质量通过或候选退化|
|frozen-reply|A/C02完整配对；C01父控制和累计门禁TLS失败|A找到提问/回应但未核实材料；C02恢复具体材料、真实推荐者及先后，限定书名截断/无链接/用途不确定，无新增语义错误；该辅助Case无reference_findings，用历史failure的Canonical见证复核，不伪造GT recall分|
|UI skill|C02第二HTTP连接失败，无最终答案|高风险门禁未完成，不能判持平或通过|

**仅有三个有效质量配对：改善2、持平1、明确退化0。** 大量单边/工程失败和未执行Case不进入这个分母；“0退化”绝不意味着最终非劣或发布通过。原计划其余核心Case和最后4条未用于调参的Development均未完成真实验收，最后4条执行数为0；未接触新的盲Holdout，不作泛化结论。

书籍恢复不能归因于删掉20/40示例：A请求after80但预算只容纳17/83条，C02请求after65却因首检索消耗较小而容纳34/68条。两侧工具顺序相同；差异涉及检索措辞、返回内容和共享投影预算。C01父控制连接失败后，更不能把累计改善独立归给P33。

## 6. 历史阶段：截至52次请求的效率与成本

以下为各有效pair的A/候选值，端到端秒数来自Trace。统一在查询前预载同一编码器，预载耗时单列；没有预跑实际查询编码，首个编码内核、请求顺序、网络和缓存仍可能影响延迟，不能作稳定因果结论。

|配对|HTTP|输入Token|输出Token|推理Token|缓存输入Token|总Token|秒|
|---|---|---|---|---|---|---|---|
|A/B01 SQL|3/3|26013/25986|251/221|0/0|0/2944|26264/26207|14.148/18.747|
|A/C01 TS|3/3|52454/52386|845/852|266/30|2944/2944|53299/53238|27.810/33.245|
|A/C02 reply|4/4|73626/69677|774/992|141/159|0/2944|74400/70669|39.467/53.815|

三组均未减少HTTP，单次总Token较少而延迟更长；对话内容、推理与缓存不同，不将全部变化归于Prompt字符。C02并未进入最终累计候选，不能拿它的Token数据代表19854字符版本。

整个原账本**52/120**，逐目录provider-ledger求和同为52，含成功、失败、诊断、组件回归和多轮额外请求。新快照阶段发送44次；认证目录GET失败及局部phase门禁阻止时，推理HTTP为0，不虚加或漏算已发送请求。

所有阶段可确认返回Usage的40次请求合计：输入**479227**、输出**7155**、总Token **486382**、缓存输入**14720**、推理**913**。这是已知下界，包含协议诊断wire返回与Router真实Usage；另12次请求Usage未知，不能填0。Provider没有返回可用货币费用，**实际金额未知**，没有用价格表估算冒充实测。

## 7. 历史停止点的失败归因

1. **原SDK tag不兼容：已修复。** 真实typed metadata正常，后续多轮工具与终态不再出现该union错误。
2. **派生索引身份/旧lexical合同：已修复。** 独立当前版本completed/integrity valid，新Case显式绑定，原件未污染。
3. **matt完整Prompt的共享投影预算失败：已精确本地复现。** 三个完成结果消耗8546+2615+4705=15866，剩134；第四次Capability已执行，最小结果envelope无法容纳，抛ToolResultProjectionError。SDK包装为UserError后，原Runtime只暴露RUNTIME_ERROR。保留原16000预算和窗口，不用扩池/重试补记成功；这是已有投影/分类可观测性缺口，非本次SSE补丁引入。本轮记录，未扩大成独立Runtime改造。
4. **实验局部phase声明不足：透明保留。** C01阶段声明8次，实际先完成6次TS+2次精确候选后，发送前阻止精确A，0HTTP。原120总门禁正常；后续新阶段改按实际变体数声明，不修改失败工件或总账。
5. **当时外部TLS阻塞。** 异常链在httpcore `start_tls`，没有HTTP状态/SSE。清空代理环境并不等于macOS直连，旧标签已更正；后续显式NO_PROXY并核验API/auth为AsyncConnectionPool，仍复现。代理隧道与绕过HTTP CONNECT的堆栈均保留；本次已证明后者仍走TUN，不是物理直连。UI、父控制与累计门禁连续被该错误中断，最后累计门禁第一请求即失败。

未认证models GET能返回401，说明短时探测可通，但不能证明真实多轮推理稳定，也不能据此编造额度不足或凭据无效。没有关闭TLS验证、切收费Provider、改用户代理/.env、自动重试或无限挑选好结果。当时的协议修复无法消除此握手阻塞，停止点为52/120；本次已在用户切换节点后继续，见第9节。

## 8. 52次停止点的发布决定与待续范围

**不推荐本轮发布精简Prompt；未替换生产SYSTEM_PROMPT。** P64只有一条定向职责验证，C01只有有限质量证据，P56/P57与P33未确认而恢复，UI/matt/累计与最后四条门禁未齐；原human/blind ReviewPolicy保持pending，不能用Agent复核冒充人工接受。

已交付：协议修复与回归、独立可用索引、16条不改GT的派生Case、真实A/B/C结果、失败复现、精确候选删文、预算对账和本报告。脱敏机器摘要见 `experiment/results-summary.json`；完整命令、请求、答案、工具投影、Trace、数据库、case binding和异常链保存在ignored `data/evaluation/gpt-high-ablation-20261018/`，没有提交私有群聊原文、凭据或数据库。其他人仅clone公开仓库无法完整重放私有语料实验，这一限制明确保留。

上述为52次停止点的决定。本次续跑保留旧工件；C01未通过UI端到端门禁而恢复首检索规则，冻结B01后再执行最后四条Development。任何新增重大事实/归属/强否定退化都应拒绝对应候选；最终语义和原review_policy未完整通过之前，生产保持20450字符。

## 9. 2026-10-19 TLS 续修与最终 Development

### 9.1 TLS 根因与恢复边界

真实异常链已经捕获为 `ConnectError → EndOfStream → SSLEOFError / UNEXPECTED_EOF_WHILE_READING`，发生在 start_tls，HTTP状态、SSE和模型内容都尚未返回。AnyIO 用 `from None` 隐藏底层context，旧诊断只查cause，因此看似空字符串。`aa47c3f` 最小修复只对httpx.TransportError保存脱敏的type/message异常链，保持原PROVIDER_ERROR/REQUEST_TIMEOUT、计数、TLS验证和SSE终态不变；真实失败工件已出现安全SSLEOF链。

本机DNS给出的fake-IP实际走TUN。HTTP CONNECT绕过与否不能区分是否通过本机代理核心；账号目录client成功也不能证明Responses另建握手成功。两地址族均已复现：100次新连接对照中IPv4为20/100、IPv6为30/100；因此撤销了尚未提交的IPv4试作，未把它纳入产品。另有连续通过的16/16显式代理与16/16绕过CONNECT、12/12间隔新连接、12/12复用和12/12 curl，这些只能说明间歇可通。随后真实时间C与固定代理的最后四条首个A又发生相同EOF，独立Cloudflare DNS HTTPS也失败，故不能把短时探测成功包装成修复。

当前证据将问题定位至本机TUN/代理共同路径上的握手关闭；没有可读的核心上游日志，不能进一步断言某服务器、证书、IPv6或SDK bug。用户先授权临时切节点，再明确亲自切换好现有节点并要求继续。本Agent沿用该最新设置，不再改动；无凭据16/16探测通过后，新建fresh A/B Baseline继续。网络身份记录HTTP代理连接池和新的user-switched-node epoch，旧失败Baseline不复用、不修改。此为外部网络路径恢复，源码交付是诊断修复，二者分别验收。

### 9.2 切换节点之前新增的真实结果

原52/120账本追加22次到74/120。书籍A/C01各4请求均completed，但具体推荐材料三条历史见证均未送达模型；两侧都诚实保留未知，属于共同任务不足，不能记作高风险通过。UI A的固定direct/context均送达并正确引用；C01在12530+3287=15817后剩183 token，第三条合法lexical结果无法容纳最小envelope，本地真实SDK工具及Runner精确复现ToolResultProjectionError→UserError，保留为端到端失败。

时间A在3请求后完成：范围、archive_latest锚点、15221 eligible与partial边界正确，21个最终来源均有Canonical和实际可见投影支持；模型只完整看到100+26条，不能说看遍200条或完整一周。C在两条工具返回后的第三HTTP握手失败。显式固定代理再试最后四条的首个A，第一HTTP即失败。零结果后续和其余最后三条在该阶段未执行，不填成功。

C01失败不证明删文造成事实错误，但确实未通过既定UI端到端门禁；据此恢复P13/P14/P16首检索指导，再冻结B01，而不是修改工具预算或候选策略补过。B01仅删35字符（0.1711%），P56/P57、P33及所有可信性职责继续保留。最后四条未用于本次选择或进一步调参。

### 9.3 验证与剩余风险

本次新增诊断回归先红后绿；相关Provider/OAuth/query/completion/screening **122 passed**，Ruff、mypy128源文件与diff-check通过；全量 **1172 passed、1 skipped（26.96秒）**。跳过项仍为明确opt-in的真实launchd集成，不是实验GPT请求。已通过本轮失败工件验证生产安全观测能保留SSLEOF，成功High工具与终态另由真实运行验证。

旧matt和新UI的小余量投影失败均保留：现有Runtime把SDK包装后的原投影异常泛化为RUNTIME_ERROR，属于尚未修复的预算准入/分类缺口。没有扩16000共享池、改窗口或吞错来掩盖它。独立索引、GT、scope、模型与High均沿用，原封存Holdout未触碰，货币成本仍未知。最终逐Case结论与预算已在第10节统一收口，不能仅据已completed或Token下降发布。

### 9.4 最后四条 Development 的 A/B01 结果

用户切换节点后新阶段实际完成8个端到端运行、18次推理HTTP，全部TLS/SSE成功。每组完整conditions相等，Prompt仅差P64的35字符；没有把这些Development称为新盲Holdout。B01冻结发生在查看本阶段答案之前，之后未调参。

|Case|A/B01事实与证据|质量结论|
|---|---|---|
|archify context|固定direct/context均完整送达并引用；所有来源作者/时间/全文与Canonical及实际输入吻合|固定目标持平；共同把安装后用法提问表述成“已安装”，确信度略高，保留此轻微边界|
|forge exact|3条exhaustive精确GT两侧全送达；URL、分享者和使用自述有支持|持平通过|
|intern paraphrase|固定critical target两侧都未送达、未引用（0/1）；其它相关困难均有真实支持|共同不足，不能算合格持平，最终质量门禁未通过|
|empty-2|完整UTC半开区间、eligible/retrieved=0、无截断/partial、Canonical COUNT=0|可信no_result持平通过|

这里“全部运行完成”和“门禁未通过”同时成立。没有发现B01新增的重大事实/作者/时序/强否定退化，但intern关键证据漏召回不能由其它三条或Token节省抵销。两侧替代实习经历不被改判事实错误，也不据此放宽GT。

|Case（A/B01）|HTTP|输入Token|输出Token|总Token|缓存输入|端到端秒|
|---|---|---|---|---|---|---|
|archify|3/3|38966/37479|651/642|39617/38121|9984/0|30.554/24.545|
|forge|2/2|19102/19488|384/372|19486/19860|0/2944|15.638/14.926|
|intern|2/2|28347/27119|680/636|29027/27755|0/0|30.793/27.886|
|empty-2|2/2|15391/15373|147/148|15538/15521|7040/2944|12.971/14.231|

四组请求数完全相同，Token与延迟有升有降；检索内容、输出与缓存不同，不将单次差异全部归于35字符。四组没有实际调用get_schema，P64无参职责的动态验证仍是此前SQL配对；这些组只补跨任务行为检验。货币费用未返回。

后续excalidraw的A用2请求完成Runtime，却被生产Finalizer拒绝：lexical无直接命中，但全局forward尚有未展开内容，检索带coverage:partial/unexpanded_forward_content，不能证明完整且为空。最后JSON能严格parse，no_result缺verified complete-and-empty evidence，精确本地复现INVALID_FINAL_OUTPUT。因此正式答案/Artifact均为空、Query失败，该阶段停止且B未执行；不能只按run.terminal_status=completed算端到端成功。保留可信零结果合同，不以谨慎语气代替positive proof，也不把Baseline独立失败归于B01。


### 9.5 其余核心场景与高风险复核

- 引用Case：A/B01各2请求，同一lexical参数、固定3条GT均送达并引用；各7条最终来源的作者、UTC和全文与Canonical/实际输入吻合，Star语境推断与非实时边界保留，判持平。
- 简历建议A：semantic12192+lexical3691=15883，余117 token；同一回合后续context已检索38条但无法投影，精确无网络重放得到ToolResultProjectionError→SDK UserError。实际2个推理HTTP，只有已结算投影记入tool_count，不能据tool_count2说第三Capability未执行。没有候选答案，不作质量方向；原阶段已停止，独立后续Case继续。
- UI新A/B01：4/3请求，固定direct/context均送达并引用；两侧把第三方正面评价与亲自安装使用证据区分，判固定GT持平通过。A的一个链接来源content前缀截断，但实际结构化urls保留完整URL和作者UTC，仅用于支持链接存在；未冒充读取外链正文。两侧conditions相等，只差P64。A/B01输入74109/54421、输出712/638、总74821/55059、缓存0/2944、端到端60.475/57.720秒。单次少1请求不能外推为稳定P64收益。

这些结果没有消除先前C01的UI失败、intern关键漏召回、excalidraw正式输出拒绝或已有工具小余量异常。原human-only、blind_pairwise ReviewPolicy保持pending，Agent审查只作为本报告证据复核。

### 9.6 共享额度错误、明确预算授权与恢复

原节点切换后的书籍首个A曾在108次总账处返回HTTP200、metadata及嵌套SSE error。实际叶子为`subscription_sharing_usage_limit_exceeded`，不是TLS故障；旧适配从外层envelope取code/message，误报`error: error`且丢失既有stops_inference标记。安全Trace保留了实际叶子，可精确定位，无需猜测付费状态或换Provider。

`0f6d531` 对已证实嵌套envelope及四字段叶子增加独立严格类型；非空type/code/message、必需可空param、严格非负seq、禁止额外字段。验证后用真实叶子驱动原错误分类，Runtime/Router/Planner均触发既有额度硬停，不继续工具或推理。原平铺error、failed/incomplete、metadata、未知事件拒绝、终态、Usage与Reasoning保持原路径。真实形状回放先8红、后77相关测试通过，全量**1180 passed、1 skipped（26.07秒）**，Ruff/mypy128/diff-check通过。没有为测试调用真实额度接口或制造账号限额。

用户在2026-10-19 04:58:22Z明确要求“增大一点预算继续”。总上限仅从120调整到**140**，原累计**108**完整保留，既有phase ledger及所有失败工件不改；新增授权记录见`experiment/budget-amendments.json`。这是本地实验HTTP上限调整，不增加账号订阅额度，不改变每Query3工具轮/16000投影池、模型档位、Case或GT。

核对发现额度失败发生00:31Z，恢复验证时已过去约4.5小时，因此不把旧失败当成当前仍限流的证据。修复通过测试后，在同账本做一次明确有界恢复验证：若仍额度错误即停止。实际新A/B01各4/3请求完整成功，说明额度已恢复；没有自动重试、改收费Provider或清零预算。新阶段使用相同嵌套修复代码，下一阶段运行已提交的0f6d531。

新书籍A尝试context_before=2/after=100，含anchor共103超过Host上限，工具明确INVALID_ARGUMENT；最终承认材料未核实，没有伪造推荐或强否定。B01通过lexical→context（after65）恢复三条材料/推荐者/随后确认的历史见证并全引用；未把资料升级为专门后训练教程。A3/B11个最终来源均有Canonical与完整实际模型投影支持。本次B01材料恢复改善，但单次自然检索/参数变化不能独立证明P64删除导致改善；此辅助Case原reference_findings为空，使用历史Failure的Canonical见证复核，不伪造GT recall或新增人工裁决。

该对A/B01输入70234/50969、输出635/882、总Token70869/51851、缓存0/0、HTTP4/3、端到端42.191/28.573秒，费用未知。真实额度曾用完、后来恢复与实验预算上限的授权调整分别记录，不能混为一种限制。


## 10. 最终结论与可核验总账

### 10.1 最后一条 TS 触发拒绝，全部删文保留

最终 TS A/B01 都产生了有证据支持的回答，但A送达并最终引用固定critical target（1/1），B01所有真实工具投影都未送达该target、最终未引用（0/1）。两侧conditions整字典相同、Prompt仅差P6435字符；A实际semantic limit8，B01自然选择limit6且query略有变化。A7/B10个其它最终来源均与Canonical/实际完整输入吻合，不能把B01相关替代内容判成事实错误；但原critical要求没有满足，**这次配对属于关键召回/引用退化，最终B01被拒绝**。

不能据单次自然工具选择证明“35字符直接导致退化”或“P64本身必不可少”；本轮也没有足够证据安全发布其删除。遵守门禁，保留P64，不重跑挑好答案。A/B01输入54496/52452、输出727/847、总55223/53299、缓存9984/0、HTTP3/3、端到端30.271/31.592秒。B01少取候选并省Token，同时漏掉关键证据，正说明Token节省不能替代质量判断。

### 10.2 完整A/B/C结论

最终B01 **13组完整配对**（旧节点SQL定向1组、新节点累计12组）：**改善1、合格持平10、共同不足1、退化1**。新节点12组单列为改善1、合格持平9、共同不足1、退化1。共同不足不算合格持平；这些是配对单位，不是13个新独立问题或人工盲审结论。

另有C组3个完整配对：C01 TS改善、C02书籍改善、C01书籍共同不足；C01 UI工程失败、C02父控制/UI不完整等不进入成功配对分母。跨全部受测版本共16个已复核完整配对，改善3、合格持平10、共同不足2、退化1，**不能用这些累计结果替代最终B01门禁**。早期19690/19600草稿从未冒充实际C版本。

|原定Case|最终/实际A、B、C证据|结论|
|---|---|---|
|chatlog-alpha|新A/B01固定2条GT均送达且引用；早期C01单边也通过|最终B01持平|
|TS learning|旧A/C01改善；最终A/B01为1/1对0/1|最终B01关键退化，拒绝|
|matt context|A共享投影剩134，最小envelope无法容纳|无有效A/B，独立主链路失败保留|
|empty-1|新A/B01完整UTC空窗positive proof|持平|
|cite archify|新A/B01三条固定GT全送达/引用|持平|
|temporal 7d|新A/B01都正确复制UTC/cursor，15221 eligible，仅100+26完整可见|partial综述持平，不是完整周报|
|resume advice|A剩117投影失败，原SDK包装UserError|无有效A/B，不用失败Baseline|
|excalidraw|A JSON可解析但partial不足no_result证明，被Finalizer拒绝|无有效A/B，保留严格拒绝|
|book reply|C02改善、C01共同漏材料；新A/B01恢复3条历史见证|本次B01改善，不独立归因P64|
|UI skill|C01剩183投影失败；新A/B01恢复固定direct/context并正确区分评价/亲自使用|最终B01持平，C01不接受|
|GitHub inventory|新A/B01原生10条全送达/引用，6仓库与Issue/主页区分、forward partial正确|持平，无新盲Holdout|
|UTC count|A/B01真实schema{}→SQL，883及绑定一致|定向持平|
|archify context（最后4）|固定direct/context两侧恢复；共同安装确信度轻微边界保留|固定目标持平|
|forge exact（最后4）|3条exhaustive GT均送达，URL/分享者/流程自述有支持|持平|
|intern（最后4）|两侧固定target都0/1；其它相关经历有证据|共同不足，非合格持平|
|empty-2（最后4）|完整UTC空窗、Canonical COUNT0、无截断/partial|持平|

16个原定Development都至少实际尝试，新快照共**57个独立run**，其中Runtime completed40、正式Query成功答案**39**；差1是excalidraw被Finalizer拒绝。其它18个Query未成功，含网络、额度、投影、认证或发送前门禁等保留事实，不能把57当独立Case数。最后4条真实8个端到端完成，但intern未通过。全阶段共60个去重run（另3个为新索引绑定前的原identity协议验证/失败）；不以alias文件重复计数。

### 10.3 效率与成本：仅描述实测

最终13组B01配对的合计如下，包含一组旧节点SQL，不能作同一网络时段的稳定性能实验。每组内部非Prompt条件一致，组间网络epoch、缓存、检索选词/参数、内容和自然模型波动仍存在。

|13组配对合计|A|B01|
|---|---:|---:|
|推理HTTP|34|32|
|输入Token|449060|405591|
|输出Token|8791|8982|
|总Token|457851|414573|
|缓存输入Token|37120|27648|
|端到端秒数之和|401.248|358.498|

本次少2请求、总Token少43278（约9.45%），不代表35字符稳定造成该收益，更不能抵销TS退化。生产仍20450字符，最终接受的删除字符为**0**；不能拿20415候选或19854/19764的被否决C版本当生产结果。

整个原账本最终 **139/140**，31个phase ledger之和同为139，保留1次而不为用满预算重复挑结果。139份实际推理body均核验`gpt-6.1-sol`及`{effort:high,summary:auto}`；保存的input均不含隐藏reasoning replay。真实请求包括所有失败、多轮、协议诊断及组件回归，目录GET不冒充推理。120→140仅来自用户新授权，原已用108及各历史phase未改。

有完整/已返回Usage的**122次请求**已知下界：输入**1639148**、输出**28826**、总Token **1667974**、缓存输入**83584**、推理**4027**；另**17次Usage未知或未完整汇总**，不能填0。金额**未知**，不以价格表或订阅价格估算冒充实测。

用户切换节点后65次推理HTTP未再出现TLS握手失败；其中1次为真实sharing额度错误，明确时间后恢复验证及后续请求成功。未将HTTP200当成功、未关闭TLS校验、未增加自动重试、未切收费Provider、未重置账本。原节点TLS具体上游原因仍缺核心日志，当前证据支持网络路径恢复，不能声称永久修复了上游节点。

### 10.4 发布与交付决定

**不发布精简Prompt；原生产SYSTEM_PROMPT完全保留。** B01发生critical目标退化，C01 UI门禁失败，B02/P33等未独立充分验证，intern共同不足和三条无有效Baseline的Case也如实保留。P64、P13/P14/P16、P56/P57、P33均保留；没有任何删文通过本轮最终生产门禁。原human-only/blind pairwise政策仍pending，不把Codex Agent审查写成人工接受；否决候选不以补做人审或重复采样为借口发布。

已交付代码：严格metadata合同（b669bcc）、TLS真实原因脱敏诊断（aa47c3f）、嵌套SSE错误/额度停止（0f6d531），以及相应回归、规范和本报告。最后源码全量1180通过/1跳过；报告/预算/原Prompt不变均另外对账。独立索引、Case原GT和封存Holdout未污染；完整本机证据在ignored目录，公开文件只含脱敏指标与结论。

剩余风险是既有小余量工具投影失败与SDK泛化分类、失败路径Usage不完整、GPT High检索/参数的自然波动，以及未经新增人工盲审的语义结论。Router/Planner先前真实JSON/超时回归仍未全部通过，本轮没有扩成独立Utility优化。若后续修复这些主链路合同，应以新的明确实验身份重新冻结非Prompt条件，保留本轮负结论；不能改GT或用不同Host实现补记本轮成功。

本轮归档的是修复和有界实验的交付记录，结论为否决；不表示精简成功、全Case有效Baseline齐备或人工盲审通过。剩余1次不再使用，也不因相同heartbeat指令自动扩充预算。
