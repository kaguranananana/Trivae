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

真实运行、Claim核验、Usage与成本结果将在本节追加；失败也记入同一累计账本。开始时余DeepSeek128 / Judge6，没有初始化新额度。

## 复现入口与材料保留

私有输出：本机 ignored `data/evaluation/budget-capacity-20261031/`，包括完整投影、canonical来源映射、计划pickle、请求正文、失败和usage。原冻结库、Trace、旧评分、旧预算文件内容在本轮开始前均保留。账本沿用 `research/agent-quality-20261029/budget.json` 与 `LEDGER.md`，新扣减继续该序列。

```sh
uv run python research/budget-capacity-20261031/offline.py --output-dir data/evaluation/<new>/offline
uv run python research/budget-capacity-20261031/replay_r7.py --output-dir data/evaluation/<new>/r7
uv run python research/budget-capacity-20261031/controlled_answers.py prepare --envelopes data/evaluation/<new>/offline/semantic-envelopes.pickle --capacity 200 --cases cap1-08-kimi-deepseek cap1-10-mobile cap1-12-agent-tools --output data/evaluation/<new>/plan
uv run python research/budget-capacity-20261031/controlled_answers.py run --plan data/evaluation/<new>/plan/plans.pickle --pool 32000 --output data/evaluation/<new>/answers-32 --dry-run
```

真实运行需去掉`--dry-run`，会扣同一累计额度；使用新输出目录。协议重放的合成fixture不是质量结果。所有研究和脚本只留实验分支；main仅保留产品修复与简短事实摘要。
