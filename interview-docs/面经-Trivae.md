# Trivae 项目面经

> 文档归档：`interview-docs/`，与项目导学及后续面试材料统一维护。
>
> 使用边界：仓库未提供用户的个人职责与协作边界。以下一级 bullet 和第一人称口播统一按“参与构建/参与定位”的保守口径生成，使用前必须结合真实 PR、commit 与协作事实确认；不得把团队成果改写为个人主导。所有评测数字只描述已完成的 Development 阶段。

## 1. 项目简介（简历可用）

Trivae 是一个面向高噪声群聊记录的技术情报分析系统，将原始聊天标准化为可检索数据，通过关键词、语义、结构化与时间检索支持 Agent 调查，并用当前运行证据约束答案与引用。项目同时建设了全链路 Trace 和可复现评测体系，用于区分召回、排序、上下文、答案契约及外部模型服务故障。

## 2. 简历 bullet

- **统一数据底座：** 针对群聊导出格式来源特定、身份与消息容易混淆的问题，参与将来源、会话、成员、消息和导入批次规范化到统一模型，以 Canonical Store 保存事实、关键词与向量索引保存可重建派生数据，并显式记录导入 provenance、索引身份和 stale/partial 状态；当前真实 Snapshot 已覆盖 473,236 条消息与 14 个来源，个人负责范围待结合提交记录确认。
- **分层检索编排：** 针对精确谓词、语义改写、时间浏览、人物解析和上下文恢复无法由单一搜索策略稳定承载的问题，参与拆分关键词、语义、结构化和上下文能力，由统一 Tool Contract 传递授权 Scope、coverage、truncated 与来源信息，避免静默回退掩盖失败；已在 10 个 exhaustive/corpus predicate query 上验证关键词 Recall@10 为 33/33，语义通道仅作为互补能力而不宣称全面优于关键词检索。
- **受约束智能执行：** 针对复杂度判断、计划生成与工具执行职责混杂会形成多套状态的问题，参与采用“轻量路由—一次性软计划—共享 Agent Runtime”的执行链，将轮次、工具预算、超时、取消和最终合成纳入显式边界；标准与计划路径复用同一运行时和应用入口，使行为差异可通过 Trace 与 Controlled Variant 验证，具体个人设计或实现 ownership 待确认。
- **证据化答案提交：** 针对模型可能引用未检索、越权或失效来源的问题，参与将事实声明、证据与引用关系建模为结构化答案产物，限定引用只能来自当前运行且在授权范围内的工具结果，并在提交前完成来源水合、范围校验、零结果充分性检查与原子会话写入；冻结后的 Development 全能力 Variant 取得 37/37 有效结构化答案产物，但该指标只代表契约有效，不等于事实正确率。
- **可复现评测与归因：** 针对 Agent 系统失败难以复现且容易把外部服务故障误判为算法问题，参与建立 Snapshot/Environment Gate、47 条人工裁决 GT、五 Variant 消融、append-only Trace 和 acceptance-condition Failure Artifact；在 37 条 Development Case 上完成 185 次真实 production-path 运行，并将测量层缺陷定位为逐调用排名丢失与异步客户端跨 event loop 生命周期错误，修复后保留召回、排序、上下文和 provider failure 的真实边界。

## 3. 面试问题

### Q1（最高频）：请用两分钟介绍 Trivae，它解决的核心问题是什么？

**主问口播（STAR）：** 我先说明职责边界：我在该项目中的精确 ownership 还需要用提交记录确认，下面按参与构建的事实口径回答。场景上，技术群聊信息量很大，但有效信息被闲聊、重复表达和碎片上下文淹没，普通关键词搜索即使命中，也很难形成可复核的结论。我的任务是参与把“找消息”扩展为“围绕问题调查并给出证据型回答”。行动上，项目先把多来源聊天统一到规范化数据模型，再提供关键词、语义、结构化、时间与上下文能力，让 Agent 在受约束的运行时中组合调用；最终答案必须绑定当前运行真实取得的证据，并经过引用校验后提交。结果上，系统形成了从 473,236 条消息的真实 Snapshot 到检索、回答、Trace 和 Evaluation 的闭环，但线上用户价值与 Holdout 泛化仍待验证。

#### 追问 1：为什么不直接用向量数据库加大模型回答？

**追问口播（STAR）：** 场景上，直接“向量召回加生成”看起来路径最短，但群聊问题并不都属于语义相似搜索：精确名称、时间范围、成员身份、数量统计和上下文恢复需要不同的确定性能力。我的任务是参与保留问题类型与检索策略之间的可解释关系。行动上，项目把统一消息库作为事实源，把关键词和向量索引视为可重建派生数据，并将结构化查询、最近消息和上下文扩展拆为独立能力；每次返回都携带范围、覆盖度、截断和来源事实。结果上，评测能明确看到关键词在 exhaustive 精确谓词上的优势，也能暴露语义检索与上下文恢复当前的不足，而不是用一个混合分数掩盖问题。

#### 追问 2：这个项目最难的地方不是模型能力吗？

**追问口播（STAR）：** 场景上，模型能力确实影响答案，但真实难点是系统必须知道“这次结论依据了什么、没有覆盖什么、失败属于谁”。如果只关注生成效果，provider 超时、检索未命中、排序靠后、上下文缺失和引用非法都会表现成一句“答案不好”。我的任务是参与建立可归因的工程边界。行动上，项目让数据、检索、工具、运行时、证据提交和评测各自保留结构化事实，再用带顺序和因果关系的事件串起一次查询。结果上，系统可以把失败拆成 provider、召回、排序、coverage、context 与 finalization 等类别，并据此决定修主链路还是保留外部可用性事实。

### Q2（高频）：为什么把系统分成 Data Plane 和 Query Plane？

**主问口播（STAR）：** 场景上，原始 QQ 导出包含来源特定字段、身份和时间格式，如果查询执行直接读取这些格式，任何来源变化、解析修复或索引重建都会波及 Agent 主链路。我的任务是参与建立稳定的领域边界。行动上，数据平面负责导入、规范化、事实存储和派生索引；查询平面只接收自然语言问题和运行上下文，通过能力层访问数据，不理解原始导出格式。第一版结构化 SQL 是有意暴露的物理查询契约，但仍受只读规则和授权范围约束。结果上，事实模型与查询编排可以独立演进，向量索引损坏或陈旧时也能显式重建，而不会改变 Canonical Store 的事实地位。

#### 追问 1：两层之间为什么还需要 Tool/Capability Layer？

**追问口播（STAR）：** 场景上，如果运行时直接调用具体仓储，模型看到的是内部实现细节，权限、错误和结果形态也会散落在不同入口。我的任务是参与把数据访问收敛为稳定能力。行动上，Capability 承载真正的业务动作和 Scope 校验，Tool 只负责把这些能力适配给 Agent，并统一返回成功、部分、截断或错误信封；检索结果同时保留策略、来源和覆盖事实。结果上，运行时不需要知道 SQLite、FTS5 或向量库的内部调用方式，评测也可以在同一能力边界观察工具选择与返回事实，减少接口漂移和越权访问的可能。

#### 追问 2：这种分层会不会过度设计？

**追问口播（STAR）：** 场景上，小型 Demo 直接从模型函数访问数据库确实更快，但本项目需要处理真实大规模消息、引用复核、会话持久化和可重复评测，边界不清会直接破坏证据链。我的任务是判断哪些抽象有真实失败依据。行动上，项目只保留固定、可组合的少量能力，不引入万能 Evidence Tool、候选状态机或大量专用分析工具；每一层都对应一个可测试责任，例如授权、检索、执行或提交。结果上，额外结构换来了可定位的失败边界，同时通过薄接口和统一应用入口控制复杂度，没有为了形式完整继续堆叠无证据抽象。

### Q3（高频）：原始聊天数据如何保证一致性、幂等性和可追溯性？

**主问口播（STAR）：** 场景上，聊天导出可能重复导入、记录顺序不稳定，也可能出现来源、会话、成员或消息字段不完整；如果直接写搜索索引，后续无法判断某条结果从哪次导入而来。我的任务是参与建立可重放的数据入口。行动上，项目先解析来源格式，再映射到来源、会话、身份、成员关系、消息和导入批次等统一对象；持久化由 SQLite 事务管理，稳定身份与去重原则用于识别同一事实，批次摘要和错误记录保留 provenance。关键词与语义索引都从 Canonical Store 派生。结果上，导入失败会显式暴露，重复运行不会靠静默吞错维持表面成功，查询证据能够回到规范化消息与来源批次。

#### 追问 1：为什么 SQLite 能承担这个规模？

**追问口播（STAR）：** 场景上，当前系统是单机研究与评测形态，核心约束是查询可复现、事务明确和部署简单，而不是先满足分布式高并发。我的任务是参与选择与阶段目标相符的存储。行动上，项目用 SQLite 保存规范化事实、会话、Trace 和 Evaluation 数据，关键词走 FTS5，语义向量放在独立 sqlite-vec 派生库；不同语义仍由独立 store 或表契约隔离。结果上，真实 Snapshot 已承载 473,236 条消息并完成检索与 185 次 Development 评测。这个结论证明当前阶段可用，但不等于已经验证生产并发、跨机容灾或长期容量上限。

#### 追问 2：语义索引为什么要独立于主库？

**追问口播（STAR）：** 场景上，Embedding 模型、维度、池化、归一化和分块算法任一变化都会让旧向量失去可比性；如果向量与事实混为一体，索引异常可能污染主数据认知。我的任务是参与把派生状态显式化。行动上，项目为语义索引保存完整身份与构建状态，并在独立数据库记录向量和可恢复的消息范围；查询前检查 missing、building、failed、stale、partial 等状态，不自动回退到关键词结果冒充语义成功。结果上，索引可以从 Canonical Store 重建，失败边界对用户和 Trace 可见，模型配置变化也能通过 identity 判断是否需要重建。

### Q4（高频）：关键词检索和语义检索如何取舍？

**主问口播（STAR）：** 场景上，团队容易把语义检索视为关键词检索的升级版，但真实数据表明两者解决的问题不同。我的任务是参与建立可验证的策略边界，而不是凭偏好选型。行动上，项目保留独立关键词与语义工具：精确术语、可枚举谓词和明确实体优先利用 FTS5，表达改写和概念相似问题可以尝试向量通道，必要时再恢复相邻上下文。结果上，模块评测中关键词在 10 个 exhaustive/corpus predicate query 上 Recall@10 为 33/33，而语义在同 scope 为 12/33；target scope 上两者也各有未命中。因此我的结论是语义是互补通道，当前证据不支持“全面优于”或“稳定提升”的表述。

#### 追问 1：为什么不马上加 reranker 或 fusion？

**追问口播（STAR）：** 场景上，观察到语义召回和排序问题后，最直觉的动作是叠加重排或融合，但这会同时改变召回、排序、成本和解释边界。我的任务是参与遵守 failure-driven 的改进顺序。行动上，项目先通过 GT、逐调用排名与 Failure Artifact 区分“根本没召回”和“已经召回但排在 K 之后”，并保留 provider failure 与记录深度不足的独立类别。结果上，post-fix 评测能确认四个 ranking failure 的相关消息位于 14 到 29 名，而不是模糊归为召回失败。下一步应先扩大人工验证样本，再设计单变量候选方案和退出条件。

#### 追问 2：Context Expansion 为什么不算一种独立排名策略？

**追问口播（STAR）：** 场景上，上下文扩展是围绕已命中消息恢复前后对话，它没有针对用户 query 重新对全库排序。如果把它的结果和 direct search 混在一起，就可能把“靠邻近关系找回”误报成检索排名命中。我的任务是参与修正这一观测语义。行动上，评测投影按单次直接检索保留 rank、strategy 和调用标识，并把上下文调用从 ranking surface 排除；上下文是否补齐则用 required-context 和 evidence 指标单独判断。结果上，召回、排序和上下文恢复三个问题可以独立归因，避免一种后处理动作污染另一种指标。

### Q5（高频）：语义分块采用什么思路，为什么？

**主问口播（STAR）：** 场景上，单条群聊消息通常过短且依赖上下文，整段会话又会把多个主题混在同一向量中。我的任务是参与在语义完整性和精确定位之间建立第一版折中。行动上，项目采用时间感知的父块与较小子块：父块保存局部会话语境，子块承担向量匹配，命中后再通过规范化消息范围恢复可引用内容；索引身份同时记录模型、维度、池化、归一化和分块版本。结果上，向量结果可以回到 canonical message，而不是把不可复核的 chunk 文本直接当最终证据。具体窗口与阈值仍属于待评测参数，不把第一版默认值包装成最优解。

#### 追问 1：如何处理 stale 或构建中索引？

**追问口播（STAR）：** 场景上，主库新增消息后，旧向量索引可能仍能返回结果，但这些结果无法代表当前 Snapshot；构建中断也可能只留下部分向量。我的任务是参与让这种不一致显式可见。行动上，系统把索引状态与身份作为查询前置条件，对缺失、构建中、失败、陈旧和部分状态分别建模；查询不通过自动关键词 fallback 假装成功，而是返回可观察错误或 coverage 限制，并保留日志与 Trace。结果上，调用方能区分“没有相关消息”和“语义索引当前不可用”，运维也能基于 Canonical Store 执行重建和完整性验证。

#### 追问 2：为什么最终引用不用 chunk id？

**追问口播（STAR）：** 场景上，chunk 是为检索构造的派生单元，边界会随算法调整；如果答案长期引用 chunk id，索引重建后引用可能失效，而且用户无法直接回到原始聊天。我的任务是参与保证证据稳定性。行动上，语义命中先携带 canonical range metadata，再从事实库恢复具体消息及会话、作者和时间快照；最终 Citation 只绑定规范化 Message 或结构化结果来源。结果上，检索参数可以演进而不改变用户证据的身份，用户也能在有界上下文中复核原消息。

### Q6（高频）：Data Access Scope 如何保证权限边界？

**主问口播（STAR）：** 场景上，Agent 可能根据自然语言自主选择工具，如果权限只写在 prompt 或入口过滤里，后续工具调用和结构化 SQL 都可能绕过限制。我的任务是参与把授权做成执行时硬边界。行动上，项目将允许的会话与时间范围建模为 Scope，由每个 Capability 在真正读取数据时与请求过滤条件求交；查询条件只是本次搜索偏好，不能扩大授权。即使开放只读 SQL，也必须先通过语句类型、schema 和 Scope 检查。结果上，引用校验还能再次确认来源属于当前 Scope，形成数据访问与答案提交的双重约束，而不是依赖模型“记得不要越权”。

#### 追问 1：Scope 和 Filter 的区别是什么？

**追问口播（STAR）：** 场景上，两者都可能包含会话和时间字段，容易在实现中被混用。我的任务是参与明确语义优先级。行动上，我把 Scope 理解为调用者授予的最大可见集合，Filter 是用户本次希望缩小的查询条件；实际读取范围只能是两者交集。Filter 缺失不能解释为全库权限，Filter 指向 Scope 外也不能扩权。结果上，能力层可以统一计算有效会话和时间区间，测试也能覆盖“无过滤、范围内过滤、越界过滤”三类行为，避免把便利参数误当授权依据。

#### 追问 2：只读 SQL 为什么仍然危险，项目如何处理？

**追问口播（STAR）：** 场景上，只禁止写操作并不足够，任意只读 SQL 仍可能访问未授权表、绕过会话条件或返回无界大结果。我的任务是参与限定结构化查询面。行动上，项目只暴露可查询 schema，对 SQL 做只读、结构和 Scope 校验，并在工具层施加有界返回；Agent 不需要自己写 LIMIT 才能获得 bounded 保障，但违规查询会显式失败。结果上，结构化分析保留了 SQLite 的表达能力，同时没有把底层数据库变成绕过 Tool Contract 的后门，错误也会进入 Trace 而不是静默改写。

### Q7（高频）：Router 和 Planner 分别做什么？

**主问口播（STAR）：** 场景上，简单查询如果都先生成计划会增加延迟，复杂调查如果完全没有规划又容易遗漏步骤；但让 Router 决定工具、让 Planner 直接执行又会产生重复控制面。我的任务是参与设计最小职责划分。行动上，Router 只把请求分成标准执行和计划执行，采用规则优先并在需要时调用模型；计划路径只额外生成一次经校验和清洗的软指导。两条路径最终都进入同一个 Agent Runtime，由模型根据可用工具和证据决定实际动作。结果上，执行链差异可通过 forced route 和 Trace 验证，Runtime 不需要维护两套工具循环。

#### 追问 1：为什么 Route 失败时允许 conservative default？

**追问口播（STAR）：** 场景上，路由只是复杂度门，不应该因为分类器不可用就让整个问答链失去基本服务；同时也不能默默吞掉故障。我的任务是参与确定有限且可解释的退路。行动上，系统优先保留已产生的规则决策，没有可用判断时才选择标准执行，并把路由失败和采用的默认决策写入可观测事件。这个行为只影响是否先生成软计划，不改变权限和工具契约。结果上，核心查询仍能进入统一 Runtime，工程师也能从 Trace 区分正常标准路径与路由失败后的保守路径。

#### 追问 2：为什么第一版不做 automatic replan？

**追问口播（STAR）：** 场景上，自动重规划会引入新的触发条件、Planner 状态、成本和循环终止问题，而当时没有 Failure Case 证明一次软计划不足是主因。我的任务是参与控制无依据复杂度。行动上，第一版只在复杂路由后调用一次 Planner，对输出做确定性校验和清洗，然后交给 Runtime 自主执行；工具失败、预算和最终合成仍由同一运行时处理。结果上，计划质量可以独立评测，失败不会被多次重规划掩盖。只有后续 Trace 证明特定失败可由重规划稳定修复，才值得新增该机制与覆盖测试。

### Q8（高频）：Agent Runtime 怎样控制轮次、预算和错误？

**主问口播（STAR）：** 场景上，开放式工具调用容易出现无限循环、重复检索、token 膨胀，或者在未知异常后继续生成看似成功的答案。我的任务是参与把 Agent Loop 变成有界执行。行动上，Runtime 为一次请求注入 Scope、会话历史、工具面、轮次与结果预算，记录每个 Tool Round；已知工具契约错误可以结构化返回给模型修正，未知异常、取消或 provider 失败则进入明确终态。接近工具轮次边界时系统保留最终合成机会，但最终文本仍要经过 AnswerArtifact 校验。结果上，运行时行为可预测、可观测，失败不会被静默包装成正常答案。

#### 追问 1：什么错误可以恢复，什么错误必须失败？

**追问口播（STAR）：** 场景上，如果所有异常都重试，代码缺陷和数据错误会被隐藏；如果任何工具参数错误都终止，模型又失去自我修正机会。我的任务是参与划定恢复边界。行动上，只有已知、契约化且对模型可解释的 Tool Contract Error 会以结构化错误信封返回，让模型调整输入；未知 Python 异常、持久化错误、provider 终止和无法证明安全的状态都显式失败。结果上，恢复机制有清晰触发条件，Trace 保留失败所有权，后续测试可以针对真实 Failure Case 增加处理，而不是提前堆砌重试与兼容分支。

#### 追问 2：为什么工具结果还要做 bounded projection？

**追问口播（STAR）：** 场景上，真实聊天检索结果可能很长，若原样塞回模型，会迅速消耗上下文，也可能让无关正文和内部字段泄漏到推理面。我的任务是参与在信息充分和预算之间建立可审计边界。行动上，工具结果先转成包含必要摘要、来源句柄、coverage、truncated 与 limitation 的有界投影，同时记录原始结果事实供 Finalizer 与 Trace 使用；截断不会被省略，而是显式成为答案限制。结果上，模型上下文可控，最终引用仍能回到完整 canonical source，并且 Evaluation 能区分“没有结果”和“有结果但投影被截断”。

### Q9（高频）：证据与 Citation 是怎样保证可信的？

**主问口播（STAR）：** 场景上，大模型可以生成格式正确但来源不存在的引用，也可能复用历史会话中的旧消息或引用 Scope 外数据。我的任务是参与把引用从文本装饰变成提交契约。行动上，系统要求模型输出结构化 claim、source handle 和 citation binding；Finalizer 只从当前 Run 的 Tool Result 建立可用来源索引，再校验引用存在、关系合法、属于当前授权范围，并水合成带会话、作者和精确时间的展示快照。任何 unresolved 或 invalid citation 都会阻止正常提交并保留诊断。结果上，答案和 Evidence Panel 共用同一结构化 Artifact，用户可以沿引用回到原始消息，而不是只相信模型概述。

#### 追问 1：为什么不能用历史会话里已经出现过的证据？

**追问口播（STAR）：** 场景上，历史答案中的来源可能来自不同 Scope、不同数据版本或已经失效的运行上下文；若默认复用，就无法证明本次答案确实重新取得了证据。我的任务是参与保证运行级 provenance。行动上，当前提交只认可本 Run 工具结果中出现的来源，历史对话只作为语言上下文，不自动进入可引用集合；若需要复核旧事实，Agent 必须在当前授权范围内再次调用能力取得来源。结果上，每个 AnswerArtifact 都能独立审计，权限变化或索引更新不会被旧引用绕过，代价是会增加一次必要的检索动作。

#### 追问 2：引用校验失败时为什么不自动修复？

**追问口播（STAR）：** 场景上，自动把不存在的来源替换成“最相似消息”看似能提高 valid answer，但会改变模型 claim 与证据的语义关系，甚至制造错误背书。我的任务是参与坚持错误透明。行动上，Finalizer 对可证明的结构化解析和来源水合做有限恢复，但不会凭相似度发明引用；无法解析、越权或 unresolved 的绑定进入明确 finalization error，并保留诊断信息。结果上，valid answer 指标可能不如宽松系统好看，却能确保每次成功提交都有可解释证据，失败也能形成 Regression Case。

### Q10（高频）：系统如何处理“没有结果”和覆盖不完整？

**主问口播（STAR）：** 场景上，一次检索没有命中不等于全库没有相关信息，尤其当范围被限制、结果被截断或索引不可用时，直接回答“没有”会产生危险假阴性。我的任务是参与建立零结果的证明边界。行动上，系统区分 no-result、partial coverage、truncated 和 terminal failure；只有完整空检索记录能够支持可验证零结果，时间浏览还需要 Host-owned coverage 事实。模型输出零结果时，Finalizer 会检查当前工具记录是否真的提供充分证据。结果上，评测可以分别计算 false-zero guard、verified zero 和 coverage accuracy，避免把“未知”包装成“确定不存在”。

#### 追问 1：partial 和 truncated 有什么区别？

**追问口播（STAR）：** 场景上，两者都会让用户拿不到全部信息，但原因不同，混在一个状态里会让补救动作失焦。我的任务是参与拆开两个轴。行动上，partial 表示查询对目标范围的覆盖本身不完整，例如索引状态或时间扫描不能证明全覆盖；truncated 表示系统找到了更多候选，但受返回预算限制只展示一部分。两者可以同时出现，也可以分别出现。结果上，答案可以准确说明限制，Evaluation 也分别检查 coverage status 与 truncation，工程师据此决定修索引覆盖、查询方式还是结果预算。

#### 追问 2：为什么 coverage 必须由 Host 产出？

**追问口播（STAR）：** 场景上，如果 Evaluation 根据若干检索调用自行猜测覆盖范围，就可能忽略生产链路的合并规则、游标状态或最大覆盖单元，最终测到的是评测器自己的逻辑。我的任务是参与保持生产事实唯一。行动上，coverage 由应用主链路在 AnswerArtifact 中产出，Evaluation 只读取并比较 GT 期望；若 Artifact 缺失 coverage，就报告 unavailable 或 coverage failure，而不是在评测层重算。结果上，评测与生产契约保持同源，发现缺口时修 projection 或主链路，不用测试代码替系统圆结论。这也使历史报告的不可用分母能够被准确解释，不会把缺失事实默认算成成功或失败。

### Q11（高频）：Trace 体系如何支持全链路故障定位？

**主问口播（STAR）：** 场景上，一次查询会跨 Router、Planner、Runtime、Tool、Retrieval、Evidence 和持久化，普通日志很难重建顺序，也无法确定某个错误属于哪个操作。我的任务是参与建立统一事件边界。行动上，系统为每次查询分配 Trace，在同一序列中追加 versioned event，并用 operation 和 causality 字段表达开始、结果与失败所有权；normal/debug profile 控制 payload，SQLite 保存结构化事件，再投影出时间线、时延、工具轮次和终态。结果上，评测能通过 trace_id 回到执行证据，用户界面也能展示受控的过程信息，问题定位不依赖在多份文本日志中猜时间顺序。

#### 追问 1：为什么采用 append-only，而不是更新一条状态记录？

**追问口播（STAR）：** 场景上，覆盖更新只能看到最终状态，会丢失中间工具调用、状态转换和第一次失败；并发事件还可能相互覆盖。我的任务是参与保留完整执行历史。行动上，每个事件只追加，不修改已有事实，顺序号保证 Trace 内排序，终态和投影由事件集合派生；事件版本允许后续 schema 演进。结果上，工程师可以复盘“先检索、再扩展、后终结失败”的真实过程，Evaluation 也能读取同一原始事实。代价是需要控制 payload 与保留策略，而长期 retention 仍应根据真实运行校准。

#### 追问 2：如何避免 Trace 变成巨量日志或泄露聊天正文？

**追问口播（STAR）：** 场景上，群聊正文可能敏感，工具结果也可能很大；若把所有对象完整写入 Trace，会带来存储、隐私和调试噪声。我的任务是参与建立有界采集。行动上，项目使用 normal/debug capture policy，只记录故障归因和指标所需的结构化字段，对模型投影、参数和结果摘要做长度与数量限制，必要时将完整本地文本日志与版本化事件分开。结果上，Trace 能支撑调用序列、coverage、candidate 和 failure ownership 分析，又不把全量聊天复制到每个事件；具体 retention 与脱敏规则仍需真实部署要求补充。

### Q12（高频）：Evaluation 体系如何保证可复现和不自欺？

**主问口播（STAR）：** 场景上，Agent 评测容易受数据版本、索引、模型、prompt、工具面和外部服务波动影响，单次总分很难说明原因。我的任务是参与构建可审计实验底座。行动上，项目用 Case Bundle 保存 query、Scope、GT、provenance 与 completeness；用 Snapshot 和 Environment Gate 固定数据与索引身份；用 Controlled Variant 明示工具和上下文差异；运行走真实应用入口，并同时报告完成率、有效答案率、质量指标、不可用原因与 Failure Artifact。结果上，已完成 47 条人工裁决 GT，其中 37 条 Development 进入五 Variant、185 次真实运行；Holdout 尚未生成，因此没有宣称泛化结果。

#### 追问 1：为什么 Calibration 不进入 headline denominator？

**追问口播（STAR）：** 场景上，Calibration Case 用来调试 GT schema、Runner、Projection 和 Metrics，本身参与了测量系统的建设；如果把它和最终 Development 指标合并，会让被反复观察的样本影响 headline。我的任务是参与区分测量校准与系统评价。行动上，项目把 10 条 Calibration 作为 substrate 校准切片，37 条 Development 作为当前质量基线，并计划在系统冻结后再构造隔离的 Holdout。结果上，47 条人工裁决可以作为数据治理事实，但 headline 分母仍明确是 37，不通过改口径把校准样本包装成更多独立评测数据。这样面试时既能展示 GT 治理规模，也不会误导对方认为 47 条都属于未参与校准的独立质量样本。

#### 追问 2：为什么 D full-system 不能和 A 的差值归因给语义检索？

**追问口播（STAR）：** 场景上，full-system 同时开放七种工具，而最小基线只开放关键词检索，两者之间存在多个变量；直接用 D 减 A 会把结构化查询、时间浏览、上下文工具和模型选择行为都算成语义收益。我的任务是参与保证因果解释。行动上，项目设计 A、B、C、C2 的逐步 Variant：B 对 A 只增加语义面，C 对 B 只恢复自动上下文，C2 对 C 只增加显式上下文工具；D 只报告绝对全系统结果。结果上，paired comparison 可以说明特定差异，但当前样本显示收益并不稳定，所以不把差值写成简历 uplift。

### Q13（高频）：请复盘一次最有价值的根因定位。

**主问口播（STAR）：** 场景上，早期 Failure Attribution 把多个检索调用的命中全局合并排序，还把上下文恢复调用当成直接排名，因此 retrieval miss、ranking failure 和记录深度不足的分类不可靠。我的任务是参与复现并修正测量主链路。行动上，我从 failure artifact 回到原始调用事实，确认局部 rank 在投影时丢失；随后按单次 direct search 保留 rank、strategy、调用标识和消息身份，排除 context 调用，并明确只有相关消息被观察到且 rank 大于 10 才属于排序失败。结果上，修复后的真实运行定位出 4 个 ranking failure，相关 rank 为 14 到 29，记录深度不足为 0，回归测试锁定了分类边界。

#### 追问 1：为什么这是 Evaluation bug，不是 Retrieval bug？

**追问口播（STAR）：** 场景上，相关消息在真实 direct search 中已经有原始局部排名，错误发生在评测投影将多个调用合并并重新解释之后。我的任务是参与判断修改边界，避免为了让指标好看去改检索算法。行动上，我对照原始工具事实、Failure Artifact 与分类器，确认召回结果本身未变化，修复只恢复正确观测和类别定义，没有改 GT、索引、query 或 ranking。结果上，这项工作提高的是 measurement substrate 的可信度；系统仍有真实 retrieval miss 和 ranking failure，并继续在报告中暴露。这个边界也保证冻结后的质量基线不会被一次测量层修复悄悄改写。

#### 追问 2：如何证明修复不是针对四个样例写特判？

**追问口播（STAR）：** 场景上，如果按 case id 或具体 rank 写分支，短期能改对报告，却无法处理下一批数据。我的任务是参与提炼通用不变量。行动上，修复围绕“rank 属于单次 direct search”“context 不属于 ranking surface”“top-K 是否可观察由投影深度决定”三条规则实现，并用合成回归覆盖多调用、上下文调用、K 内、K 外和记录截断。结果上，真实 post-fix 数据自然得到 4 个排序失败与 12 个召回未命中，而不是由样例名单驱动；全量工程检查也保持通过。更重要的是，新增检索策略只要遵守同一观测契约，就能复用分类逻辑，不需要再增加策略私有判断。

### Q14（中高频）：再讲一次异步生命周期故障是怎样定位的。

**主问口播（STAR）：** 场景上，benchmark 对多个 Variant 顺序运行时出现 `Event loop is closed`，表面像 provider 不稳定，但错误集中在客户端复用与关闭阶段。我的任务是参与复现真实执行路径并确认所有权。行动上，我沿 CLI、应用上下文和 provider client 生命周期检查，发现同步 Application context 内部为每个 Variant 分别创建 event loop，同一个 async client 跨 loop 使用，退出时又可能在另一 loop 关闭。修复将 benchmark 主入口异步化，让应用进入、全部 Variant 请求、结果投影和退出共享同一 event loop，同时保留同步包装给非 CLI 调用方。结果上，生命周期回归被固定，185-run 的 raw、Evaluation Store 与 Trace 可以对齐。

#### 追问 1：为什么不在每个 Variant 前重新创建 client？

**追问口播（STAR）：** 场景上，重新创建 client 可能绕开跨 loop 错误，但会改变连接复用、资源释放和 Variant 运行条件，也掩盖应用生命周期设计不一致。我的任务是参与修主链路而不是打补丁。行动上，我把边界提升到一次 benchmark execution：它本来就应由同一个应用上下文拥有 provider 生命周期，因此让所有异步操作共享 loop；Variant 只改变受控配置，不改变基础设施创建方式。结果上，实验条件更一致，关闭路径也只有一个所有者，避免为每个 Variant 引入特殊资源分支。

#### 追问 2：修复后为什么仍有大量 provider failure？

**追问口播（STAR）：** 场景上，post-fix clean run 中 C、C2、D 出现集中 timeout 和 connection error，容易被误解为生命周期修复失败。我的任务是参与用 Trace 区分代码缺陷与外部可用性窗口。行动上，我检查失败时间、终态和首个模型轮次，发现 114 条 provider failure 中 106 条来自后三个 Variant，C2 与 D 多数没有首个 model turn；独立 recovery smoke 中 D 又能完成。结果上，证据更支持外部 provider availability observation，而不是相同的跨 loop 根因复发，所以报告保留失败，不添加无依据 retry、fallback 或 Variant 特判，也不拿该批次重算质量 uplift。等 provider 条件稳定后，应在同一冻结身份上重新观察，而不是混用两批不同环境的分母。

### Q15（高频收尾）：项目当前最大局限和下一步是什么？

**主问口播（STAR）：** 场景上，项目已经有完整工程链路和 Development 基线，但不能把“链路完整”误说成“效果已经充分验证”。我的任务是参与明确下一阶段的证据缺口。行动上，我会把局限分三类：质量上，语义召回、上下文恢复、coverage 与 finalization 仍有 Failure Case；实验上，Holdout 尚未生成，部分 paired 样本很小，不能宣称泛化或稳定提升；产品上，真实用户任务、线上反馈、SLO、隐私和长期 retention 还缺数据。结果上，下一步应先完成 Gate 3 评审与隔离 Holdout，再基于分类后的 failure 选择一个最小候选改动，固定环境做单变量评测，而不是同时调参、加重排和重试。

#### 追问 1：如果只能优先做一件事，你选什么？

**追问口播（STAR）：** 场景上，当前候选优化很多，但没有 Holdout 就难以判断 Development 上的调整是否过拟合。我的任务是选择能最大化后续决策质量的工作。行动上，我会优先完成 Gate 3 review，并按既定隔离流程生成、人工裁决 Holdout，冻结数据、索引、代码、provider 与 Variant 后只运行一次正式对照；同时保持 Development failure 作为诊断集，不反复用 Holdout 调参。结果上，后续任何 reranker、query rewrite、chunk 或 context 方案都能获得可信的退出条件，简历也可以从“Development 工程事实”升级为有边界的泛化证据。若 Holdout 不支持候选方案，就保留失败并回到根因，而不是修改样本口径。

#### 追问 2：你会怎样把这个项目讲得既有亮点又不过度包装？

**追问口播（STAR）：** 场景上，AI 项目最容易用“提升准确率、稳定性更高”掩盖分母和证据不足。我的任务是参与建立可防守的表达。行动上，我会重点讲五个通用能力：统一事实底座、分层检索、受约束 Agent 执行、证据化答案与可复现评测；数字只使用 473,236 条消息、47 条人工 GT、37 个 Development Case、五 Variant 和 185 次真实运行，并紧跟适用范围。对语义效果、context uplift、Holdout 和线上价值主动说明未证实。结果上，面试官既能看到系统复杂度与根因定位能力，也能清楚区分已完成事实、测量结论和下一步假设。

## 4. 源码证据索引

| 主题 | 关键路径与内部符号 | 对应正文位置 |
| --- | --- | --- |
| Canonical 数据模型 | `src/trivae/data/model.py`：`SourceDescriptor`、`ChatSession`、`CanonicalMessage`、`ImportBatchSummary` | Q2、Q3；统一数据底座 bullet |
| 导入与事务 | `src/trivae/data/ingestion/importer.py`：`SharedImporter`；`src/trivae/data/storage/sqlite.py`：`SQLiteCanonicalStore`、`MessageWriteResult` | Q3 |
| 关键词检索 | `src/trivae/retrieval/lexical.py`：`LexicalRetrieval`；`src/trivae/data/storage/sqlite_lexical.py`：`SQLiteLexicalIndex` | Q4 |
| 语义索引契约 | `src/trivae/retrieval/semantic/contracts.py`：`EmbeddingModelIdentity`、`SemanticIndexIdentity`、`SemanticIndexStatusReport` | Q3、Q5 |
| 语义构建与查询 | `src/trivae/retrieval/semantic/builder.py`：`SemanticIndexBuilder`；`retrieval.py`：`SemanticRetrieval`；`embedding.py`：`SentenceTransformerEmbeddingProvider` | Q4、Q5 |
| 结构化 SQL | `src/trivae/retrieval/sql.py`：`SQLReadOnlyViolation`、`SQLScopeViolation`、`SchemaResult`、`SQLQueryResult` | Q2、Q6 |
| Scope 契约 | `src/trivae/capabilities/contracts.py`：`ExecutionScope`；`src/trivae/capabilities/scope.py`：`scope_filters`、`effective_sessions`、`effective_start`、`effective_end` | Q6 |
| Capability/Tool 注册 | `src/trivae/capabilities/registry.py`：`CapabilityRegistry`；`src/trivae/capabilities/tools.py`：`SearchMessagesTool`、`LexicalSearchTool`、`SemanticSearchTool`；`src/trivae/bootstrap/application.py`：`create_application` | Q2、Q6、Q8 |
| 路由 | `src/trivae/query/router.py`：`RouteDecision`、`RuleRouter` | Q7 |
| 计划 | `src/trivae/query/planner.py`：`Plan`、`PlanStep`、`SoftPlanner`、`render_plan_guidance` | Q7 |
| Query 编排 | `src/trivae/query/orchestrator.py`：`QueryOrchestrator`、`run` | Q1、Q7、Q8 |
| Runtime 与预算 | `src/trivae/query/runtime/openai_adapter.py`：`OpenAIAgentsRuntimeAdapter`；`src/trivae/query/runtime/budget.py`：`ToolResultBudgetConfig`、`ToolResultBudgetPolicy` | Q8 |
| 证据与引用 | `src/trivae/query/evidence.py`：`AnswerArtifact`、`CitationBinding`、`ToolResultRecord`、`validate_answer_artifact`、`finalize_answer_gracefully` | Q9、Q10 |
| 查询终结 | `src/trivae/query/completion.py`：`CompletionResult`、`invoke_completion`、`complete_text`；`src/trivae/query/orchestrator.py`：`QueryOrchestrator.run` | Q8、Q9、Q10 |
| 会话持久化 | `src/trivae/conversation/contracts.py`：`Conversation`、`ConversationMessage`；`sqlite.py`：`SQLiteConversationStore` | Q9 |
| 流式协议 | `src/trivae/query/streaming.py`：`AnswerArtifactDeltaParser`、`QueryStreamAdapter`；`src/trivae/interfaces/web/streaming.py`：`QueryStopRegistry`、`stream_query` | Q8；项目简介 |
| 应用入口 | `src/trivae/bootstrap/application.py`：`TrivaeApplication`、`create_application` | Q2、Q12、Q14 |
| Trace 契约与采集 | `src/trivae/observability/contracts.py`：`NormalizedQueryEvent`、`StoredTrace`；`src/trivae/observability/collector.py`：`TraceCollector`、`TraceOperationContext` | Q11 |
| Trace 持久化与投影 | `src/trivae/observability/sqlite.py`：`SQLiteTraceStore`；`projection.py`：`project_trace` | Q11、Q13、Q14 |
| Evaluation Case/Run | `src/trivae/evaluation/contracts.py`：`EvaluationCaseBundle`、`DatasetSnapshot`、`EvaluationRun`、`PairedComparison` | Q12 |
| Controlled Variant | `src/trivae/evaluation/variant.py`：`ControlledVariant`、`variant_diff`；`evaluation/variants/` | Q12 |
| Benchmark 编排 | `src/trivae/evaluation/benchmark/orchestrator.py`：`BenchmarkOrchestrator`、`run_benchmark_async` | Q12、Q14 |
| Failure 分类 | `src/trivae/evaluation/benchmark/failures.py`：`_recorded_direct_hits`、`evaluate_case_failure`、`ACCEPTANCE_HIT_K` | Q4、Q10、Q13 |
| 评测事实 | `evaluation/reports/resume-benchmark-v1-fact-index.md`；`.trellis/tasks/08-30-evaluation-benchmark-v1/validation.md` | 所有指标相关 bullet、Q12-Q15 |
| Failure Regression | `tests/test_benchmark.py`、`tests/test_cli.py`、`.trellis/spec/project/problems/benchmark-root-cause-closure.md` | Q13、Q14 |

## 5. 面试前必须补齐的个人事实

- 我实际负责了哪些模块：设计、实现、评测、文档、协作分别到什么边界？
- 哪些 commit、PR、任务记录可以证明每条 bullet，哪些只是团队成果？
- 是否存在真实用户、上线环境、使用频率或反馈？若无，不写上线与业务收益。
- 473,236 条消息与 14 个来源的采集、脱敏、授权边界由谁负责？是否允许在公开简历出现？
- 576 passed 是历史任务记录；投递前是否需要在当前 commit 重新运行并更新数字？
- Holdout 若后续完成，必须记录生成时序、人工审核、冻结版本与最终分母，不能只摘最好指标。
