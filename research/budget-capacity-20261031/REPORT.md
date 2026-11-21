# 消息容量与工具预算实验（2026-10-31）

本轮基于 main 的 R2/R6 产品合入 `ce553277`、状态记录 `8b684599`，实验代码与结果留在 `codex/budget-capacity-20261031`。没有改产品默认预算、模型注册表、ANN、索引、Prompt 或评分，也没有将 R7 Prompt 合入。

## 真实配置核查

- 普通查询受跟踪默认是 ChatGPT OAuth `gpt-6.1-sol`；注册容量 500,000（来源为既有账号模型目录记录）。Evaluation 是官方 DeepSeek `deepseek-flash`，本机加载后的 endpoint 为 `https://api.deepseek.com`、API key profile；不展示凭据。
- 2026-10-31 核对 [DeepSeek 官方说明](https://api-docs.deepseek.com/quick_start/pricing/)：该 alias 指向 DeepSeek-V4.1-Flash-1017，1M context、支持 OpenAI 格式接口。当前精确 provider/model 已在项目能力注册表登记 1,000,000；显式 context 覆盖优先。此次核验没有发送 1M 长度探针，不主张实测极限容量。
- 历史实验显式 context=128,000，shared pool=32,000。单次 ceiling=min(context×50%,128,000)，shared 默认=min(context×25%,256,000)。显式 shared override 优先，不会随 context 自动校正。未知 context 的现有边界为 16,000；fixed 是独立调试模式。
- 无环境覆盖时 GPT Plus 为 125,000 shared / 128,000 per-call，DeepSeek 为 250,000 shared / 128,000 per-call。当前本机 `.env` 显式 shared=200,000，query/agent 都会继承；本轮不编辑它。32K 不是当前产品统一默认。
- 当前语义展开 100 来自 ContextExpander 共用 structured transport 常量。实验仅为 SemanticRetrieval 增加独立 `expansion_message_limit`（默认仍100），其他 Capability 不扩容。
- 独立硬限制仍包括 semantic Top-K≤20、候选池≤1000、展开≤Top-K×32、邻居锚点≤20、child默认≤10消息/480字符、普通模型摘录600字符、canonical excerpt1000字符、显式原文页8000字符、ToolRecord消息≤5000、structured/member/SQL约100、get_message_context总窗口≤100；max tool rounds=6、max turns=8、API Runtime输出16,384、Router/Planner输出2,048；Finalizer还有40 claim / 20 evidence / 每evidence20 sources / 总答案20,000字符等限制。更大的 Token 池不会消除这些边界。

## A：固定51个ANN池，100 / 200 / 500

使用原冻结库只读连接、保存的候选与距离/排名，查询、scope、Top-K、chunk完全固定。各组断言选中chunk相等、100消息集合是扩容集合子集、时间顺序不变。GT前缀纠错仅记在新输出，不改历史。

|消息容量|返回消息合计|核心/邻居|已知GT出现/唯一GT|Envelope字节合计|
|---|---:|---:|---:|---:|
|100|5017|4792 / 225|18 / 8|7,116,763|
|200|8186|6770 / 1416|19 / 9|9,355,306|
|500|8938|6770 / 2168|19 / 9|9,861,704|

200只新增一次已知GT（Case11的转发消息）。500未增加核心证据，主要多出752邻居。此池实际最大返回318，Top-K×32与已选chunk限制仍在。全部调用仍有truncated标记，不能解释成扩大容量消除了全部边界。没有人工相关性标签；核心/邻居是额外噪声的代理，不能把“非GT”直接等同于不相关。

离线计时含只读缓存与组执行顺序，不能据此宣称大容量更快。最初无缓存尝试在9调用后主动中断，目录与中断说明保留；正式重放缓存完全相同的冻结range读取，无模型请求。

## B：固定Envelope，独立扩共享预算

所有组使用1M context、128K per-call ceiling，只改shared override。51调用按其历史“此前消耗/控制预留”条件重放；这是条件Host实验，不能视为完整Run的反事实（此前调用在较大预算下也可能多消耗）。Semantic容量固定100。

|共享池|目标可见出现|投影错误|可见消息|省略核心/邻居|截断调用|估算结果Token合计|
|---|---:|---:|---:|---:|---:|---:|
|32K|14|3|4428|226 / 63|12|761,902|
|64K|18|0|4999|0 / 18|1|884,655|
|128K|18|0|5017|0 / 0|0|893,556|

32K组3失败没有被当作零命中。汇总分母不同（32K仅48可投影），总Token不能直接作为单次Run成本。保存的单个R6 Envelope在32/64/128K下分别返回80/100/100，估算10,742/13,022/13,022；原已保留目标仍可见，扩容补回其余20条。

R7首批在32K下精确重建23,298+8,111=31,409，余591；64K第二份不再截断，首批后余29,720；128K余93,719。失败第二批工具数组没有落盘，因此另外明确声明3/4/7调用准入探针：32K分别需597/796/1393而失败，64/128K全部准入。这里只解除已知边界，未重跑被否定的R7 Prompt，也未证明整Run成功。

64K已补回所选样本中的目标与全部核心，128K仅补18邻居；没有继续250K的证据，本轮不运行250K。

## C：预先选择的受控真实答案对照

预注册选择 Case08（具名比较）、10（跨时间实践整合）、12（近期工具与归因；未参与R2/R6优化）。两组语义容量固定200，context固定1M、单次128K，只比较shared32/64K。使用同一历史B0查询/规范化canonical工具请求，全部消息来自同一冻结库，semantic复用A池；脚本重放工具序列，再由正式DeepSeek模型执行最后一次合成，经过正式Runtime与Finalizer。产品SYSTEM_PROMPT不变；两组采用相同固定工具轮数与无工具最终合成。

这是控制检索随机性的Agent合成实验，不能用于估计自由检索Agent整体完成率。原Trace中被预算阻止的显式上下文调用按已知source恢复精确canonical请求，并在新plan登记，不修改旧数据。检索脚本回合不消耗HTTP，但SDK usage.requests仍会计模型回合；真实请求数必须看HTTP账本。

零请求协议重放已确认：32K的Case10在下一批控制准入时显式失败，64K三个Case均能抵达最终合成。此失败保留，不补跑旧槽。

开始时余DeepSeek128 / Judge6，没有初始化新额度。实际实验夹具、使用量核对代码固定于`07f7a485`；首次运行时为`debf20e2`加该夹具修正，完整出站请求与实际参数均保存，复现以固定后的源码和保存输入为准。

初次真实夹具出现5次HTTP400，另一次原请求诊断也返回400：脚本工具回合没有生成reasoning，但DeepSeek要求assistant工具消息携带`reasoning_content`。新实验夹具为这些明确的脚本回合发送空字段，不编造推理、不修改真实Provider回合；单题成功后才继续矩阵。旧失败目录保留，不回填为成功、不将其计作预算方案质量失败。所有6次均扣额度、Usage未知。产品代码无此更改。

|共享池 / Case|正式交付|最终可见已知GT ID|真实输入/输出Token|受控合成秒数|按当日价目估算USD|
|---|---|---|---:|---:|---:|
|32K / 08|成功|1/2|44,108 / 3,246|19.04|0.00775|
|64K / 08|JSON失败|1/2|62,242 / 5,242|28.96|0.01167|
|32K / 10|控制准入失败|未调用真实合成|未发出|0.08（仅脚本）|无合成请求|
|64K / 10|成功|0/3|72,846 / 2,589|16.87|0.01165|
|32K / 12|成功|0/4|42,229 / 2,743|16.25|0.00651|
|64K / 12|成功|0/4|76,542 / 3,415|19.58|0.01270|

32/64K均交付2/3。64K的08正文在位置1073含未转义引号，Python标准JSON解析器与正式Finalizer一致拒绝；没有修补JSON、宽松解析或补跑该槽。更多输入没有保证有效交付。这些是固定工具前缀后的合成结果，不是自由检索Agent准确率。

08可见消息275→426、12可见消息231→457，但两题的已知GT覆盖均未增加；10三个已知目标仍未进输入。已知GT并非穷尽参考，不能据此把其他有效答案判零分。64K的12能引用当周Codex/zcode等具体反馈，32K主要依赖更早的讨论；这支持局部内容改善，同时两者都没有补回参考中的Magpie/OpenCode/Pi/Claude桌面目标，频率/群体归纳仍有问题。10虽恢复交付，仍遗漏微信远程Codex与T3 Code等参考事实。32K的08漏掉免费版/排队经验。

已完成6项Codex原文抽查（非独立人工裁决）：32K/08把DeepSeek harness与Claude Code的比较用来回答Kimi比较、把涉及2.6/2.7的模型评价误归为公司面试；64K/10正确保留VPS/Paseo为“计划”，但“官方方案比远程桌面更顺手”缺少直接对照支持；64K/12的一人返回DSH有原文支持，“Codex最多、其他其次”没有频次清单支持。32K/08的harness消息在实际输入中只剩32字，截掉了Claude Code部分；64K已保留完整段落，不能把32K所有归因错误都归为“看到了完整证据仍用错”。完整原文、实际输入和审查理由保存在私有`claim-audit.json`与Judge输入；仍需独立人工复核。

### Judge完成情况与质量边界

沿用OAuth GPT Plus与原v2.1 rubric。32K/08完成一份Review，task=3 / reliability=2，诊断为比较对象错配、公司/模型归因错误、无统计支持的频率外推；原文核验支持这些具体诊断。第二个Judge POST发生ConnectError（已扣额度，Usage未知）。只读连通性一度恢复后，显式继续未完成评审，但在OAuth模型目录GET阶段再次AUTH_NETWORK失败，尚未发送新的评审POST，不扣新的推理额度。两次错误均保存，未换Provider、未调大请求限额、未给其他三份答案编造评分；准备好的审阅输入可供以后恢复。

因此不能汇总Judge均分或声称通过独立人工审定。现有质量结论仅来自4份正式答案、2个明确交付失败、1份provisional模型Review及6项Codex原文抽查。

## Token估算、成本和预算耗尽

5次真实合成共297,967输入、17,235输出，315,202总Token（含未交付的非法JSON）。捕获完整出站messages按UTF8字节/3估算后，真实input/估算范围0.955～1.017；这5个中文大输入中偏差约-4.5%～+1.7%。它与“仅工具结果预算”的数值不是同一个指标：system、用户历史、工具调用与协议开销也占上下文。不能由此证明所有语言或所有小输入的估算都准确。旧Q5用被截断Trace和输出结构倍数推估的1.31中位数不是精确输入tokenizer校准，本轮不据它修改估算常量。

最大实测输入76,542，加输出3,415远低于两组共同的已登记1M窗口；每个实际出站请求另检查完整序列化字节及16,384输出预留。没有通过改变context让64K看起来更好，也没有实测1M边缘。

按官方当日周六off-peak价格（每百万token，未缓存输入$0.15、缓存$0.003、输出$0.6）和真实cached Usage估算，5次合成约$0.05029；这不是账单实扣。6次400没有返回Usage，不能编造零Token或精确费用。OAuth Judge不换付费API，订阅费用不能从Token反推为可核实增量账单。

R7头部扩容释放了空间，但Q6仍值得修。64K/12真实工具结果估算共63,744、仅余256；用正式预算策略声明一个额外双调用批次需要398而拒绝。该探针不是模型真的选择了下一批，但证明任何有限池仍有相同边界。应研究在模型选出不可准入批次前进入合法最终合成，而不是靠无限扩容或把预算失败伪装成no_result。

## 决策

- 后续受控研究优先用**消息200 / shared64K / per-call128K / 已核实1M context**；64K补回离线核心证据且解除两个已知控制边界，200只多保留一个已知目标，收益有限。
- **产品默认保持不变**：semantic100、动态25%共享预算及既有上限；本机200K覆盖也不编辑。当前生产预算本就不是32K，不能据这次历史32K对照去把生产改为64K。未证明最终答案总体提升，也未证明500/128K/250K值得采用。
- 已确认的是保留改善、具体预算边界及这5次Usage/延迟；答案质量收益、自由检索完成率、真实1M极限、成本/延迟在更多样本上的稳定性仍未验证。
- 下一项最有价值的问题是**Claim如何保留比较对象、任务条件和个人观点范围**；同时将本次完整非法JSON另存为生成协议Failure，不能声称增加预算解决了它。

## 复现入口与材料保留

私有输出：本机 ignored `data/evaluation/budget-capacity-20261031/`，包括完整投影、canonical来源映射、计划pickle、请求正文、失败和usage。原冻结库、Trace、旧评分、旧预算文件内容在本轮开始前均保留。账本沿用 `research/agent-quality-20261029/budget.json` 与 `LEDGER.md`，新扣减继续该序列。

```sh
uv run python research/budget-capacity-20261031/offline.py --output-dir data/evaluation/<new>/offline
uv run python research/budget-capacity-20261031/replay_r7.py --output-dir data/evaluation/<new>/r7
uv run python research/budget-capacity-20261031/controlled_answers.py prepare --envelopes data/evaluation/<new>/offline/semantic-envelopes.pickle --capacity 200 --cases cap1-08-kimi-deepseek cap1-10-mobile cap1-12-agent-tools --output data/evaluation/<new>/plan
uv run python research/budget-capacity-20261031/controlled_answers.py run --plan data/evaluation/<new>/plan/plans.pickle --pool 32000 --output data/evaluation/<new>/answers-32 --dry-run
```

真实运行需去掉`--dry-run`，会扣同一累计额度；使用新输出目录。协议重放的合成fixture不是质量结果。所有研究和脚本只留实验分支；main仅保留产品修复与简短事实摘要。


## 收尾与验证

- DeepSeek新增11次推理HTTP尝试：6次实验夹具/诊断400，5次正式合成；累计133/250，剩117。Judge新增2次推理HTTP尝试：1成功、1ConnectError；累计28/32，剩4。恢复评审的模型目录GET失败独立记录，不冒充推理POST。新HTTP、Usage、161条累计账本及余额一致，旧148条账本前缀逐字未变。
- 私有新输出保留所有失败、标准JSON错误定位、Claim审阅材料和请求正文。成功APFS库按生命周期回收；初次准备失败的本任务工作库`run-29fisd_l`在保存失败清单与修正后plan/结果后，通过EvaluationWorkspace标记持久化再回收。没有清理其他工作区、历史实验、master、原Trace或个人文件。
- 研究分支完整测试1402 passed / 1 skipped（39.42s），相关50 passed；Ruff、Mypy148、diff检查通过。main最终再次完整验证1395 passed / 1 skipped（37.82s），Ruff与Mypy148通过；文档摘要及验证记录已推送main。

- 原研究分支也已同步117/4累计账本，避免从旧分支的128/6历史余额继续请求；没有修改其他工作区。独立实验分支保留全部复现代码，main不跟踪research目录。
