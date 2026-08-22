# ChatLab Evaluation 架构核对

## 目的

核对本地 ChatLab 当前实现中与 Trivae Stage 1.10 直接相关的 Evaluation、Router / Planner、Runtime budget、Retrieval 参数与 Evidence 判断方式，区分可继承的架构经验、只能作为 baseline seed 的经验参数，以及 Trivae 已明确不继承的设计。

## 已确认事实

### 1. ChatLab 已有固定 Router Evaluation Set，但还不是可执行质量评测系统

- `evaluation-set.ts:3-30` 定义场景标签、稳定 Case ID、locale、chat type、User Message、expected route、expected evidence coverage 与 baseline 状态。
- `evaluation-set.ts:32-51` 要求覆盖固定场景，并明确 baseline 必须等待真实或 fixture 数据库与真实模型运行，不能伪造。
- `evaluation-set.test.ts:5-42` 只校验样本规模、ID 唯一性、Route / scenario 覆盖、planned case 的 evidence coverage 描述以及 pending baseline；它不执行 Router、Planner、Retrieval 或最终 Answer，也不产生质量分数。
- 当前集合有 24 个 Case，覆盖简单查询、长时间趋势、关系分析、话题演变、搜索失败恢复、多条件筛选和证据不足等场景。

**结论**：Trivae 应继承稳定 Case ID、场景覆盖、明确 expected evidence coverage、真实运行前 baseline 必须 Pending 的纪律；不能把静态 Case registry 当成完整 Benchmark。

### 2. Router 的单点分类分数不足以证明 Planner 有价值

- `router.ts:31-47` 包含经验 confidence threshold 与 Route taxonomy。
- `router.ts:149-179` 通过多个复杂度信号识别 planned path；`router.ts:214-245` 使用 Rule-first，再在低 confidence 时交给 LLM fallback。
- ChatLab 后续在真实调用路径记录 Route Decision、耗时与来源，并先以 shadow-style observation 引入，再接入 Planner 路径。

**结论**：Trivae 可继承“先观察 Route Decision，再用真实 workload 校准”的渐进方式；但 Trivae 已确认只有 `standard_execution / planned_execution` 两路，最终指标必须是 Planner Invocation 的下游 Utility，而不是照搬 ChatLab 三路分类准确率。

### 3. Planner 是 bounded soft guidance，适合做 paired evaluation

- `planner.ts:41-49` 定义有限 intent taxonomy。
- `planner.ts:75-118` 对 LLM Plan 做 deterministic parse / filter / bound，步骤与 success criteria 均有上限。
- `planner.ts:125-175` 的 Plan 包含高层调查目标、建议 Tool 与 Evidence Requirement，但明确是 soft guidance，不是 Workflow。

**结论**：Trivae 应在同一 Case 上比较 standard 与 planned、with planner 与 without planner 的 Answer / Evidence 质量和成本；不应仅评价“Plan 文本看起来是否合理”。

### 4. ChatLab 参数可作为 baseline seed，但不是 Trivae 的最优值

- `constants.ts:1` 的 Agent Runtime 默认 Tool Round 上限是经验值；`core.ts:25-37` 接收可覆盖参数，`core.ts:164-190` 记录 Tool 使用与轮次，达到预算后转入 final synthesis。
- `prompt.ts:35-49` 包含消息返回上限、Search 前后上下文、Compression threshold / buffer / Tool Result 占比等经验配置。
- `chunker-config.ts:26-63` 定义 Parent / Child Chunk 的时间、字符数、消息数、token 与 overlap 参数。
- `hybrid-search.ts:34-52,76-128` 定义 dense / FTS candidate pool、融合常数与 final top-k。
- `evidence.ts:44-52,93-104` 定义 Evidence 总预算、单块上限、context expansion 与最大 chunk 数。

**结论**：这些数字只能作为标注来源的 v1 baseline variant。Trivae 应通过固定 Case、固定数据快照和受控 variant 比较校准，不能因 ChatLab 已运行就把数字升级为 Trivae 架构事实。

### 5. Evidence 架构存在明确的继承与偏离边界

- `retrieve-chat-evidence.ts:215-229` 合并语义与关键词候选后，用固定词表把证据分成 included / excluded / uncertain。
- `retrieve-chat-evidence.ts:240-283` 以固定时间接近度把来源分组。
- `retrieve-chat-evidence.ts:297-335` 将 completeness warning 与候选 Evidence 输出给 Agent，并要求保守作答。

Trivae Stage 1.8 已确认：

- 继承结构化 Evidence、来源定位、bounded source review、显式 incomplete / partial 与保守作答原则；
- 不继承固定关键词 Judge、固定时间 Evidence 分组、独立 Evidence Tool 作为主语义边界；
- 使用 question-specific criterion、finding-oriented multi-source Evidence、claim-level Citation 与独立的 sufficiency / Tool completeness 双轴状态。

**结论**：Stage 1.10 必须评价 semantic entailment、criterion quality、sufficiency、contradiction handling 与 Citation coverage；不能把 ChatLab 的机械 included / excluded 状态直接当 Ground Truth。

## ChatLab 没有提供的 Stage 1.10 能力

本地实现中没有发现以下完整机制：

- 绑定固定数据快照与 Data Access Scope 的端到端 Case Bundle；
- 运行 Router → Planner → Runtime → Retrieval → Evidence → Citation → Answer 的通用 Evaluation Runner；
- 对 stochastic model output 的重复运行与方差处理；
- baseline / candidate 的 paired comparison 结果模型；
- Answer Correctness、Evidence Completeness、semantic entailment 与 Citation coverage 的正式 review contract；
- 人工 review 与 model-assisted judge 的治理边界；
- Failure Diagnosis 与 immutable Trace 的关联模型；
- 真实 Failure Case 进入 Regression Set 的生命周期；
- 质量 threshold、critical gate、budget gate 或 promotion policy。

这些是 Trivae Stage 1.10 需要自行确认的架构部分。

## 最终继承口径

### 直接继承为架构经验

- 稳定 Case ID 与场景覆盖清单；
- planned case 显式描述 expected evidence coverage；
- 真实环境运行前 baseline 保持 Pending，不伪造结果；
- Route / Plan / Tool / usage / budget 过程可观察；
- 参数显式化并允许 variant 覆盖；
- 先观察、后校准、再决定是否进入实际 gate。

### 仅作为 baseline seed

- Router confidence、Planner bounds；
- Tool Round、history / compression / Tool Result budget；
- Search context、Chunk、candidate pool、top-k、Evidence budget 等具体数字；
- ChatLab 的场景比例与语言分布。

### 明确不继承

- 三路 Route taxonomy；
- 固定关键词 Evidence Judge；
- 固定时间 Evidence 分组；
- ChatLab-specific Tool surface 与 Prompt heuristic；
- 把静态 Evaluation Set 结构测试当作质量 Benchmark；
- 没有真实 baseline 就设定 pass / fail threshold。
