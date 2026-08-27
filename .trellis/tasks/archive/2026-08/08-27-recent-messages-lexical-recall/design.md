# Design: get_recent_messages + CJK Bigram Lexical Index

## Failure A 设计

### 数据流（复用现有分层）

```text
GetRecentMessagesSDKToolAdapter (openai_tools.py, typed input)
  → GetRecentMessagesTool (_CapabilityTool envelope/trace wrapper)
    → GetRecentMessagesCapability (capabilities/recent_messages.py: scope 继承 + 相对时间解析)
      → StructuredRetrieval.retrieve_recent_messages
        → SQLiteCanonicalReadRepository.read_recent_messages (SELECT ... ORDER BY DESC LIMIT N, python reverse)
```

不新增裸 SQL；repository 实现 `_scope_where_clause` 复用。

### Input Contract

`GetRecentMessagesInput`（capabilities/contracts.py）：

- `time_range: RelativeTimeRange | Mapping | None = None`（默认 `{kind:relative,amount:2,unit:day,anchor:archive_latest}` 不在 dataclass 里做默认，而是允许全空表示"最近 2 天"？——**否**：contract 显式优先；工具 schema default 由 SDK 层注入 time_range 默认 2 days；Capability 层要求 time_range 与绝对时间戳至少给一个）
- `session_ids / start_timestamp / end_timestamp / limit`
- 校验：time_range 与绝对时间戳互斥；reversed 拒绝；limit 正整数且 ≤ max。
- 限制：`DEFAULT_RECENT_MESSAGES_LIMIT=100`、`MAX_RECENT_MESSAGES_LIMIT=MAX_STRUCTURED_RESULT_ITEMS=100`（limits.py）。

### Capability scope 语义（与 SearchMessagesCapability 一致）

- `effective_sessions`: model session_ids 必须是 trusted 子集，否则 `SCOPE_VIOLATION`。
- `effective_start/end`: 绝对时间不得外扩 trusted 边界。
- relative time_range: 用 `retrieval.repository.latest_message_timestamp(anchor_scope)` 解析 archive_latest（复用 resolve_relative_time_range）。

### Ordering Semantics（ADR 要求写测试）

时间窗 m1(10:00) m2 m3 m4，limit=2：
- selection: `ORDER BY timestamp DESC, present seq first DESC… LIMIT 2` → m4,m3
- return: reversed → [m3, m4] chronological。
- Repository 新方法签名：`read_recent_messages(query: MessageQuery) -> tuple[MessageProjection, ...]`；
- StructuredRetrieval 新方法 `retrieve_recent_messages(query)`：count_messages 取 total → read_recent_messages → StructuredMessageResult(ordering metadata 描述 "latest-N selection, returned chronologically", details 标注 selection="latest_limit")。coverage/partial/truncated 与 retrieve_messages 同规则。

### Result Contract

直接复用 `StructuredMessageResult`：
- ToolEnvelope.to_dict 已支持（contracts.py L480）；build_tool_result_record 已支持（evidence.py L975：messages→citable message_items，带 source handles）；model projection 已支持 "messages" key（evidence.py L1222）。**零新 provenance 系统。**

### Registry / Runtime 接入点

1. registry.ToolRequest union += GetRecentMessagesInput
2. tools.py: `RecentMessagesTool(_CapabilityTool)` name="get_recent_messages", trace_stage="retrieval", internal_operation_prefix="structured.browse"; _request_payload/_result_payload/_result_meta 增加 StructuredMessageResult 分支（复用 _aggregate 风格 summary：returned/total/truncated/resolved range）
3. application.create_application: register(GetRecentMessagesTool(GetRecentMessagesCapability(structured_retrieval)))
4. query/contracts.py QueryRequest.available_capabilities 默认追加 "get_recent_messages"
5. openai_tools.py 新 adapter：params `time_range{kind,amount,unit,anchor}`(对象), start/end_timestamp(int|null), session_ids(list|null), limit(default 100)；schema 增强 min/max limit；description 写明 overview/recent/topic-discovery 场景与"先用本工具再分析"
6. openai_adapter._build_agent 加 capability 分支

### Prompt 工具选择边界（prompt.py）

新增段落：
- candidate set 主要由时间范围决定且用户要 overview/summary/topic discovery/"最近聊了什么" → **先 get_recent_messages**；不要为 temporal 问题猜主题去 search。
- lexical_search：精确 lexical target（URL/repo/code/error/nickname/exact phrase）。
- semantic_search：概念转述无精确词。
- execute_sql：结构化统计 counts/GROUP BY。
- 明确 get_recent_messages 的 limit 使用其 schema 上限、zero hits 合法、禁止同参重复调用。

### Router/Planner

不改 Router 逻辑（§六）：仅依赖 tool description+prompt；Evaluation 观察错选率，未来才考虑 rule router。

## Failure B 设计：CJK Bigram Derived-Index Normalization

### 方案比较（§八）

| 维度 | A.trigram | **B.CJK bigram 归一化(选定)** | C.dual index | D.query-time LIKE fallback |
|---|---|---|---|---|
| 中文 substring recall | ✗ 实测 2 字查询 MATCH=0（trigram 需 ≥3 字符），中文双字词大量存在，致命 | ✓ 双字词恰好一个 bigram；n 字词→n-1 个重叠 bigram phrase | ✓ | ✓ 但 silent，被 §九禁止 |
| 英文 exact 行为 | 变化（≥3 字符变 substring、跨词界 trigram，破坏现有 contract） | 不变（非 Han run 原样交给 unicode61） | 不变(原 index)+✓ | 不变 |
| URL/repo/code/错误消息 | 受损风险高 | 不受损 | 好 | 好 |
| 索引规模 | 极大膨胀 | Han token ×~2，ASCII 不变 | ×2 | — |
| 运行时可用性 | FTS5 内建 | 纯 Python 归一化，无新依赖 | 两套维护 | LIKE 全表扫性能差 |
| migration | rebuild | rebuild + strategy 元数据校验 | 双表迁移复杂 | 无 |

选定 B。理由：唯一同时满足"中文 2 字词召回 + ASCII exact contract 不动 + 单一 derived index + 显式 failure attribution"的方案。

### 精确契约

纯函数模块 `src/trivae/data/storage/sqlite_lexical_text.py`：

- `CJK_Bigram_STRATEGY_ID = "unicode61+cjk-bigram-v1"`
- `normalize_lexical_index_text(text: str) -> str`：
  - 对每个连续 Han run（U+3400–U+9FFF + U+F900–U+FAFF）长度 n≥2 → 替换为其 n−1 个重叠 bigram 以空格连接（真心推荐 → 真心 心推 推荐）；长度 1 → 保留该字；
  - 非 Han 内容逐字不动（unicode61 继续处理 ASCII 切分/小写化）。
- `_fts_match_expression(query)`（sqlite_read.py）改为：terms 先各自走 normalize → 含空格的归一化串放进单个 quoted literal（FTS quoted string = 保序短语），仍 AND 连接多 term，quote 转义规则不变。
- 词义等价性：doc bigram 流中连续出现查询 bigram 序列 ⇔ doc 某 Han run 存在该子串（相邻 bigram 共享中间字符，可逆）。不含 false positive path。

### Staleness / Migration / Observability

- sqlite_lexical.rebuild() 同时维护派生元数据表 `trivae_derived_meta(key,value)`：写入 `lexical_tokenizer_strategy=<ID>`（CREATE TABLE IF NOT EXISTS + upsert，事务内完成）。
- sqlite_read._ensure_lexical_index_ready 增加 strategy 校验：meta 缺失或 != 当前 ID → LexicalIndexError("messages_fts tokenizer strategy is stale; rebuild the derived index")。旧库无表同样显式失败 → smoke 前执行一次 `application.rebuild_lexical_index()`（已有公开入口）。
- Trace/retrieval diagnostics 保持 strategy=lexical、coverage、returned/total；LexicalIndexError 不降级、不 fallback。

## Compatibility Notes

- ModelAnswerCandidate 空 claims 契约本次不动（Failure Case A 修复后不再触发 honest-empty 路径；剩余风险记录于报告）。
- `search_messages` legacy surface 不受影响（共用 read/repository 层，FTS expression 变更对其同为修复）。
