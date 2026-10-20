# Research: 当前 Baseline 各层 GT 覆盖与失败归因

- Query: 对当前8条Development Baseline核验direct、expanded/context、完整Tool returned、model-visible和final Evidence；判断context失败所在层及reply/cap是否有实际因果证据。
- Scope: internal；只读本次实验私有产物与代码，不执行Provider调用，不改业务、Case或历史产物。
- Date: 2026-10-20

## Findings

### 事实源与核验方法

| 文件 | 用途 |
| --- | --- |
| `data/evaluation/quality-optimization-20261020/protocol.json` | 冻结目标、必要事实、评分与固定条件 |
| `data/evaluation/quality-optimization-20261020/cases/*.targets.json` | 原消息目标及原始reply关系；不在本报告复制正文/身份/完整定位 |
| `data/evaluation/quality-optimization-20261020/baseline/quality-*.json` | runtime_result.tool_results完整Host记录与最终AnswerArtifact |
| `data/evaluation/quality-optimization-20261020/baseline/traces/quality-*.json` | debug Trace、model_visible_context中的结构化output_projection与投影计数 |
| `data/evaluation/quality-optimization-20261020/trivae.sqlite3` | 固定canonical快照中的消息顺序/回复关系辅助核验 |

本次使用完整Host `runtime_result.tool_results[].message_items`，不依赖Evaluation摘要的前50个direct ID。`is_hit=true`只在lexical/semantic搜索调用中计为direct；get_message_context的消息不伪装成direct ranking。

model_visible_context的普通output字符串确有20000字符capture截断，但同一条function_call_output还保存**结构化output_projection.data**。逐条检查这部分没有capture limitation；按Host tool-call ordinal和message_item序号生成的source handle映射回稳定消息ID，直接检查实际可见来源。所有调用的projected_messages与Host返回数一致、omitted_messages/context/hit均为0。这里的model-visible不是从截断字符串缺席推断。

### 各层固定GT覆盖

下表前缀均为`quality-dev-`。expanded/context列是自动非hit消息与显式context消息的并集，可与direct重叠；Tool returned列为所有调用稳定消息ID的去重并集。

| Case | 固定GT | direct | expanded / context | Tool returned | model-visible | final Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| context-archify | 2 | 1 | 0 | 1 | 1 | 0 |
| context-mattpocock-1 | 2 | 1 | 0 | 1 | 1 | 1 |
| context-mattpocock-2 | 2 | 1 | 2 | 2 | 2 | 2 |
| para-intern-owner | 1 | 1 | 1 | 1 | 1 | 1 |
| lexical-resume-miner | 4 | 0 | 0 | 0 | 0 | 0 |
| para-resume-advice | 1 | 0 | 0 | 0 | 0 | 0 |
| cite-nanobot | 4 | 4 | 0 | 4 | 4 | 4 |
| cite-meimei | 3 | 3 | 0 | 3 | 3 | 3 |
| **合计** | **19** | **11** | **3** | **12** | **12** | **11** |

所有8条的运行产物已生成。该表只表达固定GT来源覆盖，不代替独立语义评审。特别是重复分享不必逐条引用才能满足必要事实；protocol已将target recall和semantic pass分开。

### 三个context Case的真实链路

**context-archify**

- 仅1次lexical_search：67个direct、完整Host返回100条，before=3、after=5、context_source_hits=20/20。
- GT anchor位于direct rank43，已返回并进入model-visible；GT required reply没有返回，因而模型也没看见。
- 当前固定快照中，所需回复在anchor后隔9条消息，即第10条；请求after5本身不足。anchor又在前20个自动扩展来源之外。
- 因此source cap和窗口共同阻止该旧GT回复；**单修cap不能令after5覆盖第10条回复**。这不是Host projection剪裁问题。
- 最终引用30条包含archify标识的来源，但没有引用这两个固定GT。完整返回中，带archify标识的消息有67条；没有任何一条返回消息的reply_to明确指向这些带标识消息。
- 其他来源是否包含充分的独立反馈、是否满足“有人实际评价”要求，交由独立语义review；不能将0/2机械判成答案整体错误，也不能仅凭引用数量判通过。

**context-mattpocock-1**

- 仅1次lexical_search：28个direct、完整Host返回100条，before=2、after=2、context_source_hits=20/20。
- GT anchor位于direct rank14，在实际自动扩展来源内；anchor已model-visible且进入final Evidence。
- required reply距离anchor很远（严格timestamp间隔中有143条消息），不在工具返回，也不在model-visible/evidence。
- 因此**此固定GT遗漏主要来自局部邻居窗口无法覆盖远距离回复**，并不是前20来源cap排除了anchor，也不是projection预算。
- 返回中有28条包含mattpocock标识的消息；存在1条明确回复这些消息的返回来源，且该回复也被最终引用。它是否足以替代旧required reply，需要结合必要事实的独立review判断；本审计不做逐句内容结论。
- metadata记录expanded_candidate_messages=100、truncated=false，同时只扩展20/28个direct来源。这是“未扩展其余来源”没有进入truncated布尔值的披露缺口；context_source_hits/budget数字已对模型可见。不能将该披露缺口直接说成此次远距离回复遗漏的根因。

**context-mattpocock-2**

- 首次lexical_search：28个direct、100条Host返回，before=3、after=3，GT anchor rank6。
- **required reply已在第一次lexical expanded消息内，两个GT都已送达模型。**后续两次get_message_context各返回18条，其中一次再次包含两个GT。
- 两个GT均进入final Evidence；此Case的历史context缺失已没有在当前Baseline复现。
- 不得把这条Case继续列作“需要修复的0/1 context失败”；它可作为关系/上下文修改后的保持性对照。

### 其余五条的层级归因

| Case | 完整调用序列与数量 | 可支持的层级判断 |
| --- | --- | --- |
| para-intern-owner | semantic100、lexical100、context29 | 固定GT已在搜索返回、模型可见与final Evidence中；若内容仍失衡，不能归因该GT未召回。具体答案语义由另一review核验 |
| lexical-resume-miner | semantic100、context28 | 4个固定GT均未在完整Host结果中；模型与最终Evidence均不含。优先检查query/tool选择或检索，不是投影裁剪 |
| para-resume-advice | semantic100、lexical100、context51、lexical100 | 固定GT未在完整Host结果中；不是仅仅前50摘要未观测到。partial Reference下仍需独立判其他来源是否足以回答 |
| cite-nanobot | lexical100、lexical100 | 4个GT均召回、可见、选入Evidence；历史3/4的选据遗漏本轮未复现 |
| cite-meimei | lexical16、lexical0、lexical39、lexical2 | 3个GT均召回、可见、选入Evidence；有一次0结果但后续实际调用已取回，不等于最终失败 |

### reply元数据丢失：存在，但尚不能当作已证明的坏答案根因

完整Host message保存`reply_to_source_message_id`。`query/evidence.py:1758`的slim message projection对普通消息保留source handle、时间、author、正文、session、类型、urls、hit等，但没有投影reply_to_source_message_id，也没有将reply target映射成可见source handle。因此模型可能看见简短回复正文而缺少机器可读的回复对象。

这是一项真实的信息丢失，但本轮因果边界如下：

- archify及mattpocock-1的旧GT required reply在**工具返回前**已经缺失，给projection增加reply字段不会使未返回消息出现。
- mattpocock-2的required reply已可见并被选入Evidence，即使reply字段缺失，这条固定GT链路仍成功，不能声称字段缺失必然导致该类失败。
- mattpocock-1实际引用了其他明确回复相关标识消息的来源。它与必要事实的语义关系是否被回答正确理解，仍需独立review或固定对照验证。
- 因而reply投影可作为有事实依据的候选，但不能在没有隔离验证前宣称它是当前坏答案的已证实根因或预计收益。

### source cap标记：有局部披露缺口，没有统一失败因果

当前source cap=20是固定现有行为，模型实际能看见metadata.details.context_source_hits与context_source_budget。没有“完全隐藏cap”的证据。

- archify anchor在cap之外，但现有after5也不足；cap单点修复不能覆盖旧GT。
- mattpocock-1 anchor在cap之内，回复太远；cap不是该目标遗漏的原因。
- mattpocock-2 anchor在cap之内且reply成功返回/引用。

因此，若要把cap披露改动列作质量实验，必须独立证明它改变了Agent后续有用的补查并改善坏答案。单纯新增truncated=true可提高事实表达，但不自动提高Evidence覆盖，也不能与关系获取的改动混为一个可归因结论。

## Code Patterns

- `query/runtime/openai_tools.py:519`：先构建完整canonical ToolResultRecord，再独立生成model projection；Host record用于Evidence provenance。
- `query/runtime/openai_tools.py:556`：完整record与projection统计分别持久化。
- `query/evidence.py:1217`：tool ordinal决定短scope；`query/evidence.py:1230`按message序号确定source handle，支持本审计无猜测回映。
- `query/evidence.py:1758`：普通slim message不携带reply关系；正文仍可含导出文本中的回复标记，不能代替明确target关联。
- `query/evidence.py:2005`：projected/omitted消息数从真正可见source handles计算。
- `retrieval/context.py:160`：仅前20个direct来源自动扩展；`retrieval/context.py:212`在扩展集合未超result limit时返回truncated=false，不单独标明source cap遗漏。
- `retrieval/context.py:223`：超限时先保留全部hit，再按确定性顺序填context；本轮三个context工具返回以后均没有再次Host projection丢弃。

## Related Specs

- `.trellis/spec/project/engineering-principles.md`：根因优先、不能将潜在信息丢失自动上升为已证明的质量根因。
- `.trellis/spec/project/technical-decisions/stage-1-10-evaluation.md`：finding级完整度；target coverage与整体答案质量分开。
- `docs/evaluation.md`：完整Trace/生产查询事实支持层级归因，partial Reference不支持全库召回结论。
- 本任务`design.md`与实验`protocol.json`：固定GT、必要事实、model-visible层分开；其他重复相关证据可满足语义要求。

## External References

无。本轮审计不执行Provider、网络或Judge调用。

## Caveats / Not Found

- expanded/context列与direct有重叠，不能简单相加当作Tool returned。
- model-visible来源判定直接使用完整结构化output_projection.data，不依赖普通output字符串；后者仍有capture截断，不能拿它做负证据。
- model projection中部分长消息正文可受既有600字符excerpt限制；来源可见不代表原始长正文全部可见。具体必要事实是否仍完整需语义review。
- 本报告不输出私聊正文、发送者身份或完整消息ID；保留8个固定Case ID和脱敏计数。
- 本轮只负责层级审计；语义pass/fail、新数据替代反馈是否充分由独立review负责，human applicability仍按protocol保持pending。
