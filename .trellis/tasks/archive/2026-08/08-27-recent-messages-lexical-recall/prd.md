# PRD: Real Failure-Driven Fix — Temporal Browsing Tool + Chinese Lexical Recall

## Background

真实用户同题对比（Trivae vs ChatLab）暴露两个独立 Failure：

### Failure A：Temporal overview 缺失 Temporal Browsing 能力

- 用户问题：`最近一两天大家都在讨论什么有价值的内容`
- Trivae trace `trace-87060c18023e46988f4df09a98a27f9f`：
  - semantic_search ×3（猜主题）→ lexical_search("推荐") → get_schema，全部 0 hit
  - terminal_outcome=failed, model_turns=4, tool_calls=5, ~75s, final_answer unavailable
- 根因链：
  1. Prompt 未提供 temporal browsing 路径，模型只能"猜测最近聊了什么再搜索猜测"；
  2. 该访问模式对 lexical/semantic retrieval 天然不匹配；
  3. Stage 1.4 ADR §11 的 reopen trigger 已被真实 Failure Case 触发。
- ChatLab 参考实现（本地 `/Users/anontokyo/Downloads/Project/Learn/ChatLab/packages/tools/src/definitions/recent-messages.ts`）：`get_recent_messages(start_time,end_time,limit)` 一次拉取时间窗内消息 → 模型聚类总结。

### Failure B：中文 lexical_search 可疑 0-hit

- 同批数据存在 canonical message `qq:1039179741:7674201141965536638` = `"真心推荐 值得看一看"`（timestamp 1786789191000，落在查询窗口内）
- `lexical_search("推荐")` 返回 0 hits / coverage complete

## Requirements

### A. 新增 Agent-facing `get_recent_messages`

1. 输入 contract：`time_range`(relative, anchor=archive_latest) / `start_timestamp` / `end_timestamp` / `limit`；沿用现有 RelativeTimeRange；禁止 machine current time。
2. Trusted scope 由 ExecutionScope 强制；session/time 越权显式拒绝；scope 继承逻辑与 SearchMessagesCapability 同语义。
3. 排序语义：时间窗口内**先选最新 limit 条**，按自然阅读顺序（chronological ASC）返回；selection 用 DESC LIMIT N 后反转。
4. 结果复用 `StructuredMessageResult`（strategy="structured"）与统一 ToolEnvelope；messages 为完整 MessageProjection（stable identity/session/author/timestamp/content/reply/source handle）。
5. Limit 复用既有基础设施：DEFAULT=100（=DEFAULT_STRUCTURED_RESULT_LIMIT），MAX=MAX_STRUCTURED_RESULT_ITEMS(100)；canonical result > model projection 时 truncation 显式。
6. Tool 只做 temporal selection/browsing；"价值判断/聚类/总结"属 LLM synthesis。zero result = ok 非错误。
7. 进入现有 Evidence/Citation/Trace 主链路：StructuredMessageResult 在 build_tool_result_record 中已支持 → message citation 与 structured provenance 直接可用，不建第二套系统。
8. Router 不加 keyword hardcode；tool description + prompt 保证选择正确性。

### B. 修复中文 lexical recall

已确认 Root Cause（真实库诊断）：
- `LIKE '%推荐%'` 全库 1596 hits，窗口内 14 hits；FTS MATCH `"推荐"` 窗口内 **0 hits**、全库 258（仅词边界偶然命中）。
- unicode61 把连续 CJK run 存成单 token：实测 tokens `[真心推荐, 值得看一看]`；混合串更糟（`推荐这个repo` 是一个 token）。
- 目标消息 FTS row 存在、index count 一致（473236==473236，非 stale）、session/scope 无问题、escape/syntax 无问题。
- trigram tokenizer 实测对 2 字查询 MATCH=`0`（trigram 需要 ≥3 字符），且跨越词界；不可作为唯一方案。

修复方向（design.md 详述比较）：derived-index CJK bigram 归一化策略；query 侧同函数归一化；不使用 silent LIKE fallback；index 携带 strategy 版本元数据，不匹配时显式报 stale 要求 rebuild。

### Constraints

- 不新建 Runtime/Evidence/Trace/Router framework/SQL abstraction/mega-tool/hybrid_search。
- Tool 内不得调用 LLM 判定"高价值"。
- Candidate data 与 final evidence 判断分离。
- Failure attribution 不得因修复降低。
- 相对时间 anchor 保持 archive_latest。

## Acceptance Criteria

见任务根 acceptance 清单（§二十）：get_recent_messages 成为稳定首选 temporal browsing path；trace-87060c 场景 completed 且基于真实消息+可解析 citations；lexical_search("推荐") 按 bigram contract 正确召回窗口内 14 条真实 hit；URL/repo/code/error-message lexical regression 不退化；全部测试通过；真实 smoke 通过；ADR reopen 记录；interview-defense 沉淀；工作树 clean 并 commit。
