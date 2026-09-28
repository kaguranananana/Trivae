# P1 Planner blind judgments

## pu-aggregate-utc-types

Blind judgment: same

Reason: 两侧都先用 `get_schema` 确认消息类型和时间字段，再用单条 `execute_sql` 做 UTC 当日的按类型确定性聚合；都覆盖 text/reply 两个计数，也没有增加多余的检索复核。A 对时间单位和边界写得更细，B 对 UTC 日期的表达略简洁，但属于轻微表述差异，不改变计划语义质量。

## dev-context-archify

Blind judgment: A better

Reason: A 先把 `archify` 作为实体锚，明确定位直接分享、推荐、邀请或使用讨论，再沿命中消息取上下文，并明确区分亲自使用与兴趣/想尝试。B 也有命中后取上下文的主链路，但首步主要描述一般提及和声称反馈，没有同样清楚地固定直接证据关系，对兴趣或尝试意向的排除也不够明确。A 更贴合 direct hit → context 和 firsthand 限制要求。

## pu-dependent-mattpocock

Blind judgment: B better

Reason: 两侧都能先定位 `mattpocock skills` 仓库分享，再沿该消息取同会话上下文并检查亲自使用依据。A 将同一 `get_message_context` 目的拆成两次连续调用，第二次主要重复从上下文中区分反馈证据；B 在一次上下文步骤的证据要求中已覆盖后续评价、使用结果和亲自使用限制，调查链路更紧凑且没有重复检索。

## dev-zero-empty-3

Blind judgment: unjudgeable

Reason: A 标为 `No valid Plan`，因此没有可比较的 A 侧计划；按盲审规则不能把 B 的有效计划自动判为语义胜出。B 虽使用了适合完整 UTC 时间窗的 `get_recent_messages`，但这不能替代双侧比较。

Reliability reason: 单侧无有效 Plan 导致该组只能作不可判定结论，语义判断可靠性不足。

## dev-lexical-forge

Blind judgment: A better

Reason: 两侧都保留 `Forge/forge` 实体锚，先用精确词检索，再用同会话上下文确认项目描述。A 还在精确检索不足时有条件地用 `semantic_search` 按“需求拆任务并生成文档”的描述补充召回，并要求用 Forge 复核，符合只有实体路径不足时才扩展的规划指导；B 没有这条必要的受条件约束的补充路径，可能漏掉未写出项目名但描述了该项目的分享。

## pu-rank-utc-session

Blind judgment: A better

Reason: 两侧都正确采用 schema 检查加 SQL 分组聚合来求 UTC 当日会话消息数最高者。A 明确使用完整 UTC 日期边界，并要求在最高计数并列时列出并列会话或说明并列；B 的成功条件没有处理并列结果，可能在排序取最高时丢失同值会话。该差异直接影响“哪个会话”的确定性结果，不是篇幅或步骤数量差异。

## dev-temporal-30d

Blind judgment: unjudgeable

Reason: B 标为 `No valid Plan`，因此没有可比较的 B 侧计划；不能因为 A 使用了适合时间窗读取的 `get_recent_messages`，就自动判 A 语义更好。

Reliability reason: 单侧无有效 Plan，缺少双侧有效证据，无法可靠进行语义优劣判断。

## dev-cite-archify

Blind judgment: A better

Reason: A 以 `archify` 为主锚，分别检索项目近期消息和 `star/stars/星标` 的精确提及，并只在精确措辞不足时条件性补充语义召回；命中后再取上下文。B 在首个项目检索步骤中自动同时建议 lexical 与 semantic search，违反了不要机械配对两种检索的指导，也没有把语义扩展限定为精确实体路径不足时的补充。A 的检索关系更有针对性，能分别回答项目进展和 star 数是否被提及。
