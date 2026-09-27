# Planner-only blind review packet

Reviewer: ______   Date: ______

For each pair choose A better / B better / indifferent / uncertain and give a short reason.
Check entity preservation, scope discipline, tool relevance, incremental value, evidence alignment,
context/relation quality, redundancy, overplanning, and parse/provider failures separately.
These are soft plans only; no Runtime answer or human adjudication is implied.

## pu-dependent-mattpocock-r1

User Query: 先找到有人分享 mattpocock 的 skills 仓库并说明用法的消息，再沿这条讨论找到后续评价。分别说明推荐/用法与反馈是什么；如果反馈没有明确的亲自使用依据，请标明这一限制。

### Plan A

```text
Title: mattpocock skills 仓库分享与后续反馈
Intent: mixed
1. Goal: 用精确词锚定 mattpocock 的 skills 仓库分享消息，并提取其中推荐语与用法说明。
   Suggested tools: lexical_search
   Evidence needed: 包含 mattpocock 与 skills 仓库名称或链接的消息; 该消息中的推荐理由、使用方式或操作路径
2. Goal: 围绕已定位的分享消息读取同一讨论的后续回复，区分推荐/用法与后续评价，并检查评价是否包含亲自使用依据。
   Suggested tools: get_message_context
   Evidence needed: 分享消息的 message_id 及所在会话; 后续回复中的评价、反馈或使用体验; 反馈中是否明确提及亲自使用、尝试或实际效果
Success criteria: 找到至少一条分享 mattpocock skills 仓库并说明用法的消息; 说明该消息中的推荐或用法内容; 沿同一讨论找到后续评价或反馈; 明确区分推荐/用法与后续反馈; 若反馈缺少亲自使用依据，则标明该限制
```

### Plan B

```text
Title: mattpocock skills 仓库分享与反馈追踪
Intent: mixed
1. Goal: 检索 mattpocock skills 仓库的分享消息及用法说明
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 候选消息ID; 发送者; 时间戳; 仓库/用法原文片段
2. Goal: 获取目标消息上下文，定位同一讨论的后续回复
   Suggested tools: get_message_context
   Evidence needed: 目标消息上下文; 回复关系; 时间顺序
3. Goal: 沿讨论提取后续评价或反馈，区分推荐/用法与反馈
   Suggested tools: get_message_context, lexical_search, semantic_search
   Evidence needed: 后续评价消息ID; 评价原文片段; 评价立场
4. Goal: 核查反馈是否含亲自使用依据，无依据则标注限制
   Suggested tools: get_message_context, lexical_search
   Evidence needed: 亲自使用表述; 或缺失亲自使用依据的说明
5. Goal: 汇总推荐/用法与反馈，标注证据缺口
   Suggested tools: (none)
   Evidence needed: 汇总项对应的消息ID; 限制说明
Success criteria: 找到至少一条分享 mattpocock skills 仓库并说明用法的消息; 沿该讨论定位到后续评价/反馈，并有消息ID或原文片段; 分别输出推荐/用法与反馈内容; 反馈若无明确亲自使用依据，明确标注该限制; 区分直接证据与推断，不把无依据反馈当作亲测结论
```

Decision: ______
Reason: ______

## pu-dependent-mattpocock-r2

User Query: 先找到有人分享 mattpocock 的 skills 仓库并说明用法的消息，再沿这条讨论找到后续评价。分别说明推荐/用法与反馈是什么；如果反馈没有明确的亲自使用依据，请标明这一限制。

### Plan A

```text
Title: mattpocock skills 仓库分享与后续反馈计划
Intent: mixed
1. Goal: 定位分享 mattpocock skills 仓库并说明用法的原始消息。
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 消息ID、时间、作者; 仓库链接或名称; 用法/推荐原文
2. Goal: 读取该消息上下文，提取推荐理由与具体用法。
   Suggested tools: get_message_context
   Evidence needed: 前后文片段; 推荐/用法原句
3. Goal: 沿同一讨论串查找后续评价与反馈。
   Suggested tools: get_message_context
   Evidence needed: 后续消息ID、作者、内容; 是否构成反馈
4. Goal: 区分推荐/用法与反馈，并标注反馈是否含亲自使用依据。
   Suggested tools: (none)
   Evidence needed: 两类摘录对照; 亲自使用依据缺失标记
Success criteria: 找到并引用分享 mattpocock skills 仓库的原始消息; 清晰说明推荐/用法与后续反馈分别是什么; 每条结论均有消息证据支撑; 若反馈没有亲自使用依据，必须明确标注该限制
```

### Plan B

```text
Title: mattpocock skills 仓库分享与反馈
Intent: mixed
1. Goal: 定位含 mattpocock 与 skills 仓库的原始分享消息，并提取分享者说明的用法。
   Suggested tools: lexical_search
   Evidence needed: mattpocock/skills 仓库名称或链接; 推荐或用法说明原文; 消息ID与会话ID
2. Goal: 围绕原始分享消息读取同会话上下文，找出后续评价并区分推荐/用法与反馈。
   Suggested tools: get_message_context
   Evidence needed: 同一讨论中的回复、引用或追问; 后续评价原文; 评价是否指向亲自使用
3. Goal: 若同会话上下文不足，再检索同一 mattpocock skills 仓库的后续评价，并核验是否有亲自使用依据。
   Suggested tools: lexical_search
   Evidence needed: 后续评价消息ID; 亲自使用、试用或体验后的直接表述; 仅有兴趣、收藏、转述或热度更新的反例标记
Success criteria: 明确给出推荐/用法消息及分享者所述用途。; 给出沿该讨论找到的后续评价。; 区分推荐/用法内容与后续反馈。; 若反馈无明确亲自使用依据，标注该限制。; 若存在亲自使用反馈，引用其直接体验表述。
```

Decision: ______
Reason: ______

## pu-dependent-mattpocock-r3

User Query: 先找到有人分享 mattpocock 的 skills 仓库并说明用法的消息，再沿这条讨论找到后续评价。分别说明推荐/用法与反馈是什么；如果反馈没有明确的亲自使用依据，请标明这一限制。

### Plan A

```text
Title: mattpocock skills 仓库分享与后续评价
Intent: mixed
1. Goal: 检索提及 mattpocock、skills 仓库、分享或用法的消息
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 消息ID; 消息文本; 时间戳; 作者
2. Goal: 读取命中消息上下文，定位原始分享及用法说明
   Suggested tools: get_message_context
   Evidence needed: 原始分享消息; 用法描述原文; 所在讨论串标识
3. Goal: 沿该讨论串查找后续回复与评价
   Suggested tools: get_message_context
   Evidence needed: 后续消息ID; 回复关系; 评价文本
4. Goal: 归纳推荐/用法与反馈，并核查反馈是否有亲自使用依据
   Suggested tools: get_message_context
   Evidence needed: 推荐或用法表述; 反馈表述; 亲自使用依据或缺失说明
Success criteria: 找到分享 mattpocock skills 仓库的原始消息; 提取该仓库用法说明; 找到同一讨论中的后续评价; 分别总结推荐/用法与反馈; 标明反馈是否缺少亲自使用依据
```

### Plan B

```text
Title: mattpocock skills 仓库分享与后续反馈追踪
Intent: mixed
1. Goal: 定位明确分享或推荐 mattpocock 的 skills 仓库并说明其用法的原始消息，保留实体名 mattpocock、skills、仓库及用法或推荐语境。
   Suggested tools: lexical_search
   Evidence needed: 包含 mattpocock 与 skills 仓库的原始消息; 该消息中关于仓库用途或使用方式的描述
2. Goal: 围绕已定位的分享消息调取同一会话的后续上下文，找出针对该仓库的后续评价或反馈，并检查反馈是否明确声称亲自使用或试用。
   Suggested tools: get_message_context
   Evidence needed: 分享消息所在会话的后续回复或讨论; 后续评价的原文; 反馈中是否有亲自使用或试用的明确依据，或仅有兴趣或转述
Success criteria: 找到至少一条分享 mattpocock skills 仓库的消息并说明其推荐或用法; 沿该讨论找到后续评价或反馈; 分别呈现推荐/用法与反馈内容; 若反馈未明确声称亲自使用，则标注该限制
```

Decision: ______
Reason: ______

## dev-context-archify-r1

User Query: archify 这个工具有人用过吗？反馈如何？

### Plan A

```text
Title: archify 工具使用与反馈
Intent: mixed
1. Goal: 定位提及 archify 的消息，识别直接分享、推荐或使用讨论
   Suggested tools: lexical_search
   Evidence needed: 包含 archify 的原始消息
2. Goal: 围绕相关消息获取上下文，查找回复中的 firsthand 使用反馈或评价
   Suggested tools: get_message_context
   Evidence needed: 回复中提及实际使用体验或反馈的语句
Success criteria: 找到至少一条提及 archify 的消息; 识别出明确表示使用过 archify 的 firsthand 陈述; 收集到对 archify 的正面或负面反馈
```

### Plan B

```text
Title: archify 使用反馈调查
Intent: mixed
1. Goal: 定位所有提及 archify 的消息
   Suggested tools: lexical_search
   Evidence needed: 匹配消息ID; 发言者; 时间戳; 原文片段
2. Goal: 补充语义相关但未精确匹配的讨论
   Suggested tools: semantic_search
   Evidence needed: 语义相近消息ID; 上下文线索
3. Goal: 读取命中消息上下文，确认是否实际使用及反馈
   Suggested tools: get_message_context
   Evidence needed: 前后文; 使用场景; 评价正负向
4. Goal: 归纳反馈主题与典型意见
   Suggested tools: (none)
   Evidence needed: 重复出现的优点/缺点; 争议点; 用户身份或角色
Success criteria: 至少找到一条明确提及 archify 的消息，或确认完整检索无命中; 区分“用过/没用过/仅听说”等使用状态; 提取并归类正面、负面、中性反馈; 给出带消息ID或时间戳的证据引用; 若证据不足，明确说明无法判断
```

Decision: ______
Reason: ______

## dev-context-archify-r2

User Query: archify 这个工具有人用过吗？反馈如何？

### Plan A

```text
Title: archify 使用反馈调查
Intent: evidence
1. Goal: 用精确词 archify 检索所有提及，锚定该工具名。
   Suggested tools: lexical_search
   Evidence needed: 提及 archify 的消息ID、会话、发送者、时间、原文片段
2. Goal: 对直接分享、推荐、邀请或实际使用讨论的命中消息，读取同会话上下文，捕获回复与反馈。
   Suggested tools: get_message_context
   Evidence needed: 同会话回复、使用体验、评价、问题、后续反应
3. Goal: 从上下文中判定是否有人实际使用，并归纳反馈类型；区分亲自使用与仅兴趣或二手推荐。
   Suggested tools: (none)
   Evidence needed: 实际使用证据（试用/日常使用描述）; 正面/负面/中性反馈原话; 兴趣或推荐与 firsthand 的区分
Success criteria: 至少定位到一条明确提及 archify 的原始消息; 能回答是否有人用过：列出实际使用描述或明确说明无 firsthand 证据; 能归纳反馈：正面、负面或中性评价及来源; 引用消息ID、会话、发送者、时间作为证据; 区分亲自使用与仅感兴趣或二手推荐
```

### Plan B

```text
Title: archify 使用与反馈检索
Intent: search
1. Goal: 在群聊中检索 archify 的提及
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 包含 archify 的消息片段、作者、时间
2. Goal: 提取高相关消息的上下文与讨论脉络
   Suggested tools: get_message_context
   Evidence needed: 前后文、是否亲身使用、具体评价
3. Goal: 归类反馈为正面、负面、中性及使用场景
   Suggested tools: (none)
   Evidence needed: 分类后的反馈要点与对应消息
4. Goal: 汇总回答：是否有人用过及反馈如何
   Suggested tools: (none)
   Evidence needed: 带引用的结论
Success criteria: 找到并引用至少一条 archify 相关消息，或明确说明未找到; 区分亲身使用反馈与转述/猜测; 归纳主要反馈主题（正面、负面、中性）; 结论基于可追溯消息，不臆测使用情况
```

Decision: ______
Reason: ______

## dev-context-archify-r3

User Query: archify 这个工具有人用过吗？反馈如何？

### Plan A

```text
Title: archify 使用反馈调查
Intent: evidence
1. Goal: 定位提及 archify 的原始消息，识别直接分享、推荐或使用讨论。
   Suggested tools: lexical_search
   Evidence needed: 包含 archify 的消息及其作者、时间、会话
2. Goal: 围绕相关 archify 消息读取同会话上下文，检查回复、后续反馈和 firsthand 经验。
   Suggested tools: get_message_context
   Evidence needed: 回复内容、使用体验、反馈或明确无反馈
Success criteria: 找到提及 archify 的原始讨论; 区分实际使用反馈与仅推荐/兴趣; 给出可引用的反馈摘要或说明无相关证据
```

### Plan B

```text
Title: archify 使用反馈核查
Intent: mixed
1. Goal: 定位群聊中所有 archify 直接提及
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 包含 archify 的消息原文; 提及者与时间戳
2. Goal: 扩展检索拼写变体及相关讨论
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 变体或相关命中; 使用与反馈相关措辞
3. Goal: 读取命中消息前后文，确认是否实际使用及反馈对象
   Suggested tools: get_message_context, get_recent_messages
   Evidence needed: 上下文对话; 使用场景、评价与结论
4. Goal: 归纳使用者、反馈主题与代表性发言
   Suggested tools: execute_sql, get_schema
   Evidence needed: 去重用户列表; 正负面反馈分类; 代表性原文
Success criteria: 列出至少一条直接提及 archify 的消息，或明确说明无命中; 区分“实际使用”与“仅听说/询问”; 给出反馈摘要，含正负面要点与代表发言; 若证据不足，标注不确定性
```

Decision: ______
Reason: ______

## pu-aggregate-utc-types-r1

User Query: 按 UTC 时间算，2026-08-15 的 text 消息和 reply 消息各有多少条？

### Plan A

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

### Plan B

```text
Title: 2026-08-15 UTC text/reply 消息计数
Intent: summary
1. Goal: 确认消息表、消息类型字段及 UTC 时间字段，并确认 text/reply 的取值表示
   Suggested tools: get_schema
   Evidence needed: messages 表字段与关系; 消息类型字段及 text/reply 取值; 时间戳字段与 UTC 单位
2. Goal: 按 UTC 日期 2026-08-15 过滤，并按消息类型分组统计 text 与 reply 的消息数
   Suggested tools: execute_sql
   Evidence needed: 2026-08-15 UTC 当天的 text 消息计数; 2026-08-15 UTC 当天的 reply 消息计数
Success criteria: 明确 2026-08-15 的 UTC 起止时间边界; 给出 text 消息的整数计数; 给出 reply 消息的整数计数; 两个计数均来自消息表在指定 UTC 日期范围内的确定性聚合
```

Decision: ______
Reason: ______

## pu-aggregate-utc-types-r2

User Query: 按 UTC 时间算，2026-08-15 的 text 消息和 reply 消息各有多少条？

### Plan A

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

### Plan B

```text
Title: UTC text vs reply counts for 2026-08-15
Intent: comparison
1. Goal: Inspect the exposed schema to identify the canonical message table, the message-type field distinguishing text from reply, and the timestamp column usable for UTC day filtering.
   Suggested tools: get_schema
   Evidence needed: canonical message table name; message type or reply indicator column; timestamp column and UTC handling
2. Goal: Run one bounded SQL aggregation that counts messages grouped by text versus reply for the UTC day 2026-08-15.
   Suggested tools: execute_sql
   Evidence needed: count for text messages on 2026-08-15 UTC; count for reply messages on 2026-08-15 UTC
Success criteria: A SQL result returns the text message count for UTC 2026-08-15; A SQL result returns the reply message count for UTC 2026-08-15; The time window is treated as UTC 2026-08-15; The aggregation is scoped to the canonical message table; No additional retrieval is used to reconfirm a complete deterministic count
```

Decision: ______
Reason: ______

## pu-aggregate-utc-types-r3

User Query: 按 UTC 时间算，2026-08-15 的 text 消息和 reply 消息各有多少条？

### Plan A

```text
Title: UTC 2026-08-15 text 与 reply 消息计数
Intent: comparison
1. Goal: 获取消息表结构，确认消息类型字段和 UTC 时间戳字段。
   Suggested tools: get_schema
   Evidence needed: 消息表名; 类型字段; 时间戳字段及单位
2. Goal: 先检索 UTC 2026-08-15 窗口内的近期消息，确认是否有消息及类型取值。
   Suggested tools: get_recent_messages
   Evidence needed: 窗口内消息样本或完整空窗口; text/reply 对应类型值
3. Goal: 若窗口非空，用 SQL 按类型统计 UTC 2026-08-15 的消息条数。
   Suggested tools: execute_sql
   Evidence needed: text 计数; reply 计数; UTC 起止毫秒/秒边界
Success criteria: UTC 2026-08-15 起止边界正确计算。; 消息类型字段中 text 与 reply 的取值已确认。; 分别报告 text 和 reply 在当日 UTC 的条数。; 若 get_recent_messages 返回完整空窗口，则计数为 0 且无需额外 SQL 复核。; 统计仅覆盖 UTC 2026-08-15 且未混入其他类型。
```

### Plan B

```text
Title: UTC 2026-08-15 text 与 reply 消息计数
Intent: summary
1. Goal: 检查 schema，确认消息表、时间戳字段及 text/reply 类型或回复关联的判定方式。
   Suggested tools: get_schema
   Evidence needed: 消息表结构; 时间戳字段; text/reply 类型或 reply 关联字段
2. Goal: 用一次范围受限 SQL 按 UTC 2026-08-15 统计 text 和 reply 消息条数。
   Suggested tools: execute_sql
   Evidence needed: text 消息计数; reply 消息计数; UTC 日界过滤条件
Success criteria: 给出 2026-08-15 UTC 范围内 text 消息条数。; 给出 2026-08-15 UTC 范围内 reply 消息条数。; 计数使用 UTC 全日边界，且由确定性聚合得出。
```

Decision: ______
Reason: ______

## dev-zero-empty-3-r1

User Query: 按 UTC 时间算，2025-08-26 这天大家有没有发言？都在聊什么？

### Plan A

```text
Title: UTC 2025-08-26 发言与话题回顾
Intent: summary
1. Goal: 拉取 UTC 2025-08-26 全天范围内的近期消息，判断是否存在发言并查看讨论内容。
   Suggested tools: get_recent_messages
   Evidence needed: 该 UTC 日期窗口内的消息记录；若为空则确认无发言; 非空消息的主题、关键词与对话片段
Success criteria: 明确回答 2025-08-26 UTC 当天是否有发言; 若有发言，概述主要讨论话题; 不额外做重复的计数或检索验证
```

### Plan B

```text
Title: UTC 2025-08-26 发言与话题查询
Intent: mixed
1. Goal: 用 get_recent_messages 拉取 UTC 2025-08-26 全天窗口，先判断是否为空
   Suggested tools: get_recent_messages
   Evidence needed: 该 UTC 日期内的消息记录；空窗口即无发言证据
2. Goal: 若非空，抽样并概括当天聊天主题
   Suggested tools: get_message_context, semantic_search, lexical_search
   Evidence needed: 消息内容样本; 话题或关键词摘要
3. Goal: 若非空且需量化，用 SQL 统计当天消息量、参与者与话题分布
   Suggested tools: execute_sql, get_schema
   Evidence needed: UTC 日期过滤后的计数; 参与者或话题聚合结果
Success criteria: 明确说明 UTC 2025-08-26 是否有发言; 若有发言，列出当天主要讨论话题; 结论基于消息窗口或统计证据，而非仅 SQL 计数
```

Decision: ______
Reason: ______

## dev-zero-empty-3-r2

User Query: 按 UTC 时间算，2025-08-26 这天大家有没有发言？都在聊什么？

### Plan A

```text
Title: UTC 2025-08-26 发言与讨论主题
Intent: mixed
1. Goal: 获取 UTC 2025-08-26 全天消息窗口，判断是否有发言。
   Suggested tools: get_recent_messages
   Evidence needed: UTC 2025-08-26 的消息记录; 完整空窗口或非空窗口
2. Goal: 若有消息，归纳主要讨论主题与关键词。
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 消息文本样本; 主题或高频关键词
3. Goal: 对代表性消息提取上下文，避免断章取义。
   Suggested tools: get_message_context
   Evidence needed: 相关消息前后文
4. Goal: 仅当需要精确统计或复杂筛选时，再查表补充；完整空窗口不追加 SQL 复核。
   Suggested tools: get_schema, execute_sql
   Evidence needed: 表结构; 按 UTC 日期筛选的计数或样本
Success criteria: 明确回答 UTC 2025-08-26 是否有发言; 若有发言，概括主要讨论主题与内容; 结论基于消息文本或完整空窗口，而非仅 SQL 计数; 不重复用 SQL 验证完整空窗口
```

### Plan B

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

Decision: ______
Reason: ______

## dev-zero-empty-3-r3

User Query: 按 UTC 时间算，2025-08-26 这天大家有没有发言？都在聊什么？

### Plan A

```text
Title: UTC 2025-08-26 发言与话题概览
Intent: mixed
1. Goal: 用 UTC 全天窗口拉取消息，确认 2025-08-26 是否有发言，并从命中内容归纳主要话题。
   Suggested tools: get_recent_messages
   Evidence needed: UTC 2025-08-26 00:00:00 至 2025-08-27 00:00:00 的消息记录; 非空窗口中的消息内容与发送者; 空窗口用于确认零发言
Success criteria: 明确回答该 UTC 日是否有发言。; 若有发言，概括主要讨论话题。; 时间范围严格按 UTC 2025-08-26 完整日界定。
```

### Plan B

```text
Title: UTC 2025-08-26 当日发言与话题
Intent: mixed
1. Goal: 用 get_recent_messages 拉取 UTC 2025-08-26 全天消息，确认是否存在发言。
   Suggested tools: get_recent_messages
   Evidence needed: UTC 当日窗口内消息记录; 消息时间戳与内容
2. Goal: 若窗口为空，则直接判定当日无发言；若有消息，则归纳主要讨论话题。
   Suggested tools: (none)
   Evidence needed: 空结果或非空消息集合; 话题关键词或摘要依据
3. Goal: 必要时用 get_message_context 查看代表消息上下文，避免断章取义。
   Suggested tools: get_message_context
   Evidence needed: 相关消息前后文
Success criteria: 明确回答 UTC 2025-08-26 是否有发言; 若有发言，概括当日主要讨论话题; 结论基于 get_recent_messages 的完整 UTC 当日窗口; 空结果时以完整空检索作为零结果证据，不另做 SQL 计数确认; 说明时间口径为 UTC
```

Decision: ______
Reason: ______

## dev-temporal-30d-r1

User Query: 最近30天群里的主要话题有哪些？

### Plan A

```text
Title: 最近30天群主要话题总结
Intent: summary
1. Goal: 获取最近30天的群消息，按时间分布与发送者线索识别高频讨论和候选话题。
   Suggested tools: get_recent_messages
   Evidence needed: 时间窗口内消息文本; 消息时间戳; 发送者分布
2. Goal: 对候选话题用语义检索补充同义或换词表达的相关消息，合并为稳定主题并过滤仅一次提及。
   Suggested tools: semantic_search
   Evidence needed: 候选话题相关消息; 语义相近表达; 消息时间戳
3. Goal: 对代表性话题线程追溯上下文，确认讨论焦点、持续性和主要答复方向。
   Suggested tools: get_message_context
   Evidence needed: 代表消息的回复与上下文; 话题延续证据
Success criteria: 输出最近30天群内3至7个主要话题; 每个话题至少有消息文本或上下文证据支持; 区分高频主题与一次性提及; 仅依据最近30天窗口内的消息
```

### Plan B

```text
Title: 最近30天群主要话题归纳
Intent: summary
1. Goal: 获取最近30天群消息，确认窗口内数据是否充足
   Suggested tools: get_recent_messages
   Evidence needed: 最近30天消息列表或空窗口标记
2. Goal: 从消息样本中提取高频词、短语和候选话题
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 高频词或短语; 语义相似消息簇
3. Goal: 合并同义或相近话题，并保留代表性消息
   Suggested tools: semantic_search, get_message_context
   Evidence needed: 话题聚类结果; 代表性消息及上下文
4. Goal: 按消息量或参与度对主要话题排序
   Suggested tools: execute_sql, get_schema
   Evidence needed: 各候选话题消息量或参与度统计; 排序依据
Success criteria: 明确列出最近30天群主要话题; 话题按热度或参与度排序; 每个话题有消息量或代表性消息支撑; 结论限定在最近30天时间窗口内; 结论仅基于群消息证据
```

Decision: ______
Reason: ______

## dev-temporal-30d-r2

User Query: 最近30天群里的主要话题有哪些？

### Plan A

```text
Title: 最近30天群内主要话题概览
Intent: summary
1. Goal: 检索最近30天群消息，确认窗口内是否有消息及总体活跃度
   Suggested tools: get_recent_messages
   Evidence needed: 最近30天消息列表; 时间范围与消息数量
2. Goal: 按关键词与语义聚类提取高频话题
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 高频词或短语; 代表性消息片段; 话题聚类结果
3. Goal: 补充关键话题的上下文，避免断章取义
   Suggested tools: get_message_context
   Evidence needed: 相关消息前后文; 关键讨论脉络
Success criteria: 明确列出最近30天内的主要话题（通常3-5个）; 每个话题有来自该时间窗的消息证据支持; 若窗口内无消息，则直接说明无近期讨论而非推测话题; 话题概括简洁且不混入30天外内容
```

### Plan B

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

Decision: ______
Reason: ______

## dev-temporal-30d-r3

User Query: 最近30天群里的主要话题有哪些？

### Plan A

```text
Title: 近30天群聊主要话题总结
Intent: summary
1. Goal: 先拉取最近30天群消息，确认时间窗口内是否有消息及基本规模
   Suggested tools: get_recent_messages
   Evidence needed: 最近30天消息集合; 消息数量或空窗口结论
2. Goal: 若存在消息，识别高频词、反复出现的实体与讨论片段，归纳候选话题
   Suggested tools: semantic_search, lexical_search, get_message_context
   Evidence needed: 高频关键词或短语; 代表性消息或上下文片段
3. Goal: 合并同类候选话题，形成最近30天主要话题列表及简要说明
   Suggested tools: (none)
   Evidence needed: 话题归并结果; 每个话题的代表性证据
Success criteria: 明确最近30天窗口内是否有消息; 列出主要话题并给出简要描述; 每个主要话题尽量有消息证据支持; 若窗口为空，直接说明无消息可总结
```

### Plan B

```text
Title: 最近30天群主要话题
Intent: summary
1. Goal: 获取最近30天群消息，识别高频词、重复讨论与活跃主题候选
   Suggested tools: get_recent_messages
   Evidence needed: 时间范围内消息文本; 时间戳; 发送者或回复关系
2. Goal: 用候选主题的语义表达扩展检索，合并同义近义讨论并区分偶发提及
   Suggested tools: semantic_search
   Evidence needed: 不同措辞的相关消息; 主题聚合证据
3. Goal: 对关键主题词做精确检索并抽取同会话上下文，确认代表性讨论
   Suggested tools: lexical_search, get_message_context
   Evidence needed: 关键词命中记录; 消息上下文; 代表性消息ID
Success criteria: 列出最近30天内3-5个主要话题; 每个话题有至少多条消息或持续讨论支撑; 区分主要话题与一次性提及; 给出代表性消息或时间线索
```

Decision: ______
Reason: ______

## dev-lexical-forge-r1

User Query: 有没有人分享过一个把需求拆成任务并生成文档的 agent 项目 forge？

### Plan A

```text
Title: 查找 forge agent 项目分享
Intent: search
1. Goal: 用关键词 forge 与 agent、需求拆解、任务、文档等组合检索历史消息
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 包含 forge 的消息; 项目名称或链接; 功能描述
2. Goal: 若命中，读取消息上下文确认分享内容和分享者
   Suggested tools: get_message_context
   Evidence needed: 消息上下文; 分享者; 时间戳
3. Goal: 若未命中，用语义检索扩大查找需求拆解、任务生成、文档生成类 agent 项目
   Suggested tools: semantic_search
   Evidence needed: 语义相近项目分享; 项目描述
4. Goal: 汇总是否有相关分享，并列出关键证据
   Suggested tools: (none)
   Evidence needed: 有/无结论; 关键消息引用
Success criteria: 确认是否有人分享过 forge 项目; 若存在，给出分享消息或上下文证据; 若不存在，说明检索范围和主要关键词
```

### Plan B

```text
Title: 查找 forge 需求拆解与文档生成 agent 项目的分享
Intent: search
1. Goal: 用精确词检索是否有成员分享过名为 forge 的 agent 项目，锚定项目名及需求拆任务、生成文档等描述。
   Suggested tools: lexical_search
   Evidence needed: 包含 forge 的分享或推荐消息; 消息中同时出现 agent、需求拆任务、生成文档、项目链接或仓库名等线索
2. Goal: 对命中分享消息取同会话上下文，确认是否为直接分享或推荐，而非仅转述或无关提及。
   Suggested tools: get_message_context
   Evidence needed: 分享者消息原文; 链接、仓库或项目介绍上下文; 若有回复，回复是否确认该项目描述
Success criteria: 找到至少一条直接分享或推荐名为 forge 的 agent 项目消息; 证据能对应 forge 与需求拆任务并生成文档的描述; 可给出分享者、消息上下文及可用链接或仓库名；若无命中，则说明未发现相关分享
```

Decision: ______
Reason: ______

## dev-lexical-forge-r2

User Query: 有没有人分享过一个把需求拆成任务并生成文档的 agent 项目 forge？

### Plan A

```text
Title: Forge agent 项目分享检索
Intent: search
1. Goal: 以实体 forge 为主锚，检索其作为“需求拆任务并生成文档”的 agent 项目的分享消息。
   Suggested tools: lexical_search
   Evidence needed: 包含 forge 且指向需求拆解、任务生成或文档生成 agent 项目的原始消息
2. Goal: 对命中的分享消息读取同会话上下文，确认分享者身份、项目用途及是否有人回应或反馈。
   Suggested tools: get_message_context
   Evidence needed: 相关分享消息的回复、补充说明或使用反馈
Success criteria: 确定是否至少有一条分享消息提到 forge 作为需求拆任务并生成文档的 agent 项目; 识别分享者或分享会话，并区分原始分享与后续回应; 若存在讨论，说明项目名称、功能描述及相关反馈；若不存在，给出基于检索结果的判断
```

### Plan B

```text
Title: 查找 Forge 项目分享
Intent: search
1. Goal: 用关键词检索 Forge、需求拆任务、生成文档、agent 项目等提及
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 匹配消息 ID; 消息文本; 分享链接或项目名
2. Goal: 查看命中消息上下文，确认是否分享项目及其用途
   Suggested tools: get_message_context
   Evidence needed: 上下文消息; 分享者; 项目描述
3. Goal: 若需确认分享者身份，定位成员信息
   Suggested tools: find_members
   Evidence needed: 成员 ID/名称
4. Goal: 若无直接命中，扩大语义检索相关表述
   Suggested tools: semantic_search
   Evidence needed: 相关消息; 近似项目名或关键词
Success criteria: 找到或排除 Forge 项目的分享消息; 确认项目是否将需求拆成任务并生成文档; 给出分享者与消息位置; 零结果时说明检索范围与关键词
```

Decision: ______
Reason: ______

## dev-lexical-forge-r3

User Query: 有没有人分享过一个把需求拆成任务并生成文档的 agent 项目 forge？

### Plan A

```text
Title: 查找 Forge agent 项目分享
Intent: search
1. Goal: 用精确实体词 Forge 检索包含 agent、项目、需求拆解、文档生成等上下文的分享、推荐或介绍消息。
   Suggested tools: lexical_search
   Evidence needed: 命中消息中明确出现 Forge 作为 agent 项目名; 消息文本包含将需求拆成任务并生成文档的分享、推荐或介绍
2. Goal: 对 Forge 直接命中消息取同会话上下文，确认是否有人实际分享、推荐或讨论该项目，而非仅重复提及。
   Suggested tools: get_message_context
   Evidence needed: 分享、推荐、邀请或使用讨论的首条消息; 后续回复对 Forge 项目功能的确认
3. Goal: 若 Forge 精确匹配不足，再按“需求拆任务并生成文档的 agent 项目”概念召回可能未写 Forge 的相关分享。
   Suggested tools: semantic_search
   Evidence needed: 概念相关消息中是否包含 Forge 或同类项目分享; 能否补充回答是否有人分享过此类项目
Success criteria: 能回答是否有人分享过名为 Forge 的 agent 项目; 能给出至少一条相关分享消息或说明未找到; 证据以直接分享或推荐消息为准，不以无关重复提及充数
```

### Plan B

```text
Title: 查找 forge agent 项目分享
Intent: search
1. Goal: 识别 forge、agent、需求拆解、文档生成等关键词及别名
   Suggested tools: semantic_search, lexical_search
   Evidence needed: 匹配消息ID、作者、时间; 项目名称或链接
2. Goal: 检索群内是否有人分享该 agent 项目
   Suggested tools: semantic_search, lexical_search
   Evidence needed: 分享内容片段; forge 与需求拆解/文档生成的关联
3. Goal: 对命中消息读取上下文并确认成员身份
   Suggested tools: get_message_context, find_members
   Evidence needed: 前后文; 分享者信息
4. Goal: 若限定近期，先检查最近消息窗口
   Suggested tools: get_recent_messages
   Evidence needed: 完整空窗口或命中记录
Success criteria: 找到至少一条相关分享消息，或确认无匹配结果; 说明 forge 是否被描述为将需求拆成任务并生成文档; 引用消息ID、作者、时间等可验证信息; 区分直接证据与推测
```

Decision: ______
Reason: ______

## dev-cite-archify-r1

User Query: archify 项目最近发展怎么样？star 数有被提到过吗？

### Plan A

```text
Title: archify 近期动态与 star 提及核查
Intent: mixed
1. Goal: 获取最近消息窗口，确认 archify 相关讨论和 star 数提及是否存在
   Suggested tools: get_recent_messages
   Evidence needed: 最近时间窗口消息; archify 关键词; star 数关键词
2. Goal: 在最近窗口内检索 archify 与 star 相关消息
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 命中消息; 发布时间; 讨论主题
3. Goal: 对命中消息拉取上下文，核实发展情况与 star 数是否被具体讨论
   Suggested tools: get_message_context
   Evidence needed: 上下文片段; star 数值或提及方式
4. Goal: 若最近窗口完整为空，则记录无相关消息，不额外用 SQL 仅复核空结果
   Suggested tools: (none)
   Evidence needed: 完整空窗口结果
5. Goal: 汇总 archify 近期发展要点，并回答 star 数是否被提到
   Suggested tools: (none)
   Evidence needed: 近期动态摘要; star 提及结论
Success criteria: 给出 archify 近期发展的简要结论; 明确 star 数是否被提及及提及方式; 结论基于最近消息或检索命中证据; 若窗口为空，说明无相关记录即可
```

### Plan B

```text
Title: archify 项目近期发展与 star 提及
Intent: mixed
1. Goal: 检索包含 archify 的原文消息，定位项目相关讨论。
   Suggested tools: lexical_search
   Evidence needed: 提及 archify 的消息及其时间、内容
2. Goal: 围绕关键 archify 消息读取同会话上下文，检查近期进展与 star 数讨论。
   Suggested tools: get_message_context
   Evidence needed: 后续回复或补充中的发展状态; star 数相关的直接表述
Success criteria: 找到 archify 项目相关消息; 识别近期发展动态或版本更新; 确认 star 数是否被提及及具体说法
```

Decision: ______
Reason: ______

## dev-cite-archify-r2

User Query: archify 项目最近发展怎么样？star 数有被提到过吗？

### Plan A

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

### Plan B

```text
Title: Archify 项目近期发展与 star 数提及核查
Intent: mixed
1. Goal: 检索近期窗口内与 Archify 项目相关的消息，判断最近发展动态。
   Suggested tools: get_recent_messages
   Evidence needed: 带时间戳的近期 Archify 相关消息
2. Goal: 在消息中搜索 Archify 与 star/GitHub stars/star 数等关键词的明确提及。
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 包含 star 表述且指向 Archify 的消息片段
3. Goal: 对可能提及 star 数的命中消息获取上下文，确认是否真的在说 Archify 及具体数值。
   Suggested tools: get_message_context
   Evidence needed: 命中消息前后文、作者与时间
4. Goal: 汇总近期发展并给出 star 数是否被提到的结论。
   Suggested tools: (none)
   Evidence needed: 近期动态摘要与 star 提及/未提及的证据
Success criteria: 给出 Archify 近期发展的简明摘要并附时间范围; 明确回答 star 数是否被提到过; 若有提及，给出具体 star 数和上下文; 若未提及，说明检索依据而非无证据断言
```

Decision: ______
Reason: ______

## dev-cite-archify-r3

User Query: archify 项目最近发展怎么样？star 数有被提到过吗？

### Plan A

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

### Plan B

```text
Title: archify 近期发展与 star 提及查询计划
Intent: mixed
1. Goal: 获取最近消息窗口，检查 archify 相关讨论与 star 提及。
   Suggested tools: get_recent_messages
   Evidence needed: 完整空窗口即证明近期无 archify 消息和 star 提及; 非空窗口中的 archify 消息
2. Goal: 在消息中检索 archify 项目进展与 star 关键词。
   Suggested tools: lexical_search, semantic_search
   Evidence needed: 包含 archify 的消息片段; 包含 star 或 star 数的消息片段
3. Goal: 对命中的 archify 消息获取上下文，确认发展情况与 star 数说法。
   Suggested tools: get_message_context
   Evidence needed: 消息前后文; 发展描述或 star 数具体值/说法
Success criteria: 返回 archify 近期发展的证据摘要; 明确回答 star 数是否被提及; 若提及则给出具体消息依据；若未提及则给出检索范围
```

Decision: ______
Reason: ______

## pu-rank-utc-session-r1

User Query: 按 UTC 时间算，2026-08-15 哪个会话发言最多？请给出会话 ID 和消息数。

### Plan A

```text
Title: UTC 2026-08-15 会话消息数排名
Intent: comparison
1. Goal: 检查 SQLite 物理 schema，定位消息表、会话 ID 字段、时间戳字段及单位，以便按 UTC 日期做聚合。
   Suggested tools: get_schema
   Evidence needed: messages 表与会话/消息关系; 时间戳列及单位; 会话 ID 列名
2. Goal: 执行一次有界只读 SQL：过滤 UTC 2026-08-15 全天消息，按会话 ID 分组计数，降序取消息数最多的会话。
   Suggested tools: execute_sql
   Evidence needed: UTC 2026-08-15 各会话消息数; 最大消息数对应 session_id 和 count
Success criteria: 返回一个会话 ID 和该会话在 UTC 2026-08-15 的消息数; 时间窗口严格为 UTC 2026-08-15 00:00:00.000 至 2026-08-15 23:59:59.999; 结果按消息数降序且仅取最大会话; 不再用额外检索或 SQL 复核该确定性排名
```

### Plan B

```text
Title: UTC 2026-08-15 会话消息量排名
Intent: comparison
1. Goal: 确认消息表中的会话 ID 字段与 UTC 时间戳字段
   Suggested tools: get_schema
   Evidence needed: 消息表结构; 会话 ID 字段; 时间戳字段
2. Goal: 按 UTC 日期 2026-08-15 聚合各会话消息数并取最多者
   Suggested tools: execute_sql
   Evidence needed: 会话 ID; 消息数; UTC 日期边界
3. Goal: 检查并列与当日消息覆盖范围，确认结果稳健
   Suggested tools: execute_sql
   Evidence needed: 并列会话; 当日总消息数; 排名前几项
Success criteria: UTC 时间范围明确为 2026-08-15 00:00:00 至 2026-08-16 00:00:00; 给出消息数最多的会话 ID; 给出该会话当天的消息数; 若有并列，列出并列会话或说明; 计数来自消息表且按会话正确分组
```

Decision: ______
Reason: ______

## pu-rank-utc-session-r2

User Query: 按 UTC 时间算，2026-08-15 哪个会话发言最多？请给出会话 ID 和消息数。

### Plan A

```text
Title: UTC 2026-08-15 会话发言量排行
Intent: summary
1. Goal: 查看 messages 表结构中会话 ID 与时间戳字段，确认 UTC 过滤字段和单位
   Suggested tools: get_schema
   Evidence needed: 会话 ID 字段名; 消息时间戳字段名与单位
2. Goal: 按 UTC 2026-08-15 聚合各会话消息数并取最大值，返回会话 ID 和消息数
   Suggested tools: execute_sql
   Evidence needed: 单日 UTC 过滤后的分组计数; 消息数最大的会话 ID; 对应的消息数
Success criteria: 按 UTC 日期 2026-08-15 过滤消息; 按会话 ID 分组统计消息数; 返回发言最多的会话 ID; 返回该会话的消息数
```

### Plan B

```text
Title: 2026-08-15 UTC 会话消息数排名
Intent: comparison
1. Goal: 获取消息表结构，确认 UTC 时间字段和会话 ID 字段。
   Suggested tools: get_schema
   Evidence needed: 消息表字段包含 timestamp/time 与 conversation/session/chat id
2. Goal: 按 UTC 日 2026-08-15 过滤消息，按会话分组统计消息数并降序取第一。
   Suggested tools: execute_sql
   Evidence needed: UTC 范围 2026-08-15T00:00:00Z 到 2026-08-16T00:00:00Z; 按会话分组计数; ORDER BY 消息数 DESC 的第一行
3. Goal: 输出最多发言会话的 ID 和消息数。
   Suggested tools: (none)
   Evidence needed: 会话 ID; 消息数
Success criteria: 给出 2026-08-15 UTC 消息数最多的会话 ID; 给出该会话消息数; 统计口径为 UTC 自然日且可复核
```

Decision: ______
Reason: ______

## pu-rank-utc-session-r3

User Query: 按 UTC 时间算，2026-08-15 哪个会话发言最多？请给出会话 ID 和消息数。

### Plan A

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

### Plan B

```text
Plan unavailable: {'code': 'invalid_output', 'message': 'planner completion was truncated by the provider', 'detail_code': 'provider_length', 'parse_stage': 'provider_response', 'diagnostic': None, 'exception_type': None}
```

Decision: ______
Reason: ______
