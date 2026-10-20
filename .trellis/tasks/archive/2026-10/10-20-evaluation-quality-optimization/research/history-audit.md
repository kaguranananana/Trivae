# Research: 历史 Evaluation 失败链路审计

- Query: 审计冻结 Development baseline 的 D context recovery 0/3、Evidence Recall 49/67、Gate 3 12 条人工 review 与本地 Trace，筛选可复现且有修复价值的候选。
- Scope: internal；只读历史产物、代码与当前 canonical 消息元数据，不执行 Provider 请求。
- Date: 2026-10-20

## Findings

### 事实源与可复现性

| 文件 | 用途 |
| --- | --- |
| `evaluation/reports/resume-benchmark-v1-fact-index.md` | 历史 baseline / Gate 3 candidate / Holdout / post-fix 之间的事实边界 |
| `docs/evaluation.md` | 生产查询复用、Reference 完整度、Trace 与答案质量的不同职责 |
| `data/evaluation/benchmark/stage3-final-real/d-records.json` | D 的 37 条历史指标 |
| `data/evaluation/benchmark/stage3-final-real/raw-records.json` | 37 Case × 5 variants 的 185 个运行标识 |
| `data/evaluation/benchmark/stage3-final-evaluation.sqlite3` | 历史 query_result、retrieval_calls、evidence_sources 与运行事实 |
| `data/evaluation/benchmark/gate3-final-development-evaluation.sqlite3` | Gate 3 candidate 运行事实 |
| `data/evaluation/benchmark/gate3-review/review.md` | 已填写的 12 条人工答案核验 |
| `data/evaluation/benchmark/gate3-review/packet.json` | 12 条抽样与旧的 pending 状态 |
| `evaluation/cases/benchmark/dev/` | Case Reference 与 required_context 的 canonical GT |
| `data/traces/` | 按 trace_id 关联的本地 Trace 文本 |

本地核验结果：stage3-final-real 对应 Trace 文件 **185/185** 存在；Gate 3 final Development 对应 Trace 文件 **185/185** 存在。两个 Evaluation SQLite 均可只读打开。这里的“存在”不代表每个字段完整。

历史 baseline 使用 473236 消息快照；当前本地 canonical 已有更大的数据集。重新跑 Development 必须声明新的 Snapshot / index identity，不能将不同数据条件下的结果直接写成同条件质量提升。历史 Holdout 不用于本次调参。

### D context recovery 0/3：三例都先丢在获取阶段

`metrics.py:358`–`metrics.py:377` 的 context_recovery 计算的是 **最终 evidence.message_ids 是否包含 GT required_context**，不是工具召回率本身。

| Case | 历史 D Evidence | 工具与参数 | GT required_context 在返回中 | projection 事实 | 当前最有证据的归因 |
| --- | --- | --- | --- | --- | --- |
| dev-context-archify | 1/2；context 0/1 | 仅 lexical_search；before=0、after=2；5 direct、8 extra context | 不在 fully recorded direct/expanded 集合；anchor 已命中 | projected=13；omitted=0 | 邻居窗口未覆盖关系回复；没有后续 context / reply 查询 |
| dev-context-mattpocock-1 | 1/2；context 0/1 | 两次 lexical_search，均 before=0、after=0；第一次 8 direct，第二次 100 direct 且只保存前 50 个 direct ID | 第一次无上下文扩展；required_context原文不含两次查询关键词（mattpocock / github.com），两次均无扩展 | projected=8、100；omitted=0 | 只找带关键词的消息，未沿目标消息获取回复；第二次 broad lexical 无法补齐关系 |
| dev-context-mattpocock-2 | 1/2；context 0/1 | 两次 lexical_search，均 before=0、after=0 | 同上；anchor 已命中，所需回复未进入 evidence | projected=8、100；omitted=0 | 关闭邻居窗口且未继续 context 获取 |

三例均没有调用 get_message_context；记录中没有 Host projection 省略消息的证据。当前 canonical 元数据进一步确认：三个 required_context 的 `reply_to_source_message_id` 都指向相应 GT anchor。按当前数据的 timestamp 严格间隔计数，三对消息之间分别有 9、143、1 条消息；这是**当前快照的辅助诊断**，不冒充历史快照的重算结果。

这个观察支持“沿明确回复关系获取讨论”的候选，不支持无限扩大邻居窗口。尤其 mattpocock-1，固定小窗口无法覆盖远距离回复。

接口边界须准确：底层 LexicalQuery 支持 source / reply 过滤（`structured.py:103`）；**公开 lexical_search 并未暴露这两个字段**（`capabilities/contracts.py:244`、`query/runtime/openai_tools.py:221`）。只有 semantic_search 的公开 SDK 参数暴露 reply 过滤（`query/runtime/openai_tools.py:373`），且其过滤作用于 dense 检索候选，不能当作穷尽回复读取。需要先验证现有公开工具能否完成关系获取，再决定最小实现；不能在报告中声称已具备确定性 lexical reply 路径。

### Evidence Recall 49/67：18 个缺失来自 13 个 Case

逐 Case 从 D records 重算缺失数量之和为 18；其余 14 个可计算 evidence recall 的 Case 全部命中 GT target，合计 27 个可计算 Case。下表数字严格复述历史 evidence 指标。

| Case | Evidence 命中 | 工具层观察 | 结论边界 |
| --- | --- | --- | --- |
| dev-cite-meimei | 1/3 | lexical + semantic；两次均投影100消息，检索ID摘要有截断 | 不能仅凭前50个ID缺席断定未召回；最终确实漏2个GT target |
| dev-cite-nanobot | 3/4 | 4个GT target均已在direct_hits观测，projection omitted=0 | 明确有一个已召回target未进入最终evidence；适合检查选据/答案覆盖 |
| dev-context-archify | 1/2 | 见上文 | 上下文获取缺失 |
| dev-context-mattpocock-1 | 1/2 | 见上文 | 上下文获取缺失 |
| dev-context-mattpocock-2 | 1/2 | 见上文 | 上下文获取缺失 |
| dev-lexical-forge | 2/3 | 3个GT target均已在direct_hits观测；17消息全投影 | 已召回但有1个未选入evidence |
| dev-lexical-mcp-switch | 1/2 | lexical、semantic、context；大调用摘要被截断 | 最终漏1个；不能从有限摘要排除深位/截断观测 |
| dev-lexical-resume-miner | 0/4 | semantic、lexical、3次context；大调用摘要被截断 | 4个target均不在最终evidence；不能只凭摘要将其全部归因召回 |
| dev-lexical-siclaw | 2/3 | 3个GT target均已在direct_hits观测；15/20消息全投影 | 已召回但有1个未选入evidence |
| dev-lexical-vibe-game | 1/3 | 2次lexical，各100消息；摘要截断 | 最终漏2个；需完整工具输出或固定重放辨别召回/选据 |
| dev-para-intern-hard-part | 0/1 | semantic；100消息、摘要截断 | 目标遗漏，不能声称全库语义召回率为0 |
| dev-para-job-anxiety | 0/1 | recent + semantic + lexical；各100消息、摘要截断 | GT为partial，只是已知目标遗漏 |
| dev-para-resume-advice | 0/1 | recent + semantic + lexical + context + semantic | GT为partial；已知目标遗漏，不能外推全部正确答案 |

明确值得作为 downstream positive control 的是 nanobot、forge、siclaw：GT target 已被检索到，但最终evidence不全。不能把这类失败继续用提高Top-K或扩大工具返回解决。另一方面，partial GT 下存在未标注但相关的正确证据，仅有 target omission 不足以判答案整体错误；人工内容判断必须独立检查。

### Gate 3 人工 Review 与 packet 不同步

`review.md` 实际填写了 12 条：2 fail、4 failed_no_answer、5 confirmed_with_notes、1 confirmed。`packet.json` 顶层仍为 pending_human_review，全部12个 item.human_review.status 仍为 pending。此处应由后续独立的 review 导入/同步工作修复，**不回写历史 Trace，不升级 Judge claims 为人工 adjudicated**。

| Case | 人工 review 状态 | 可核实的重点 |
| --- | --- | --- |
| dev-cite-meimei | confirmed_with_notes | 主事实基本正确；存在未获节选支持的附加描述 |
| dev-cite-nanobot | confirmed_with_notes | 主事实基本正确；部分引语/数字待完整来源核对 |
| dev-context-archify | fail | 把“没有找到具体反馈”写成过强结论，忽略人工节选中的简短正面反馈 |
| dev-context-mattpocock-1 | confirmed_with_notes | 漏掉一条GT上下文反应；部分群归属在节选中无法核实 |
| dev-lexical-agentic-zh | failed_no_answer | run_status failed，provider_failure，无内容块 |
| dev-lexical-nanobot-wiki | failed_no_answer | run_status failed，provider_failure，无内容块 |
| dev-para-intern-owner | fail | 忽略相反立场，把有争议的讨论压成单向结论；并有无据附加描述 |
| dev-para-job-anxiety | confirmed_with_notes | 漏已知目标；有附加描述待来源支持 |
| dev-temporal-14d | failed_no_answer | runtime completed，但 production Finalizer拒绝，INVALID_ANSWER_ARTIFACT |
| dev-temporal-2d | confirmed_with_notes | 原review的coverage解释有误，详见下文 |
| dev-zero-empty-1 | failed_no_answer | runtime completed，但 production Finalizer拒绝，INVALID_ANSWER_ARTIFACT |
| dev-zero-empty-2 | confirmed | 正确零结果对照 |

两个内容 fail 在 Gate 3 SQLite 的工具事实：

- dev-context-archify 仅调用1次lexical_search；5 direct、16 expanded；GT required_context 不在完整记录集合，最终evidence亦不包含。人工packet中的 evidence_excerpts 包含审核所需参考来源，**不能把 packet 节选当成模型已看见的内容**。根因首先是所需反馈未被工具获取，随后在有限证据上作过强否定。
- dev-para-intern-owner 调用两次semantic_search，各100 direct、expanded=0、各省略50个direct ID摘要。GT target 不在最终evidence；有限direct摘要无法判定是否曾在rank51–100返回。人工评审足以确认讨论结论失衡，但完整召回/送达边界仍需重放。

### 必须纠正的 coverage 与运行状态解释

Gate 3 dev-temporal-2d 的真实 artifact.retrieval_coverage：status=partial、eligible_units=2699、covered_units=100、has_more=true。只调用了一次get_recent_messages；只投影100条，不能宣称2699条已完整覆盖。

原人工review认为“2699未超trusted capacity，因此应补完整覆盖声明”，这与生产实际冲突。`metrics.py:387` 明确coverage指标读取Host-owned artifact；`failures.py:259` 同样比较artifact真实coverage。这里的coverage_error是**GT期望complete与实际partial的差异**，并非仅少写一句话。应区分目标时窗、工具实际覆盖、回答中的局限披露；不得为消除该指标而伪造complete。该运行同时有 limitation_preservation failure，说明partial局限未被完整保留。

dev-temporal-14d 与 dev-zero-empty-1：Evaluation terminal/run_status completed反映runtime结束，但query_result.execution_status=failed、finalization_status=failed；Trace `answer.finalization.failed` 都记录INVALID_ANSWER_ARTIFACT，error_path为空。故它们属于**最终输出合同被拒绝导致无答案**，不能统称模型没有生成文本，也不能与两个provider_failure混合。

### 可复现且有修复价值的优先候选

1. **命中anchor后获取明确回复**：3个context Case共同存在GT回复关系、anchor已命中、没有后续关系获取。先做不调用Provider的固定查询/关系诊断；再在已冻结的新Snapshot进行baseline与小范围候选对照。不能以少量样例专用窗口规则替代关系需求。
2. **已召回target未被选入最终证据**：nanobot优先，forge/siclaw作为同类复核。对齐tool返回、最终evidence、答案事实，验证是有价值的信息遗漏还是GT冗余来源；改进时同时检查可读性和无据附加描述。
3. **人工已确认的立场遗漏**：intern-owner适合检验是否在相关讨论中保留反证与争议；partial GT目标遗漏和答案失衡分别记录，禁止把目标Recall当整体答案正确性。
4. **测量解释修正**：temporal-2d只保存事实纠正与GT/覆盖条件说明；不把新增“complete”措辞当修复。packet/review状态不一致也应独立修复，不能冒充系统质量收益。
5. **system失败单独诊断**：两个INVALID_ANSWER_ARTIFACT与两个provider_failure分组；更换Provider后的改善只能解释新的运行链路，不是历史检索质量提升。

## Code Patterns

- `metrics.py:358`：Evidence Recall / Context Recovery 只比较final evidence IDs与GT IDs。
- `metrics.py:339`：未completed的运行剔除条件质量指标，保留无条件execution指标。
- `metrics.py:387`：coverage读取artifact.retrieval_coverage的Host事实。
- `failures.py:289`：context_missing的解释是required_context缺少于final evidence，不声称工具从未召回。
- `context.py:137`：bounded自动邻居扩展；direct hit占满容量时跳过邻居读取。
- `lexical.py:33`：lexical将请求before/after传入同一ContextExpander，未自动沿reply关系扩展。
- `capabilities/contracts.py:244`、`query/runtime/openai_tools.py:221`：公开lexical input无reply字段。
- `capabilities/contracts.py:355`、`query/runtime/openai_tools.py:373`：semantic input / SDK暴露source和reply过滤。
- `collector.py:63`：normal Trace单字符串截到512字符，最多16项；字段缺席不代表原始model输入缺席。

## Related Specs

- `.trellis/spec/project/engineering-principles.md`：根因优先、Failure Case驱动、生产事实与质量结论分开。
- `.trellis/spec/project/technical-decisions/stage-1-10-evaluation.md`：Case Bundle canonical truth、finding级完整度、Trace不可回写。
- `.trellis/spec/project/problems/benchmark-root-cause-closure.md`：按单次direct call保留rank；排除context-only observation，不把未观测到解释为不存在。
- `.trellis/spec/project/technical-decisions/stage-1-9-trace-observability.md`：Trace只记录运行事实与明确capture边界。

## External References

本研究不依赖外部资料；未执行网络检索、真实Provider调用或密钥读取。历史model/provider身份来自Evaluation持久化记录，不能代表当前配置。

## Caveats / Not Found

- normal Trace的model_visible_context.output通常仅512字符；不能用全文字符串搜索的缺席证明GT未送达模型。运行projection计数能证明是否发生Host省略，但不代替完整原始内容。
- retrieval_calls对大结果只记录前50个direct ID，多个大调用还有expanded摘要上限；这类Case只报告not observed within recorded depth。
- Gate 3 packet提供审核参考来源；模型未必实际看过全部packet节选，必须以run query_result/工具Trace区分。
- 当前canonical辅助验证仅持久化session/timestamp/seq/reply/source关系结论和关键词匹配布尔事实，不将私聊正文、发送者身份或完整消息定位复制到本研究。
- 本研究没有重算历史质量结论，没有修改GT、人工Review、packet、Trace或业务代码。
