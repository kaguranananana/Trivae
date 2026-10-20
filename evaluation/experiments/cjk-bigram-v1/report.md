# Trivae CJK bigram v2 检索对照实验

执行日期：2026-10-20。结论：**大幅改善穷举字面覆盖，但前十排序并非全面改善，存在混排误匹配、单字缺失及性能开销；没有稳定 Agent 质量提升的证据。**

## 实验身份与审计

生产检索代码基于 `201a81b`。实验期间生产 tokenizer、索引算法、Agent Prompt 均未修改。唯一 `src` 改动为 Evaluation Snapshot 的结构化身份长度修复；冻结前复现并测试，提交身份见该目录关联的 Git 提交。执行时实验脚本位于工作树，随后提交，不能称为 clean-worktree execution。

- Snapshot：809,850 canonical + 13,985 forwarded occurrences = **823,835** indexed documents；12 sessions、80 sources、canonical revision 44070。时间范围 1753011800000–1792418450000 ms。仍有 217 个未展开转发节点；穷举只涵盖快照内可恢复正文。
- 环境：SQLite 3.50.4，Python 3.12.13，macOS-26.6.2-arm64-arm-64bit。索引复制自同一只读备份，生产库未重建或写入。
- A：原文 FTS5 unicode61；B：现有 `normalize_lexical_index_text` 与查询同源函数。schema、行顺序、SQLite 配置、Scope、limit=10、BM25 和稳定 tie-break 一致。
- 查询用生产 `_lexical_match_union`，多空白 term 为 literal AND；每个归一化 term 为 quoted phrase。实验只替换 A 的 MATCH 文本，不改 Scope SQL。实验FTS的source_message_id为NULL（UNINDEXED）；该列不参与匹配或BM25，正式来源均从Canonical恢复。
- 普通正文及 forward own-text 复用生产函数；转发 occurrence 保留 root/path 独立身份，按外层 timestamp 过滤，结果从 canonical root JSON 回读。preview 不进入正文。实验 B **64/64 count+top10 与生产一致**；Agent adapter 两侧另有 128 arm/case 检查及两组 session+时间 Scope parity；合成转发端到端测试覆盖 preview、Scope、恢复与 A 的真实无 metadata 身份。
- 生产 guard 检查 strategy、forward projection version、canonical revision/count、FTS 与 forwarded 总数；A 始终是实验库，没有伪造 v2 metadata，也没有旧策略生产入口。

历史记录 `temporal-browsing-cjk-lexical-recall.md` 和归档任务保留了 473,236 消息时的 `推荐` 0→157→187、全库 1596=LIKE、约 8.7–9.0 秒重建。已从历史原Trace恢复0命中的实际条件：trusted Scope为单会话，archive_latest前2天，时间区间[1786671390000,1786844190001)，limit=30、context=2/2、coverage=complete。记录中的初次诊断窗口14条与后续smoke的157/187条，仍缺少后两次完整原请求参数来核实是否同一过滤条件，不能仅凭文字将三者合并。旧 Trace/文字记录可以说明历史失败与修复过程，**不计入此次分子分母，也不宣称重跑了历史实验**。历史 resume-benchmark 的 lexical/semantic、Provider、sealed Holdout 同样不改写。

## Benchmark 与 Oracle 修订

64 条固定查询：短词20、连续中文12、中英混排12、英文/URL/代码控制12、不存在词4、单字4。57条有相关消息，7条空 Reference（4条不存在词及3条控制词）。短/长词人工选取真实主题和历史 failure；混排从原文扫描发现后选择技术/求职语汇，排除昵称等系统噪声。控制词保留无命中的 ImportError、HTTP 500、get_message_context，没有看 A/B 输出后换题。不是随机线上 Query 分布，也不是 fresh holdout。

首次按转义 LIKE 冻结 Reference 后发现原文 NUL：`LIKE '%模型%'` 对 `前文\0后文模型` 返回0，而 FTS会搜索后段。首版输入/结果完整保留，标为 Oracle-invalid；新建 `oracle-v2`，用 **`instr(lower(content_text), lower(term)) > 0`** 枚举完整文本。8个查询的 Reference 合计增加19个 query-message pairs，Query/Scope/limit/排序改变0；修正记录见 [oracle-correction.json](oracle-correction.json)。修正版 Reference 冻结后，复用完全相同 A/B索引重新查询及生产 parity，未选题或修改算法。 headline 仅使用修正版评分。

Reference 是 ASCII 大小写不敏感的完整字面子串，不是语义相关性；没有人工审核，**human_verified=false**。不存在同义词/语义问题的全库 GT。`HTTP 500` 的生产空白 AND 与整串子串 Oracle 不同；混排空格/标点等价也是 tokenizer 契约差异，不自动判成语义无关。分母是 query-message pairs，跨 Query 的同一消息可重复计数。完整参考与排名身份仅保存在被 Git 忽略的本地目录。

## 总体指标（57 个正例 Query；7 个空例单列）

Recall@10 = 前十相关数 / 全部字面相关数；Hit@10 = 前十至少一条相关；MRR@10 = 首条相关的倒数排名。空 GT 不计入这些分母。macro 按 Query 平均，micro 按相关消息聚合；Hit/MRR 的 micro 与 macro 等价。全深度覆盖枚举全部 FTS hits，不受结果10条截断；**不是应用已向用户返回全部消息**。

| 指标 | A unicode61 | B bigram v2 | 绝对提升 | 相对提升 | 实际分子/分母（A → B） |
|---|---:|---:|---:|---:|---|
| Recall@10 macro | 9.772% | 13.254% | +3.482 pp | +35.63% | Σ比率 5.570062/57 → 7.554725/57 |
| Recall@10 micro | 0.311% | 0.345% | +0.034 pp | +10.89% | 459/147362 → 509/147362 |
| Hit@10 macro | 94.737% | 98.246% | +3.509 pp | +3.70% | Σ比率 54.000000/57 → 56.000000/57 |
| MRR@10 macro | 94.737% | 96.491% | +1.754 pp | +1.85% | Σ比率 54.000000/57 → 55.000000/57 |
| 全深度字面覆盖 macro | 25.634% | 92.388% | +66.755 pp | +260.42% | Σ比率 14.611247/57 → 52.661334/57 |
| 全深度字面覆盖 micro | 6.234% | 69.411% | +63.177 pp | +1013.38% | 9187/147362 → 102286/147362 |

真实 Hit 为54/57→56/57，MRR倒数排名和54/57→55/57。总体返回项字面 Precision@10（sum TP / sum actual returned，少于10不补齐）为 **459/461=99.566% → 509/519=98.073%**（−1.493 pp，相对−1.50%）；不是人工语义 Precision。全深度字面误匹配2→341（+339），其中339来自混排。空例正确无结果6/7→6/7；四条预设不存在词两侧均4/4。HTTP 500两侧均有2条 AND命中、没有整串字面命中。

## 主要中文范围与分类

44条中文/混排查询：全深度 micro覆盖 **2,853/89,346=3.193% → 89,340/89,346=99.993%**，绝对+96.800 pp，相对+3031.44%；macro为21.819%→99.777%。Recall@10 macro **10.166%→14.676%**（+4.510 pp，+44.36%），micro **360/89,346→407/89,346**（0.403%→0.456%，+0.053 pp，+13.06%）。Hit@10 **42/44→44/44**（+4.545 pp，+4.76%）；MRR@10 **42/44→43/44**（+2.273 pp，+2.38%）。

32条纯中文查询（不含混排/单字）：全深度 **2,454/87,671=2.799% → 87,671/87,671=100%**；macro12.979%→100%。仅支持本次可穷举字面范围。20条短词的前十相关数两侧都是200：高频词已有10条命中时，扩大覆盖不会自动增加Recall@10；`推荐` 本次283→2485=Reference2485，并不等于Agent准确率从11%升到100%。

| 分类 | Query/正例n | Recall@10 macro A→B | Hit@10 A→B | MRR@10 A→B | 全深度 TP/Reference A→B | 漏召回 pairs A→B |
|---|---:|---:|---:|---:|---|---:|
| short | 20/20 | 0.360% → 0.360% | 100.000% → 100.000% | 100.000% → 100.000% | 2170/86273 → 86273/86273 | 84103 → 0 |
| long | 12/12 | 21.540% → 36.158% | 100.000% → 100.000% | 100.000% → 100.000% | 284/1398 → 1398/1398 | 1114 → 0 |
| mixed | 12/12 | 15.136% → 17.053% | 83.333% → 100.000% | 83.333% → 91.667% | 399/1675 → 1669/1675 | 1276 → 6 |
| control | 12/9 | 12.179% → 12.179% | 100.000% → 100.000% | 100.000% → 100.000% | 6324/13313 → 12926/13313 | 6989 → 387 |
| absent | 4/0 | 不适用 → 不适用 | 不适用 → 不适用 | 不适用 → 不适用 | 0/0 → 0/0 | 0 → 0 |
| single | 4/4 | 0.023% → 0.031% | 75.000% → 75.000% | 75.000% → 75.000% | 10/44703 → 20/44703 | 44693 → 44683 |

分类完整 macro/micro、每个 Query 的 metrics/分母见 [oracle-v2-summary.json](oracle-v2-summary.json)；上表全深度漏召回比例可按遗漏数/Reference复核。无相对分母时不声称无限提升。


### 分类增幅与遗漏比例

| 分类 | 漏召回比例 A→B | Recall@10 macro 绝对/相对 | Hit@10 绝对/相对 | MRR@10 绝对/相对 | 全深度micro 绝对/相对 |
|---|---:|---:|---:|---:|---:|
| short | 97.485%→0.000% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +97.485 pp / +3875.71% |
| long | 79.685%→0.000% | +14.619 pp / +67.87% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +79.685 pp / +392.25% |
| mixed | 76.179%→0.358% | +1.918 pp / +12.67% | +16.667 pp / +20.00% | +8.333 pp / +10.00% | +75.821 pp / +318.30% |
| control | 52.498%→2.907% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +49.591 pp / +104.40% |
| absent | 不适用 | 不适用 | 不适用 | 不适用 | 不适用 |
| single | 99.978%→99.955% | +0.008 pp / +34.41% | +0.000 pp / +0.00% | +0.000 pp / +0.00% | +0.022 pp / +100.00% |

## 失败、排序退化与边界

- A=0、B有前十相关：`大模型infra`（0→122 hits，10条前十相关）、`字节hr`（0→101 hits，8条前十字面相关；Reference82）。零基线不计算相对提升。
- 三条 top10退化：ai应用开发 10→9; AI算法 10→8; agent开发 10→9。混排 MRR 从10/12→11/12总体改善，但不能掩盖具体排名退化。所有A的全深度hits都保留在B内；退化来自新召回项和排名截断，不是原有候选被删除。
- B中混排全深度仍漏6条：`华为ODDO`（1条）、`字节hrbp`（1条）、`aagent开发`/`mdagent开发`（2条）、`caludecode源码`/`opencode源码`（2条）的 ASCII前后缀仍受 exact token边界限制。其余339个额外mixed命中主要来自“AI 应用”“AI/算法”“字节 hr”“agent 开发”等分隔写法；对完整字面串是FP，对语义问题可能有用，当前没有人工标注去断言。
- 单字4条：仅 **10/44,703 → 20/44,703** 全深度覆盖；`荐`两侧0/2504。bigram不包含内部unigram，B并未解决单字子串查询。
- ASCII控制的前十指标不退化；全深度coverage上升，但`GitHubeducation`、`GithubPages`、`JavaScript`等词内子串仍不被 exact token覆盖。非Han字符没有被改写不意味着混排文档的分词边界完全不变。
- NUL假FP已通过独立Oracle修订排除；未为此改生产算法。217未展开forward节点不作为已知正文补齐；Reference只对可恢复内容穷举。

所有64条的Query/Scope/Reference、FP/FN IDs及真实正文样例位于本地 `oracle-v2/failure-cases.json`。确定性回归覆盖NUL Oracle、混排分隔符FP、空GT分母、生产keyword/AND、forward Scope与恢复。没有把已知限制用fallback或新策略掩盖。

## 性能与空间代价

同样823,835条投影输入，A/B的FTS插入+commit分别 **1.839s / 4.842s**，B增加163.4%；一次构建，未估计方差。独立FTS文件 **130,686,976 / 179,273,728 bytes**（124.63/170.97 MiB），B增加37.18%。共享canonical/forward投影准备成本不计入双方FTS差值；首轮完整生产rebuild计时因manifest构造失败未保存，明确 unavailable。

Agent与测试结束后单独延迟复测：64 Query×5 warm repetitions=320样本/侧，逐题交替A/B。count+top10 SQL中位数 **0.223→3.158 ms**，P95 **10.427→66.517 ms**。这是SQL核心耗时，排除了readiness全表校验、Canonical正文恢复、自动上下文和Provider；不能当作完整工具/线上SLA。频繁词更多匹配增加count/sort代价。此前两轮时序也保留；Oracle-v2重跑与Agent并发，故质量结果可用，headline延迟取独立结束后复测，而非挑选较低值。[latency-final.json](latency-final.json)包含每次原始样本。

## DeepSeek Flash 真实 Agent（独立于离线指标）

官方 `deepseek/deepseek-flash`，`https://api.deepseek.com`，显式读取本地.env并校验密钥存在，未覆盖/记录密钥。复用真实 `TrivaeApplication.query()` 和 EvaluationRunner/SQLiteEvaluationStore；两侧同一代码、Prompt、标准路径override、工具surface（lexical_search/get_message_context）、result scope=10、context=0、现有轮次预算。只注入已通过parity的实验lexical reader；不覆写生产readiness，不伪造strategy。两侧canonical/forward恢复一致。

这是lexical-only受控Agent，不是默认全工具Agent。每题一次；8题中的GitHub A在计数异常检查时主动中断，不重试，不剔除。最终15条returned runs（10 completed、1 completed_degraded、4 failed）+1 aborted；7完整配对中两侧各5/7成功，没有completion uplift。5条可回答正例中，最终Evidence至少包含原始完整关键词为A **4/5**、B **5/5**；每题最多3条必要字面证据的配额为12/15→15/15。这只证明本次Evidence命中，不等于答案事实正确率，不能由1个case推导稳定E2E提升。

| Case | A（direct相关；final相关/引用来源；调用/Token/时间） | B |
|---|---|---|
| cjk-01 推荐 | completed; direct=10; final=5/5; 2 calls / 15825 tokens / 11.8s | completed; direct=10; final=5/5; 2 calls / 15839 tokens / 7.4s |
| cjk-21 人工智能 | completed; direct=3; final=3/3; 2 calls / 15079 tokens / 4.8s | completed; direct=3; final=3/3; 2 calls / 14850 tokens / 7.1s |
| cjk-33 ai应用开发 | completed; direct=10; final=3/3; 2 calls / 15667 tokens / 3.7s | completed; direct=9; final=6/7; 2 calls / 15765 tokens / 5.6s |
| cjk-34 大模型infra | completed_degraded; direct=0; final=0/3; 3 calls / 25106 tokens / 8.2s | completed; direct=10; final=4/4; 2 calls / 17606 tokens / 6.3s |
| cjk-45 GitHub | 主动中断；不评分 | completed; direct=10; final=3/3; 2 calls / 15817 tokens / 21.4s |
| cjk-46 Python | completed; direct=3; final=3/3; 2 calls / 14488 tokens / 17.2s | completed; direct=3; final=3/3; 2 calls / 14435 tokens / 9.0s |
| cjk-57 不存在的量子香蕉数据库 | failed; direct=0; final=0/0; 2 calls / 14039 tokens / 6.9s | failed; direct=0; final=0/0; 2 calls / 13825 tokens / 6.6s |
| cjk-61 荐 | failed; direct=0; final=0/0; 2 calls / 13927 tokens / 5.8s | failed; direct=0; final=0/0; 2 calls / 14130 tokens / 6.6s |

- 所有引用来源都能从Canonical恢复；来源存在/字面相关不等于每句话得到正确支持。AI诊断看到B把“人工智能”说成“三个字”（实际4字），`ai应用开发`的回答用“最早/最具代表性”概括BM25候选，且把276个FTS hits称为完整字面串数量（Reference249）。保留为答案/表述失败，不标human_verified，不给语义citation correctness率。
- `大模型infra`的A改查infra后交付degraded答案，但最终来源0/3含原始完整词；B有4/4含原词的来源。该差异与离线token漏召回相符，单次运行不足证明稳定收益。
- 不存在词A/B及`荐`A/B均在finalization被 `INVALID_FINAL_OUTPUT`拒绝。Trace错误为 `zero-result final answer lacks verified complete-and-empty retrieval evidence`；检索返回partial，因为有217个forward gap。不存在词是覆盖/无结果合同边界；`荐`还叠加真实检索漏召回。Provider全部已记录响应为200，不将这些当成Provider失败。
- Python A一次Trace为collector_degraded，日志仅给出TraceStoreError而无可确认的底层原因，不能断言锁竞争。该run缺失sequence=1（query.received），其余2–30存在；完整Trace审计不可用，不重跑或假装完整。
- 首批hook错误挂在httpx，而当前SDK走httpx2。原0计数保留但标为无效；从Trace/usage核对首批17个完成请求，中断项1个完成响应、另1个可能在途。后续7runs由正确httpx2 hook记录14次200。**确认32次HTTP响应，计入取消中的请求后总尝试范围32–33，未超过40**；无法恢复取消请求的精确计费，不伪造整数。
- 15条已完成记录总Token **236,398**（input 226,969，output 9,429，cached-input 178,944），中断项已确认另6236 tokens，未完成请求usage未知。未返回真实成本金额，因此不推算费用。

[agent-summary.json](agent-summary.json)为脱敏运行摘要；私有原始结果、完整Artifact、Trace、review packet、HTTP列表和计数修正均保留在本地。审核状态是自动字面检查/AI诊断，没有人工答案裁决或付费Judge。现有索引与Prompt不为此次结果重调。

## 结论与可引用边界

本次证明：在固定真实快照的32个纯中文字面查询中，v2消除了unicode61的连续中文子串漏召回；44个中文/混排查询的micro全深度覆盖从3.193%升到99.993%，同时暴露6条混排漏召回、339个分隔写法FP、3条前十退化及单字限制。整体Recall@10提升有限且远小于全深度覆盖提升，构建、磁盘与SQL延迟均增加。

不能证明：Agent事实准确率达到99.993%；任意自然语言语义召回完整；单字支持；线上延迟SLA；跨语料泛化；全默认Agent或稳定E2E质量提升。查询为人工选词/同一语料，无盲测统计推断。后续若要优化，应分别用真实需求决定混排分隔语义、ASCII前后缀和单字支持；本任务不引入新tokenizer、LIKE查询fallback或Prompt改写。

简历证据与面试说明见 [CJK检索实验-简历与面试.md](../../../interview-docs/CJK检索实验-简历与面试.md)。工作验证：最终完整pytest **1187 passed/1 skipped**，专项7/7通过；ruff与mypy通过；原始ID独立指标核验、公开摘要一致性和文档链接检查通过。提交及推送身份见Git记录。
