# M2A Read Contract + Structured Retrieval — Technical Design

## 1. Design Goal

实现一条连续查询链：

`TrivaeApplication -> Capability/Tool -> Retrieval Core -> Read/Derived Data Adapter -> M1 messages`

职责保持单向：retrieval 定义业务读取契约、lexical/context/result 语义并封装结果，data/storage 负责 SQLite 连接、canonical SQL 和 derived FTS 数据，capabilities 只定义 agent-facing contract/registry，bootstrap 负责组装与关闭。Retrieval Core 不知道 SQLite 列布局，不接收 write store connection；Tool 不重写 Retrieval 逻辑。

## 2. Proposed Files and Ownership

### Retrieval layer

- `src/trivae/retrieval/__init__.py`
  - 只导出 M2A 对外需要的 query、projection、result、error 和 service 类型。
- `src/trivae/retrieval/structured.py`
  - 定义冻结 query dataclass、聚合 query、retrieval-facing projection、coverage/metadata、消息/聚合结果类型。
  - 定义 `CanonicalReadRepository` Protocol。
  - 实现 `StructuredRetrieval`：验证 query、调用 repository、计算 returned/truncated、封装 strategy/coverage/metadata。
  - 不出现 SQL、sqlite3、数据库列名或 raw payload。
- `src/trivae/retrieval/lexical.py`
  - 编排 lexical query、FTS hit projection、scope/limit 和 Retrieval Result；不直接执行 SQLite。
- `src/trivae/retrieval/context.py`
  - 根据 stable message identity 请求同 session 的窗口，合并重叠窗口、去重、排序和 bounded trim，并保留真实 hits。
- `src/trivae/retrieval/structured.py`
  - 与 query/projection 一起定义 Retrieval Core 结果类型，不复用 ToolResult、Citation、Trace 或 Evaluation schema。

### Data/storage layer

- `src/trivae/data/storage/sqlite_read.py`
  - 实现 `SQLiteCanonicalReadRepository`。
  - 使用 SQLite URI 的 `mode=ro` 打开独立读取连接，并设置 `query_only`；连接对象只作为私有字段存在。
  - 集中构造参数化 WHERE、消息 projection SELECT、显式排序、COUNT 和三个分组表达式。
  - 将数据库行转换成 retrieval projection；转换函数不把 JSON 原文带出边界。
- `src/trivae/data/storage/sqlite_lexical.py`
  - 负责 FTS5 derived index 的 rebuild/同步与参数化 lexical query；canonical messages 仍是 source of truth。

### Bootstrap layer

- `src/trivae/bootstrap/application.py`
  - 创建 read repository 和 Structured Retrieval；保留现有 write store/importer 关系。
  - 提供最小的结构化消息/聚合查询入口，或暴露已组装的业务服务（最终以现有应用 facade 风格中改动最小者为准）。
  - `close()` 先关闭 read repository，再关闭 write store；退出时不吞异常。

### Tests and docs

- 新增 `tests/test_structured_retrieval.py`，使用临时 SQLite 数据库和现有 M1 importer/helper 构造两个隔离 session。
- 新增 lexical/context/capability contract tests；真实数据测试不修改 raw/canonical source。
- 同步 backend directory/database guideline 与必要的 Stage1.3/Stage1.4 technical decision，记录已经落地的物理边界与契约。
- 在任务目录维护 `validation.md`，只填入代码、测试、真实数据校准、benchmark 或实际 Failure Case 能证明的内容。

## 3. Read Contract

### 3.1 MessageQuery

消息查询采用冻结值对象，字段为：

```text
session_ids: tuple[str, ...] | None
start_timestamp: int | None
end_timestamp: int | None
sender_user_ids: tuple[str, ...] | None
message_types: tuple[str, ...] | None
source_message_id: str | None
reply_to_source_message_id: str | None
limit: int | None = 100
```

`100` 是有界消息列表的默认上限；显式传入 `None` 仍然代表无界消息查询，必须报 `InvalidStructuredQuery`，而不是隐式读取全表。过滤集合归一化为 tuple 以保证值对象可重复使用；空集合表示调用方给出了无意义 scope，应在入口显式报错。

验证顺序固定为：先验证时间区间，再验证 limit，再验证过滤集合，最后验证 source/reply 必须有 session scope。`start == end` 是合法的空半开区间，SQL 使用 `timestamp >= start` 与 `timestamp < end`。

### 3.2 AggregateQuery

聚合查询复用上述 scope 字段但不带消息列表 limit，`group_by` 只能是：

- `None`：返回过滤后的总数
- `"session"`：按 `session_id` 分组
- `"sender"`：按 `sender_user_id` 分组，NULL 保留为一个明确的“无 sender_user_id”桶，不伪造身份
- `"month"`：按 UTC 的 `YYYY-MM` 分组，使用 canonical timestamp 的 Unix milliseconds

`group_by` 只允许来自内部 Literal 到 SQL 表达式的固定映射，不能把用户输入拼进 SQL。

### 3.3 Projection

`MessageProjection` 只包含 retrieval 需要的值：

```text
internal_message_id
session_id
source_message_id
sender_user_id
sender_platform_id
sender_uin
sender_name
timestamp
seq
message_type
normalized_content
reply_to_source_message_id
recalled
system
```

`normalized_content` 当前直接来自 M1 已规范化的 `content_text`；M2A 不重新解释 `content_json`。internal ID 与 source ID 使用不同字段名和不同 SELECT 列，避免下游误将 source ID 当作全局主键。

## 4. Ordering Contract

仓储 SELECT 使用以下逻辑顺序：

```sql
ORDER BY
  timestamp ASC,
  CASE WHEN seq IS NULL THEN 1 ELSE 0 END ASC,
  seq ASC,
  internal_message_id ASC
```

第一项遵守 canonical 时间，第二项确保有 seq 的行和缺失 seq 的行不受 SQLite 默认 NULL 排序影响，第三项在同一 timestamp 下使用平台顺序提示，最后一项为所有剩余相等情况提供稳定 tie-break。实现注释必须用简体中文说明：缺失 seq 的顺序是可重复排序，不是对平台原始顺序的推断。

## 5. SQL and Repository Boundary

仓储内部使用一个 scope builder 生成 `WHERE` 和绑定参数：

- session：`session_id IN (?, ...)`
- time：`timestamp >= ?`、`timestamp < ?`
- sender：`sender_user_id IN (?, ...)`
- type：`message_type IN (?, ...)`
- source：`source_message_id = ?`
- reply：`reply_to_source_message_id = ?`

所有值通过 sqlite parameter binding；列名、排序、分组表达式只从代码固定常量产生。source/reply 的 session 前置约束由 query contract 验证，SQL 仍然包含 session predicate，因此不会发生跨 session 漏查。

消息读取分两步：先 `COUNT(*)` 得到 `total_hits`，再用限定列的 SELECT 加 `LIMIT ?` 读取消息。两步使用同一 scope；结果中 `returned_count = len(messages)`，`truncated = total_hits > returned_count`。M2A 不以返回行数推断 total。

聚合查询使用独立的 COUNT/group SQL，返回 `AggregateBucket`，不复用消息 projection，也不执行任何语义分类。Structured path 不新增索引；Lexical path 先在当前 Python/SQLite 环境实际探测 FTS5，再比较 LIKE 与 FTS5 的真实结果/耗时。只有 FTS5 可用、scope/一致性可验证且校准适合当前规模时才建立 derived virtual table；否则保留明确证据和 blocker，不静默降级。

## 6. Result and Coverage Semantics

消息和聚合结果都带 `strategy="structured"`、原始 query/scope、`Coverage(status="complete", basis="canonical_store")`、`partial=False` 和 `metadata`。直接读完整 M1 canonical store，因此 Structured path 不伪造 partial；Lexical derived index 的 stale/unavailable 由 lexical error contract 显式表达。

`truncated` 只表示消息列表的 limit 截断；`coverage` 表示数据源覆盖程度；`partial` 表示结果本身是否仅覆盖数据源的一部分。三者使用不同字段，不能互换。metadata 保存标准化 ordering 描述和 `perf_counter` 测得的耗时（毫秒）；不实现 Stage1.9 的 trace/span 体系。

## 7. Application Lifecycle and Compatibility

`create_application()` 的顺序为：创建现有 write store、创建 importer、创建 read repository、创建 Structured Retrieval。read repository 只读打开已由 store 初始化的数据库。关闭时按 read repository -> write store 顺序释放资源，并保留现有异常传播方式。

不修改 M1 `CanonicalMessage`、`SQLiteCanonicalStore` 的写入接口、schema、projection、seq/identity/conflict/error mapping。M1 的公开 connection 仅保留现有测试/代码兼容状态；M2A 不新增任何 read-facing connection 访问。

## 8. Failure and Observability Strategy

- 非法 query 在执行 SQL 前抛出明确的 `InvalidStructuredQuery`，包含稳定 error code 和可定位的字段信息。
- SQLite 打开失败、SQL 失败和行转换失败继续显式抛出；不添加 fallback、静默吞错、重试或 LIKE 降级。
- 结果 metadata 与测试断言 scope、strategy、total、returned、truncated、coverage 和 ordering；不记录完整消息 raw 内容。
- session isolation 失败视为主链路 Failure Case，优先修正 scope builder，而不是增加针对某个 ID 的特殊规则。

## 9. Verification Strategy

单元/集成测试覆盖 20 个要求类别：session、半开时间、sender、type、source 隔离、reply 隔离、多条件、无结果、超过 limit、total≠returned、确定性排序、相同 timestamp 不同 seq、相同 timestamp 缺失 seq、跨 session 重复 source ID、count、session/sender/month 分组、非法时间、非法 limit、非法 query scope。

真实数据校准只读打开现有 `data/trivae.sqlite3`（若需构造临时数据则使用临时 DB，不触碰 raw）；对总消息数、7 session、真实 sender/time/source、重复 timestamp 顺序和代表性 latency 与直接 SQLite COUNT/SELECT 对比。校准后运行 M1 unittest、ruff、mypy 和 `python -m trivae --help`。

## 10. Interview-defense Evidence Plan

实现阶段不预先填写未经验证的结论；只冻结需要采集的证据形状：

| 面试追问方向 | M2A 需要保留的证据 | 事实边界 |
| --- | --- | --- |
| 为什么要有 Read Contract？ | 非法 query 的测试、结果字段和调用边界 | 说明契约解决的 scope/limit/total 歧义，不声称解决未来策略问题 |
| 为什么使用独立 read repository？ | 依赖方向、私有只读连接、SQL 边界测试/代码 | 记录 SQLite 读写生命周期，不扩展为 universal store |
| 为什么 source/reply 必须带 session？ | 两个 session 复用 ID 的隔离回归测试 | 这是 session identity 事实，不把 source ID 当全局键 |
| 为什么这样排序？ | SQL 排序表达式、seq 缺失测试、重复执行结果 | 缺失 seq 只保证确定性，不宣称恢复平台真实顺序 |
| total、returned、coverage、truncated 如何区分？ | limit 场景的结果断言和 metadata | 分别说明匹配总数、返回数、数据覆盖和列表截断 |
| 如何定位读取问题？ | query scope、filters、ordering、耗时和错误字段 | 不提前声称已有 Stage 1.9 完整 Trace |
| 数据规模与未来演进怎么办？ | 真实 canonical 校准、代表性耗时、必要时的 query plan | measured fact 与 engineering expectation 分开；演进由新证据触发 |

## 11. Fast-track M1 Hardening Boundary

M1 hardening 先基于现有实现和测试找缺口，不以“重做 ingestion”作为默认方案。检查顺序：

1. 运行现有 unittest、ruff、mypy、CLI help 和当前 real-data stats。
2. 对 `seq`、conflict projection、typed error、rollback、CLI exit、rerun/provenance 逐项建立可复现 Failure Case 或确认已有 contract test。
3. 只在证据证明缺口存在时改 owner 层，并把 Failure Case 固化为 regression。
4. 用独立临时数据库做 clean import + rerun；对比 canonical count、duplicate/conflict/error/provenance，变化必须解释根因。

M1 的 canonical write path 仍是事实源；M2 derived index 的任何重建/删除都不能改变 M1 message rows。

## 12. Lexical Retrieval Design

### 12.1 Selection evidence

先探测 `PRAGMA compile_options`/实际 `CREATE VIRTUAL TABLE ... USING fts5`，再在代表性 fixture 和 real DB 上比较：

- LIKE：作为比较基线，不作为无依据的产品 fallback。
- FTS5：若可用，使用 local SQLite derived index；记录创建、rebuild、典型低频/高频/中文/多关键词查询的 latency 和 returned count。

选型结果写入 validation.md；若形成稳定技术决策，再增量写入 Stage1.3 technical decision，不把未验证预期写成架构事实。

### 12.2 Derived index ownership

FTS table 只存检索所需的 normalized content 与 stable identity locator（至少 internal_message_id、session_id、source_message_id），不存 raw payload，也不成为 Evidence Source of Truth。rebuild 先清理并从 canonical messages 重建；操作失败显式传播，不能留下“看起来成功”的半完成状态。导入同步只在已有 write transaction ownership 能清晰证明时加入；否则提供显式 rebuild path，不在 M1 importer 中加入静默异步同步。

Lexical query 使用固定 FTS query construction、session/time/sender scope 和 bounded hit read；空 keyword、非法 syntax 和未命中都使用明确的 contract semantics。FTS 命中后的 canonical projection 仍从 read repository 读取，确保结果不直接信任 derived content。

## 13. Context Expansion Design

Lexical hits 先保留 stable identity 与 hit metadata，再由同一 retrieval core 请求窗口消息。窗口查询必须带 hit 的 session scope；不能从一个 session 的边界向另一个 session 扩展。

每个窗口按 `before_n <= seq position <= after_n` 的可验证 canonical order 读取；对没有 seq 的数据使用 repository 已定义的确定性 ordering，不声称恢复平台真实顺序。窗口合并按 session 和 identity 去重，按统一 ordering 输出。最终 trim 采用 hit preservation：若总结果超过 bound，先保证所有真实 hit，剩余空间再按距离/排序规则选择 context；当 hits 本身超过 bound 时，结果显式 `truncated=True`/`partial=True`，不简单切掉前面的真实 hit。

如果当前 M1 schema 无法为 context 提供可证明的相邻定位，不添加隐式 fallback；记录真实 Failure Case，按现有 canonical ordering 最小实现或停止对应 context 变更。

## 14. Retrieval Result Contract

定义 `RetrievalResult`（名称按现有代码命名调整）作为 Retrieval Core 的稳定事实结果，至少包括：

```text
query
filters
strategy
hits
expanded_messages
total_hits
returned_messages
coverage
partial
truncated
metadata
```

`hits` 是 lexical hit locator/score/metadata，`expanded_messages` 是 retrieval projection；两者不混淆。Structured-only 查询可以返回空 hits 与 messages，但仍保持统一的 coverage/partial/truncated 语义。Tool wrapper 只做 envelope projection，不修改这个事实结果。

## 15. M3 Capability / Tool Design

M3 只在 M2 lexical/context/result 通过测试和 real-data validation 后继续。Capability 负责 metadata、typed input/output contract、scope inheritance、bounded result、error ownership；registry 负责稳定名称到 capability 的显式注册，不做动态猜测。

`search_messages` 的数据流为：

`Tool input -> Capability validation/scope -> Retrieval Core lexical + automatic context -> normalized RetrievalResult -> Tool envelope`

Tool handler 不导入 SQLite connection、不生成 FTS SQL、不实现 context merge/order/trim。scope 由 application execution context 与输入 contract 合并；调用方不能通过 Tool input 绕过 trusted session/time/bound。若 Stage1.4 的具体字段仍未落地，先复用文档已经确认的最小 envelope/typed error 边界，不自创完整 Tool framework，并在 validation.md 标记 pending。

M3 contract tests 使用临时 canonical DB 与 fake/in-memory Retrieval Core seam 验证 wrapper 语义，同时至少有一条真实 Retrieval Core integration path，避免只测试自我回显的 wrapper。

## 16. Explicit Stop Boundary

本 task 完成后停止在 M3 Capability/Tool Layer。不得实现 Router、Planner、OpenAI Agents SDK Runtime、Agent Loop、Tool Selection、LLM、answer generation、Citation generation、HTTP、Frontend、M4 CLI query E2E、M6 Trace backend 或 M7 Evaluation runner。
