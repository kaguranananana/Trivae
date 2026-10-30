# 研究问题池（Agent Quality Research 2026-10-29）

> 最新状态（2026-10-30）：本轮已完成并收束，结论以[REPORT.md](REPORT.md)和[STATE.md](STATE.md)顶部为准。R2/R6工程保留、R7 Prompt未采纳；剩余预算128/6，不重置。原问题池的open标签是研究前快照。

## 用途

汇集今晚 Agent 质量研究要回答的问题。每个问题独立登记，按状态推进；被否定的问题保留记录，不删除。

来源：2026-10-29/30 四路勘察的整合——①代码链路静态阅读（Agent 主循环/检索/预算/Trace）；②prompt-ab-eval-v1-20261029 正式 A/B 数据梳理；③历史文档负结果与工程约束；④Case 02/04/05/15 共 16 次运行的六阶段 trace 定位。承重引用已于 2026-10-30 抽查复核（见 STATE.md「已验证结论」），未复核的引用注明出处勘察。

## 排序标准与预算约束

- 排序：预期质量收益 × 影响面 × 复现程度 ÷（验证成本 × 实施复杂度）；等价地优先「预期信息量 ÷ 预算消耗」最大者。
- 今晚预算（budget.json）：DeepSeek Agent HTTP 请求 250 次、Judge 评审 32 次。
- 实测换算（prompt-ab-eval-v1-20261029/metrics.json：new_agent_usage_including_failures.requests=185 / new_agent_attempts.all=44）：**1 次运行尝试 ≈ 4.2 次 DeepSeek 请求；1 次有效运行 = 1 次 Judge 评审**。即今晚最多约 59 次运行尝试、32 次可评审运行。
- 零模型成本的离线实验（冻结库只读重放、study-data 分析、代码核验、人工裁决）不消耗预算，优先作为第 1 轮。

## 问题字段说明

每个问题必须包含以下字段：

| 字段 | 含义 |
| ---- | ---- |
| ID | 唯一编号，格式 `Q<N>`（如 Q1），供 STATE.md、LEDGER.md 备注引用 |
| 问题 | 一句话描述要回答的研究问题 |
| 待否定假设 | 该问题对应的可证伪假设（明确写出"预期什么、若观察到什么即否定"） |
| 最小实验设计 | 能对该假设给出证据的最小实验：对照条件、观察指标、假设区分逻辑、判定标准、预计成本 |
| 优先级 | high / medium / low（高优先级 = 预期信息量 ÷ 预算消耗 最大） |
| 状态 | open（待研究）/ in-progress（实验中）/ falsified（假设被否定）/ confirmed（假设未被否定）/ deferred（预算不足或依赖缺失，挂起） |

## 问题列表

### Q1（high）开放汇总类问题的关键事实消息从未被召回：失败在查询词设计、Top-K 窗口还是语义准入？

- **问题**：Case 15（开源项目分享）、02a（改代码流程）、04a/04b（订阅比价）等预注册关键事实消息在多数运行的已记录检索候选中从未出现——失败发生在查询词设计、Top-K/热度窗口截断，还是语义准入/排序？
- **待否定假设**：
  - H1（查询词设计）：模型只用泛化关键词与泛化语义查询、从不按事实特异词二次检索。已观察：Case 15 全部 8 次运行查询固定为 lexical「github.com」+ 泛化语义查询，无一次用 hindsight/记忆/skill 等区分词（勘察四）。
  - H2（窗口截断）：目标消息在 FTS 全量命中表中 rank 超出投影窗口（订阅 1084 命中只读前 100、github.com 308 命中前 100），或 semantic limit=10/20 截断（src/trivae/config/limits.py:11-16，已复核）。
  - H3（语义准入/排序）：literal-then-dense 排序（src/trivae/retrieval/semantic/retrieval.py:144-147，已复核）+ 准入无最低分阈值（同文件 158-190，已复核）+ ANN 池尾部弱相关挤占，同义表达目标进不了 top-K；与历史「同义召回边界」记录一致但从未做配对实验。
  - H4（分词/索引）：目标消息根本不在 FTS 全量候选中（分词或索引层问题）。
- **最小实验设计**：
  - 第 1 步（零预算）：只读连接冻结库 data/evaluation/frozen-20261028-validated/（trivae.sqlite3 + trivae.semantic.sqlite3），对 16 case 全部 GT 证据消息 × 每次运行的真实查询词（study-data.json + 各 record 目录 runs.json 的 retrieval_calls.direct_hits 全量表）重放 lexical/semantic 检索，记录目标消息全量 rank、dense_rank、是否进入 capability 投影窗口。解析口径可参考勘察四脚本 /tmp/trivae-survey/harness.py（若已清理则按其六阶段口径重写）。
  - 假设区分逻辑：消息不在 FTS 全量命中 → H4；全量命中但 rank > 投影 limit → H2（lexical）；语义近义变体查不回已知存在消息 → H3；每次运行查询词与目标文本零词交集且无二次收窄 → H1；rank ≤ limit 但未投影 → 转入 Q2。
  - 第 2 步（条件触发，仅当 H1 为主）：固定冻结快照/模型/预算，做「查询引导单变量」对照（只改工具 description 或 SYSTEM_PROMPT 检索策略段，不动四行约束），选 Case 15+02，每臂 2 rep（≈17 请求 + 8 评审），走 `trivae eval run` 正式入口。
  - 观察指标：每条未覆盖事实的失败层分布；第 2 步中目标消息召回率与覆盖变化。
  - 判定标准：H1 占多数且对照中召回/覆盖提升 → 确认查询引导是主要杠杆；H2/H3 占多数 → 依数据设计窗口/准入实验（数据先行，不盲目放大上限）。
  - 预计成本：第 1 步 0.5–1 人日、零预算；第 2 步 ≈17 DeepSeek 请求 + 8 Judge 评审。
- **证据指针**：勘察二/四；已复核 2026-10-30：`grep -c 7698750208906130992` 于 A/agent-runs/cap1-15-open-source/run-02、B/run-01、B/run-02 三个 trace-001.json 均为 0（文件存在、0 命中）；src/trivae/config/limits.py:11-16；src/trivae/retrieval/semantic/retrieval.py:114,144-190。
- **优先级**：high（4 个双臂全败 case 的共同主因候选；影响所有开放汇总类问题；8 次运行一致复现；第 1 步零成本）　**状态**：open（待研究）

### Q2（high）语义 chunk 命中但消息未进入工具投影：断层在 chunk→消息投影的哪一环？

- **问题**：语义检索在 chunk 级命中目标消息（Case 05 中 rank 4/7/6，chunk 区间覆盖该消息），但该消息未出现在消息级投影、证据、引用与答案中（Case 04c/04e parent-only 同模式）——断层在哪一环？
- **待否定假设**：
  - H1（投影区间/粒度）：expand_ranges 或 parent 投影子窗口未覆盖目标消息（src/trivae/retrieval/semantic/retrieval.py:128-141,192+；src/trivae/retrieval/context.py:273-403，均未逐行复核，出自勘察一/四）。
  - H2（投影排序截断）：目标消息实际已返回，但排在 direct_hits 记录窗口（50）之外不可考（src/trivae/evaluation/checks.py:47-51，已复核）。
  - H3（模型未采用）：投影已含目标消息，模型未做 get_message_context 定点深挖也未引用（Case 05 四次运行对该消息 0 次深挖，勘察四）。
- **最小实验设计**：
  - capability 级重放（零预算）：用 Case 05 三次运行的真实语义查询词直接调用 semantic_search Capability（只读库/EvaluationWorkspace），核对命中 chunk 的 parent 区间是否含目标消息、expand_ranges 产出集合与工具返回投影的差异；对照 runs.json direct_hits 全量表。
  - 假设区分逻辑：capability 层即不含 → H1（再定位区间公式）；capability 层含、历史运行投影记录不含 → H2（记录上限问题，并入 Q4 的落盘上限修正）；两者都含 → H3，转 Agent 重跑观察深挖行为。
  - 判定标准：「消息级投影缺失」的环节唯一化；若 H1 成立，给出最小修复点并以既有回归测试（tests/test_agent_runtime.py 等）验证修复不破坏契约。
  - 预计成本：0.5 人日、零预算；若 H3 成立补 2–4 次运行（≈8–17 请求 + 2–4 评审）。
- **证据指针**：勘察四（Case 05 阶段判定：含事实消息的候选 parent 贡献 0 条投影，其他候选 parent 贡献 8–20 条且与候选序一致）；已复核 2026-10-30：src/trivae/evaluation/checks.py:47-51。
- **优先级**：high（收益：语义路径普遍机制，非单 case；复现：3 case 一致模式；成本：capability 级重放零预算）　**状态**：open（待研究）

### Q3（high）答案合成丢失证据的认知属性：已引用证据被写错来源属性/断言过强

- **问题**：证据已返回、已入上下文且引用可回溯（02b 在 A2/B1 以 rank 17/28 命中、答案近乎逐字复述、绑定 e6 且 excerpt_truncated=false），但答案把转发建议写成「群里实践」、把推测写确定（attribution_error、unsupported_assertion）——认知属性在哪一层丢失？
- **待否定假设**：
  - H1（投影层缺失）：模型可见投影未呈现 provenance/epistemic 元数据（转发、机器人、频道等），模型无从区分；需核对 src/trivae/query/evidence.py 投影字段与 02b 运行的 direct_hits 投影。
  - H2（指令缺口）：SYSTEM_PROMPT 与四行约束均无 claim 级来源属性要求；新证据：B 臂 unsupported_assertion 34→39、四行约束未解决该类（勘察二重算）。
  - H3（生成后无校验）：Finalizer 只做结构/provenance 确定性校验，不检查结论是否被绑定原文语义支持（docs/PROJECT_STATUS.md:27 列为边界；docs/FAILURE_AUDIT_20261023.md:87-89,122 的「结论-来源绑定检查」至今未系统复验）。
- **最小实验设计**：
  - 第 1 步（零预算）：①核对 02b A2/B1 的 evidence_sources 与 direct_hits 投影是否含 forward 元数据（study-data.json + runs.json）；②对 01c 四次回答做人工 claim-原文绑定回读，统计「内容正确但属性丢失」vs「内容越界」比例；③读 evidence.py 投影字段清单确认 provenance 是否在模型可见 payload。
  - 假设区分逻辑：投影含 provenance 而答案丢失 → H2/H3；投影不含 → H1（工程修复点优先于任何 prompt 改动）。
  - 第 2 步（条件触发）：H2 为主 → 设计单条 claim-属性标注要求（有 A/B 新证据支持、按 docs/evaluation.md 正式 A/B，2 case × 2 臂 × 2 rep ≈ 17 请求 + 8 评审）；H3 为主 → 先做小规模人工 entailment 抽检（数字/人物/概述类各 1 题），不建自动裁判、不加无依据修复（ADR Stage 1.8 禁止项）。
  - 判定标准：第 1 步产出属性丢失层判定；第 2 步观察 attribution_error 计数与 02b/01c coverage 变化。
  - 预计成本：第 1 步 0.5 人日、零预算；第 2 步 ≈17 请求 + 8 评审。
- **证据指针**：勘察四（02b 六阶段判定）；勘察三（01c、FAILURE_AUDIT 待办）；已复核 2026-10-30：coverage-assessments.json 02b 条目——requirement 明确要求「作为转发建议而非被证实的通用修复」呈现，rationale 却写「均未报告该转述建议」（措辞与判定实质错位，见 Q4）。
- **优先级**：high（unsupported_assertion 是最高频诊断之一且 B 臂上升；影响所有含转述/推测的回答）　**状态**：open（待研究）

### Q4（high）质量信号链自身可信度未建立：judge-人工一致率、完成门槛假阴性、rationale 错位、Trace 记录截断

- **问题**：所有质量结论依赖的 Judge 分数、coverage 判定与 Trace 记录自身存在已知可信度缺口且未校准——它们会不会系统性扭曲 tonight 及以后的实验结论？
- **待否定假设**：
  - H1：Judge v2.1 与人工判断基本一致（14 份 Eval v1 重评 review 全部进入人工复核队列至今 0 份裁决；interview-docs/Evaluation校准审阅-20261028.md 已有逐题裁决建议，勘察三）。
  - H2：完成门槛无系统性假阴性——现存反证：judge 双轴≥3 但未过 case 门槛的运行 A 5 次/B 8 次，同 case 重复完成一致率仅 62.5%（metrics.json repeat_completion_agreement=0.625，已复核）。
  - H3：rationale 措辞错位是孤例（02b 已证实一例：requirement 是属性区分、rationale 写「未报告」；下一轮 rationale 模板应引用答案 claim 文本）。
  - H4：Trace 记录截断不影响失败归因——已被勘察四否定一半（normal 档 512 字符/16 items，src/trivae/observability/collector.py:64-65 已复核，使工具输出与候选表不可考；checks.py:47-51 另有 50/8/50/20 记录上限）；提高上限属纯工程改动、零模型影响。
- **最小实验设计**：
  - ①人工裁决 14 份 review（1–2 小时人工、零预算），按轴与诊断计算一致率。
  - ②把勘察二的复算逻辑固化为 research 目录内脚本（judge≥3-but-fail 门槛分解、62.5% 一致率复核）。
  - ③下一轮评测的 coverage rationale 模板强制引用答案 claim 文本与判定依据。
  - ④trace 落盘上限配置化 + 全量落盘 retrieval candidate/direct-hit 表（collector.py:65、checks.py:47-51），工程改动 + 既有测试回归，零预算。
  - 判定标准：一致率 <80% → 本轮所有 judge 结论加强 provisional 标注、后续阈值判定预注册双判据（judge 分数 + case 门槛并行报告）；一致率高 → judge 单判据可信。
  - 预计成本：人工 1–2 小时 + 脚本/工程各 0.5 人日、零预算。
- **证据指针**：勘察二/三/四；已复核 2026-10-30：metrics.json 标量与 collector.py:64-65、checks.py:47-51。
- **优先级**：high（收益：它是其余全部问题的判分前置；影响面：全部评测；成本：近零）　**状态**：open（待研究）

### Q5（medium）Token 估算常数（UTF-8 bytes ÷ 3）的中文偏差未校准：预算与 Trace 指标建立在未验证估算上

- **问题**：全部裁剪/预算结算/Trace 指标使用 MODEL_TOKEN_CHAR_RATIO=3（src/trivae/query/evidence.py:58，已复核）估算 token——中文语料下的偏差方向与幅度未知，预算决策与实验解读建立在校准前。
- **待否定假设**：
  - H0（待否定）：bytes/3 与 provider 实际 tokenizer 的偏差 <30% 且方向稳定。
  - H1 中文系统性偏差（勘察一推断「低报 2–3 倍」，但 1 汉字 ≈ 3 bytes ÷ 3 = 1 token/char 与常见中文 tokenizer 约 0.5–1.5 token/char 的关系方向未定——正因方向不明才需校准）。
  - H2 混合中英文偏差不一致，使 per-call ceiling 与 run pool 的有效容量偏离设计意图，「剩余 < 2×最小开销即 finalizing」的终止预判时机失准（openai_adapter.py:1033-1045，勘察一）。
- **最小实验设计**：
  - 离线（零预算）：冻结库分层抽样（中文为主/英文/混合 × 长短分布，各 ≥300 条），用 provider tokenizer（或以评测侧精确 usage 计数交叉验证）对比 bytes/3；再用 A/B 64 次运行 study-data.json 的 agent_usage 与 Trace 预算结算快照（estimated_tokens vs 实际 usage）做回归。
  - 判定标准：偏差 >30% → Trace 双指标记录 + Q6 实验带校正系数解读 + 预算默认值重估提案；<30% → 记录结论、公式不动。
  - 预计成本：0.5 人日、零预算。
- **证据指针**：勘察一；已复核 2026-10-30：src/trivae/query/evidence.py:58。
- **优先级**：medium（间接收益但近零成本，是 Q6 的解读前置）　**状态**：open（待研究）

### Q6（medium）共享证据预算的耗尽链：整轮预留超池直接 failed、大调用独占池、后续查询空返回

- **问题**：预算机制的三个环节在 A/B 中造成 2 次运行硬失败与多次「第 4 轮起空手而归」——分配策略与耗尽处理从未做对照（不试已否决的「简单 8k 默认」、不扩大池）。
- **待否定假设**：
  - H1（超池即失败）：reserve_budget_stop_results 整轮总额 > 剩余 run pool 时直接 raise ToolResultBudgetExhausted（src/trivae/query/runtime/openai_tools.py:90-94，已复核），异常冒泡使 run 终态 failed、已完成证据不进入综合（openai_adapter.py:1506-1518，勘察一）；「剩余 < 2×最小开销即 finalizing」预判只在上轮完成后评估，挡不住同回合并行突发。改为「部分预留 + 其余调用返回显式 budget-stop envelope → 下一轮 finalizing」可消除硬失败且不降质量。
  - H2（大调用独占）：per-call ceiling（context×50%，cap 128k，limits.py:51-52）远大于 run pool（25%/cap 256k 或显式 32k），实测 02-B2 单次「改代码」投影 100 条消耗 31760/32000（勘察四），后续轮空返回；「同轮全为 get_recent_messages 才均分」（openai_tools.py:99-105，已复核）之外的组合分配不确定。
  - H3：上述现象部分归因于 Q5 的估算偏差而非分配策略本身。
- **最小实验设计**：
  - 第 1 步（零预算）：单测复现 H1 raise 路径与 H2 分配顺序依赖（构造 budget 状态直接调用 reserve_budget_stop_results / protect_tool_result_budget）。
  - 第 2 步（依赖 Q5 校准解读；固定 32k 显式池）：对 cap1-02、cap1-04 做「超池处理：raise vs 优雅 finalizing」单变量代码开关对照，2 case × 2 rep（≈17 请求 + 8 评审）。
  - 观察指标：硬失败率、有效完成率、关键事实覆盖率、budget-stop 次数、最终答案引用的证据量。
  - 判定标准：优雅 finalizing 消除 failed 且覆盖不降 → 记录 confirmed（合入属核心链路语义修改，须按 .trellis/spec/project/engineering-principles.md 升级边界确认后另行提交）；覆盖下降 → 记录负结果保留现状。H2 的分配策略（首轮配额）在校准后另立实验，不与 H1 混变量。
  - 预计成本：单测+修复 1–1.5 人日 + ≈17 请求 + 8 评审。
- **证据指针**：勘察一/二/四；已复核 2026-10-30：src/trivae/query/runtime/openai_tools.py:90-105。
- **优先级**：medium（收益：消除 3% 硬失败 + 空返回；复现：2 次失败 + 多次投影 0 条；成本：中）　**状态**：open（待研究）

### Q7（medium）投影裁剪与邻居扩展的系统性信息偏置：尾部先丢（时间最新）与 20 锚点静默无邻居

- **问题**：模型可见投影的裁剪从稳定顺序尾部省略（消息按 timestamp ASC ⇒ 最新先丢），邻居扩展锚点上限 20 处静默无邻居——「最新进展/是否有人回应」类问题是否被系统性伤害？
- **待否定假设**：
  - H1 omitted 消息的 timestamp 分布显著偏新（相对查询锚点）：裁剪二分从尾部省略（src/trivae/query/evidence.py:2257,2309 已复核）+ 消息按 timestamp ASC 排（勘察一引 structured.py:41-43）。
  - H2 >20 direct hit 的运行中，未获邻居的命中无 per-hit「此命中无邻居」标注（src/trivae/retrieval/context.py:188-193 已复核），模型可能误判「无人回应」；metadata 的 context_source_hits/budget 可核对（勘察一）。
  - H3（待否定）：该机制在现有 64 次运行中已实际造成可观察伤害（omitted 集中于时间敏感 case 且含 GT 证据）。
- **最小实验设计**：
  - 离线（零预算）：从 16 运行 trace 的 runtime.tool.completed 投影计数 + 各 record evaluation direct_hits 全量表，统计 omitted_hit/omitted_context 消息的 timestamp 相对查询锚点的分布、被省略消息与 GT 证据集的交集、>20 hit 运行的邻居覆盖情况。
  - 假设区分逻辑：omitted 显著偏新且含 GT 证据 → H3 成立，升级「两端保留/per-hit 标注」投影策略对照（另行立项）；无集中偏新或未触及 GT → H3 否定，记录低风险保留现状。
  - 预计成本：0.5–1 人日、零预算。
- **证据指针**：勘察一；已复核 2026-10-30：src/trivae/query/evidence.py:2250-2343、src/trivae/retrieval/context.py:186-193。
- **优先级**：medium（机制确定但伤害未证实；离线验证便宜）　**状态**：open（待研究）

### Q8（medium）答案层时效/范围声明系统性缺失：04d 四次未覆盖 + 双臂各 26 条 temporal_or_scope_error

- **问题**：回答不声明「历史消息无法确认查询时点仍有效」（04d 四次未覆盖、A1 触发唯一 guardrail 违例、judge 诊断 temporal_or_scope_error 26+26 条）——模型可见上下文是否根本没有查询时点锚定？
- **待否定假设**：
  - H1（锚定缺失，已部分证实）：动态 instructions 只注入 SYSTEM_PROMPT + 工具轮预算 + no_result 资格 + 计划指导（src/trivae/query/runtime/openai_adapter.py:1648-1689，已复核），无查询时点/范围锚定事实；SYSTEM_PROMPT 的时间规则是检索窗口选择（prompt.py:16-24,117-121，grep 确认），未见「答案须声明历史信息可能失效」要求（全文确认待第 1 步）。
  - H2（模型能力）：锚定存在但 deepseek-flash 不生成时效声明。
  - H3（证据不足）：04-A1「优惠」专项检索因预算空返回，无可触发声明的证据（与 Q6 交互，勘察四）。
- **最小实验设计**：
  - 第 1 步（零预算）：全文读 prompt.py 确认无时效声明要求；从 study-data.json 统计 52 条 temporal_or_scope_error 是否集中于无时效相关证据的运行。
  - 第 2 步（单变量）：case 04 固定条件下对照「instructions 增加查询时点锚定事实」vs 基线，每臂 2 rep（≈9 请求 + 4 评审）。
  - 判定标准：04d 覆盖改善 + guardrail 违例消失 + reliability 不降 → 按评测流程验证后合入；无改善 → H2，记录模型能力边界；若 temporal 错误集中于预算空返回运行 → 先做 Q6。
  - 预计成本：第 1 步 0.5 人日零预算；第 2 步 ≈9 请求 + 4 评审。
- **证据指针**：勘察二/四；已复核 2026-10-30：openai_adapter.py:1648-1689 与 prompt.py grep 输出。
- **优先级**：medium（temporal_or_scope_error 是与 unsupported_assertion 同级的高频诊断；guardrail 违例仅 1 例但 reliability 2 分集中于 case 04）　**状态**：open（待研究）

### Q9（medium）当前主 Prompt（Candidate B）覆盖率回退（-6.9pp）的机制未定位

- **问题**：B 臂覆盖率 52.8%→45.9% 与 citation mismatch 12→3 改善并存——回退是行为收缩、表述收缩还是个案集中？这决定 v2 候选怎么设计（docs/evaluation.md:66 已声明「采纳不等于证明总体质量提升」）。
- **待否定假设**：
  - H1（行为收缩）：B 臂 tool_calls/检索次数/证据量显著少于 A 臂（四行约束促使提前收束）。
  - H2（表述收缩）：检索行为不变，答案更保守、具体事实密度更低。
  - H3（个案集中）：回退集中于 Case 10/12，非普遍机制（勘察二：case 级差值方向不一致、每格仅 2 次运行）。
- **最小实验设计**：
  - 离线（零预算）：study-data.json 对比两臂行为量指标（tool_calls、retrieval 次数、evidence_sources 数、answer 长度、具体事实密度=数字/专名/消息细节比例）。
  - 假设区分逻辑：行为量显著下降 → H1；行为不变而事实密度降 → H2；差值集中于个别 case → H3。
  - 判定标准：机制定位后才设计 v2 候选（保留 citation 收益、修复对应缺陷），走 16 题冻结正式 A/B（≈134 请求 + 64 评审，超出今晚 Judge 预算，另行安排）；不重跑旧六题（docs/evaluation.md:66 边界）。
  - 预计成本：0.5–1 人日、零预算；后续 A/B 另计。
- **证据指针**：勘察二/三；已复核 2026-10-30：metrics.json（coverage 0.528125/0.459375、relative_change.coverage=-0.1302）。
- **优先级**：medium（main 上的已记录开放风险；离线定位便宜；修复实验贵）　**状态**：open（待研究）

### Q10（medium）工具轮 4–6 的单变量价值实验

- **问题**：默认 6 轮（bfa3118）的收益从未单变量证明，历史全范围同题两组实际只用 2 轮——这是 docs/FAILURE_AUDIT_20261023.md:124 明确列为待做、且严禁归因造假的实验。
- **待否定假设**：
  - H0（待否定）：固定 Prompt/冻结数据/32k 池/模型下，允许 6 轮的运行会实际进入第 4–6 轮并带来新增必要证据。
  - H1 运行从不进入第 4 轮 → 6 轮默认无收益证据。
  - H2 进入但新增证据未提升覆盖 → 轮数非当前瓶颈。
- **最小实验设计**：
  - 固定冻结快照 + 当前主 Prompt + 32k 池 + deepseek-flash，只改 TRIVIAE_MAX_TOOL_ROUNDS（3 vs 6），选检索密集 4 case（02/04/05/15），每配置 2 rep = 16 次运行（≈67 请求 + 16 评审——占今晚 Judge 预算一半，需与 Q8/Q3 第 2 步排序取舍）。
  - 观察指标：每轮工具调用分布、第 4–6 轮新增证据是否进入最终引用、覆盖率。
  - 判定标准：6 轮组进入第 4–6 轮且新增必要证据比例 >0 且覆盖提升 → 保留 6 轮；否则记录负结果考虑回 3 轮。严禁把前 3 轮策略变化算作 4–6 轮收益（历史禁令）。
  - 预计成本：≈67 请求 + 16 评审 + 1 人日。
- **证据指针**：勘察三（docs/FAILURE_AUDIT_20261023.md:124；docs/DEVLOG.md:223,226）。
- **优先级**：medium（文档明确待做；成本占 Judge 预算大，排第 2 轮之后）　**状态**：open（待研究）

### Q11（low）路由层对最终质量的影响未测量：正则短路 + Jev shadow 已关闭

- **问题**：五组中文正则 + confidence≥0.8 短路（src/trivae/query/router.py:154-161,199-202，勘察一）决定 structured/planned 路径；Jev 分类正结果（93.75% vs 81.25%）因缺 utility 链路从未升级且本机已关闭——路由错误对覆盖率的影响有多大？
- **待否定假设**：
  - H1 路由分布偏斜或误路由对覆盖率影响显著（ExecutionOverride.forced_route 可隔离测量，query/contracts.py:39，勘察一）。
  - H2 路由错误率低且对质量影响不显著 → 维持现状，Jev 重估长期挂起。
- **最小实验设计**：
  - 第 1 步（零预算）：16 case 的 trace router.decision 统计实际 route 分布与规则命中占比。
  - 第 2 步（条件触发）：2–3 个 route 敏感 case 用 forced_route 配对（每臂 2 rep ≈ 25 请求 + 12 评审）。
  - 判定标准：route 间覆盖差 < 预注册阈值（±10pp）→ H2，路由层降级；显著 → 才立项 Jev 重估（需人工标签 + 完整对照，成本高，另行安排）。
  - 预计成本：第 1 步 0.5 人日零预算；第 2 步 ≈25 请求 + 12 评审。
- **证据指针**：勘察一/三（.trellis/spec/project/technical-decisions/router-jev-provider-experiment.md:22,26,34,38）。
- **优先级**：low（无新负结果证据但 utility 链路缺失使收益不确定；重估成本高）　**状态**：open（待研究）

### Q12（low）Capability v2 剩余 20 题真实续跑（3 失败 + 17 未启动）

- **问题**：--case-list 续跑入口已实现并测试、remaining-case-identities.json 已固化 20 个 case 版本，但因订阅额度从未真实执行；30 题 Baseline 与「用户问题优先候选集」待补齐。
- **待否定假设**：执行型任务，无待否定假设；价值假设是 30 题全量 Baseline 会扩大后续归因的样本面。
- **最小实验设计**：额度恢复后按 docs/capability-evaluation-v2.md:119-142 续跑清单执行正式评测入口（`trivae eval run` + freeze manifest + 独立工作库）；结果并入本池归因。
  - 判定标准：30/30 Baseline 完成。
  - 预计成本：20+ 次运行（超出今晚预算）；**阻塞在外部订阅额度（用户侧）**。
- **证据指针**：勘察三（docs/capability-evaluation-v2.md:47,119-142；docs/DEVLOG.md:362-368）。
- **优先级**：low（依赖缺失；完成后收益是样本面而非直接质量）　**状态**：open（待研究；执行依赖外部额度恢复，恢复前实质 deferred）

### Q13（low）Provider 非法 JSON（AnswerDeltaParseError 型）被动观测：只收集诊断上报，不做修复

- **问题**：Case 03 型故障（Provider 在 JSON mode 下返回含未转义引号的非法 JSON）根因在 Provider 侧且未解决——已保存偏移/chunk/坏字符/上下文诊断，等待真实复现以统计发生率并向上游定位。
- **待否定假设**：
  - H0（待否定）：该故障在当前 provider/模型组合下复发率可忽略（等待复现数据）。
  - H1 复发且已保存诊断足以向 DeepSeek 上游定位（区分 401/402/429/5xx 错误码族）。
- **最小实验设计**：观察型：今晚及后续任何真实运行复现时，按 docs/EVAL_RUNTIME_FAILURES_20261029.md:22-38 登记发生率与诊断内容；不新增任何解析修复、兼容分支或重试（.trellis/spec/project/engineering-principles.md:29-34 禁试）。
  - 预计成本：零（被动观测）。
- **证据指针**：勘察三（docs/EVAL_RUNTIME_FAILURES_20261029.md:22-24,26-38；docs/eval-v1.md:148-150）。
- **优先级**：low（低频；修复方向被禁，唯一动作是观测）　**状态**：open（待研究）

## 排除方向清单（历史负结果已否定，不入池）

新证据出现时须先在 STATE.md 记录证据再重开；本池所有实验设计已主动避开以下方向：

1. 具名资源充分性 Prompt 与盲目「叠加提示句」（.trellis/spec/project/problems/named-resource-sufficiency.md:25,33；docs/FAILURE_AUDIT_20261023.md:76）。例外路径：Q3 第 2 步仅在有 A/B attribution 新证据、单条针对性要求、走正式 A/B 评测时考虑。
2. 简单 8k 首轮预算默认（docs/DEVLOG.md:111-113）。Q6 固定 32k 池做分配/耗尽处理对照，不属此列。
3. 把轮数收益归因第 4–6 轮、或以前三轮策略变化冒充轮数收益（docs/FAILURE_AUDIT_20261023.md:124）。Q10 即该禁令要求的单变量实验。
4. ASCII 词内前缀 LIKE / 改 BM25 / 全面子串搜索（docs/FAILURE_AUDIT_20261023.md:109）。
5. Provider 非法 JSON 的修复、兼容解析、无依据重试（docs/EVAL_RUNTIME_FAILURES_20261029.md:24）。Q13 仅被动观测。
6. 无真实 Failure Case 支撑的新增 retry/fallback（.trellis/spec/project/engineering-principles.md:29-34）。
7. 扩大 Planner 使用 / 全库 Planner 调参（.trellis/spec/project/technical-decisions/planner-engineering-closure.md:19-25）。
8. 只靠扩大总证据池解决覆盖/长度（docs/DEVLOG.md:214；旧基线 23,852/125,000 证明池不是瓶颈）。Q6 全部实验固定池。
9. 盲目放大其余上限（docs/DEVLOG.md:210）。Q1 的窗口/limit 只做离线截断频率测量，数据先行。
10. 打开封存 Holdout、混用不同 Snapshot/模型分母（docs/FAILURE_AUDIT_20261023.md:127）。本池全部实验单一冻结快照 frozen-20261028-validated。
11. SQLite backup 长期工作副本 / 共享库跑正式评测（AGENTS.md 评测数据库生命周期约定）。
12. 自行启动/重启/登录 QQ 或 NapCat（docs/DEVLOG.md:316-324）。
13. ADR Stage 1.6/1.8 排除项：automatic replan、Planner-owned state、LLM Plan Validator、retrieve_evidence 工具、Evidence Agent、固定关键词 Judge、Runtime-owned Evidence 状态机、silent citation drop、自动来源替换、无依据 repair/retry（.trellis/spec/project/technical-decisions.md）。

## 维护约定

- 问题状态推进时同步 STATE.md 的「待验证假设 / 已否定假设」小节；每个问题做完最小实验后在原条目追加结果行，不删除。
- 真实模型请求先记 LEDGER.md 一行、再同步扣减 budget.json；预算耗尽即停止一切真实模型请求，剩余问题转 deferred。
- 同一失败模式的新候选合并进既有问题的假设列表，不新开问题，除非失败层不同。

## Codex恢复后的状态覆盖 · 2026-10-30

以下续记覆盖原13项的统一open状态，原假设与探索过程保持不改。

- Q1/Q2/Q7：已验证semantic候选到100条消息容量的优先序断层；51调用最高dense排名整块丢失19→0，目标出现8→18、无已知目标退化。候选尚需真实答案A/B。R1数字parent包含/S3归因和L6采用统计不是权威根因分母。
- Q4：辅助复核和口径审计完成；人类裁决未完成。02b理由错但属性门槛仍未满足，不改分数；L6仅36/40精确ID一致。见R3-results.md。
- Q5：旧1.31不是严格tokenizer校准，不调整预算，精确校准仍open。
- Q8：52条诊断中辅助拆分41范围、4来源日期、7历史→当前；否定“全部来自缺查询日期锚定”，暂停单纯日期注入实验。
- Q9：不支持表述收缩；工具调用变少与覆盖回退有关联，因果仍未确定。
- Q3/Q6/Q10/Q11/Q12/Q13：原调查结果与约束保持，未因候选检索收益宣称已解决；不重跑历史负结果、不自动续跑Capability30题。

Q8最终证伪（Codex）：audit_time_context.py逐一检查原64Run实际model_visible_context，64/64已有正确as-of时间消息；来源是EvaluationRunner对Case.time_context的正式注入。不得因SYSTEM_PROMPT无时间变量再提“缺查询时点”修复。时效错误的剩余方向是历史→当前的语义使用、来源日期解读及范围约束，非重复注入时间。
