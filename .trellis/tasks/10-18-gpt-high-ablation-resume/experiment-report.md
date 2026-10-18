# GPT High Prompt 消融实验续跑报告

本轮完成了 SSE 根因修复、回归测试、真实 GPT High 工具调用验证，以及与当前代码匹配的独立词法/语义快照。A/B/C 已执行真实请求，但**完整质量门禁未完成，生产 SYSTEM_PROMPT 未替换**。当前硬阻塞是官方端点 TLS 握手阶段的间歇连接失败；代理与明确绕过代理两条路径均已复现。原总账本停在 **52/120，保留 68 次**，并非预算耗尽。

这是部分完成的实验报告，不是发布通过记录。任务保持待续，不归档为全部完成。所有数字来自本机真实工件；失败请求、0 推理请求的认证失败和发送前预算阻止均分别保留。

## 1. GPT High、代码与 SDK 合同

固定 Provider=`chatgpt-plan`、Model=`gpt-6.1-sol`、`reasoning={effort:high, summary:auto}`，仅使用 Standard 路径做 Prompt 单变量实验。真实业务入口仍为 `TrivaeApplication.query()`，复用 `run_prompt_screening.py`、EvaluationRunner、Frozen Baseline、ReviewPacket、Trace 与 HTTP 发送前预算钩子，没有第二套 Agent Runtime。

配置与预算基础实现已在 d093512/e951680；本轮协议修复提交为 **b669bcc**。修复后的Prompt质量运行使用该运行代码，后续只补中文逐行注释与脱敏文档，未改变运行行为；旧失败与修复前严格复现保留各自原代码身份，不混为同一版本。Agents SDK **0.22.0**、OpenAI SDK **3.5.0** 保持原版本；无 Medium/Low 对比，无 Jev 或检索算法调整。Runtime、Router、Planner 的实际请求记录均携带 high；完成响应返回的 actual_model 与配置一致。

Router/Planner 独立生产组件回归没有全部成功：Router 一次 ConnectError 后，一次显式重测收到完整 HTTP200/completed/metadata/Usage，但返回内容未通过原 JSON 合同，记录 `ROUTER_COMPLETION_INVALID`；Planner 真实请求触发原 20 秒 `completion_timeout`。未改解析器、超时或路由策略。这些请求计入 120 总账，不混入固定 Standard 的质量比较。

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
|C01实际版|19854|从B01删P13/P14及P16首检索句561字符，P56/P57仍保留；TS配对改善，精确Case仅候选单边通过；固定为待续累计验收候选|
|C02实际版|19764|在C01再删P33数字示例90字符；累计书籍Case改善，但父控制与UI失败，不能独立接受P33，**恢复保留**|

早期19690/19600字符草稿继承了未确认的B02，未用于上述真实C结果，不混为一版。当前累计候选19854，比原文少596字符（**2.9144%**），不是生产最终版本；生产实际删减为0。

保留访问范围、Evidence/Citation/Provenance、作者/时间、partial、零结果/强否定、失败表达、结构化输出和讨论恢复指导。没有证据支持让Host替代这些模型语义职责。C01工具 descriptions仍包含同类首次选路指导，因此最多证明主Prompt重复段落在部分样本可删，不能宣称模型在无策略提示下自主检索。

## 5. 真实 Case 结果与质量差异

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

## 6. 实测效率与成本

以下为各有效pair的A/候选值，端到端秒数来自Trace。统一在查询前预载同一编码器，预载耗时单列；没有预跑实际查询编码，首个编码内核、请求顺序、网络和缓存仍可能影响延迟，不能作稳定因果结论。

|配对|HTTP|输入Token|输出Token|推理Token|缓存输入Token|总Token|秒|
|---|---|---|---|---|---|---|---|
|A/B01 SQL|3/3|26013/25986|251/221|0/0|0/2944|26264/26207|14.148/18.747|
|A/C01 TS|3/3|52454/52386|845/852|266/30|2944/2944|53299/53238|27.810/33.245|
|A/C02 reply|4/4|73626/69677|774/992|141/159|0/2944|74400/70669|39.467/53.815|

三组均未减少HTTP，单次总Token较少而延迟更长；对话内容、推理与缓存不同，不将全部变化归于Prompt字符。C02并未进入最终累计候选，不能拿它的Token数据代表19854字符版本。

整个原账本**52/120**，逐目录provider-ledger求和同为52，含成功、失败、诊断、组件回归和多轮额外请求。新快照阶段发送44次；认证目录GET失败及局部phase门禁阻止时，推理HTTP为0，不虚加或漏算已发送请求。

所有阶段可确认返回Usage的40次请求合计：输入**479227**、输出**7155**、总Token **486382**、缓存输入**14720**、推理**913**。这是已知下界，包含协议诊断wire返回与Router真实Usage；另12次请求Usage未知，不能填0。Provider没有返回可用货币费用，**实际金额未知**，没有用价格表估算冒充实测。

## 7. 失败归因与停止证据

1. **原SDK tag不兼容：已修复。** 真实typed metadata正常，后续多轮工具与终态不再出现该union错误。
2. **派生索引身份/旧lexical合同：已修复。** 独立当前版本completed/integrity valid，新Case显式绑定，原件未污染。
3. **matt完整Prompt的共享投影预算失败：已精确本地复现。** 三个完成结果消耗8546+2615+4705=15866，剩134；第四次Capability已执行，最小结果envelope无法容纳，抛ToolResultProjectionError。SDK包装为UserError后，原Runtime只暴露RUNTIME_ERROR。保留原16000预算和窗口，不用扩池/重试补记成功；这是已有投影/分类可观测性缺口，非本次SSE补丁引入。本轮记录，未扩大成独立Runtime改造。
4. **实验局部phase声明不足：透明保留。** C01阶段声明8次，实际先完成6次TS+2次精确候选后，发送前阻止精确A，0HTTP。原120总门禁正常；后续新阶段改按实际变体数声明，不修改失败工件或总账。
5. **当前外部TLS阻塞。** 异常链在httpcore `start_tls`，没有HTTP状态/SSE。清空代理环境并不等于macOS直连，旧标签已更正；后续显式NO_PROXY并核验API/auth为AsyncConnectionPool，仍复现。代理隧道与直连堆栈均保留。UI、父控制与累计门禁连续被该错误中断，最后累计门禁第一请求即失败。

未认证models GET能返回401，说明短时探测可通，但不能证明真实多轮推理稳定，也不能据此编造额度不足或凭据无效。没有关闭TLS验证、切收费Provider、改用户代理/.env、自动重试或无限挑选好结果。当前仓库内的协议修复无法消除此握手阻塞，故停止新付费请求并保留68次预算。

## 8. 发布决定、交付与待续范围

**不推荐本轮发布精简Prompt；未替换生产SYSTEM_PROMPT。** P64只有一条定向职责验证，C01只有有限质量证据，P56/P57与P33未确认而恢复，UI/matt/累计与最后四条门禁未齐；原human/blind ReviewPolicy保持pending，不能用Agent复核冒充人工接受。

已交付：协议修复与回归、独立可用索引、16条不改GT的派生Case、真实A/B/C结果、失败复现、精确候选删文、预算对账和本报告。脱敏机器摘要见 `experiment/results-summary.json`；完整命令、请求、答案、工具投影、Trace、数据库、case binding和异常链保存在ignored `data/evaluation/gpt-high-ablation-20261018/`，没有提交私有群聊原文、凭据或数据库。其他人仅clone公开仓库无法完整重放私有语料实验，这一限制明确保留。

恢复稳定TLS后，从原52/120账本和现有新快照继续；先验证连接链路，再完成固定19854字符候选的高风险/累计配对及最后4条未调参Development，保留最终预算；不重置、不扩充，不重用失败Baseline。任何新增重大事实/归属/强否定退化都应拒绝对应候选。完成语义与原review_policy要求之前，生产保持20450字符。
