# M1 Hardening → M2 Retrieval Core → M3 Capability/Tool — Validation Record

> 本文件只记录可由 architecture decision、代码、测试、真实 canonical 数据运行、benchmark、evaluation 或实际 Failure Case 证明的内容。未验证项明确标为 `pending`、`engineering expectation` 或 `anticipated risk`。

## Problem / Motivation

### Baseline

- `measured fact`: M1 现有 SQLite canonical messages、session-scoped identity、write store、importer 和回归测试；baseline unittest 16/16 通过。
- `measured fact`: clean import/rerun 已重新校准 473,236 inserted messages、7 sessions、0 errors 和 provenance 幂等。
- `measured fact`: 当前 runtime 支持 FTS5；real-data lexical/context latency 与 query plan 已补录。

### Failure attribution target

- Read contract / query validation：Retrieval Core
- SQL/projection/session isolation：Data/Storage read adapter
- FTS consistency/rebuild：Derived Data adapter
- Context merge/trim/hit preservation：Retrieval Core
- Capability input/output/scope/error projection：Capability/Tool layer
- Canonical facts、identity、conflict、provenance：M1 ingestion/storage；本任务不为检索便利改变其语义

## Design Rationale

| Problem | Considered options | Selected option | Reason / trade-off | Evidence status |
| --- | --- | --- | --- | --- |
| Retrieval 读取边界 | 直接复用 write store / 独立 read adapter / 复杂 repository hierarchy | 最小独立 read adapter | 避免 Retrieval 直接操作 SQLite，同时不引入未来数据库抽象 | architecture + read tests |
| lexical index | LIKE / SQLite FTS5 / 外部搜索服务 | SQLite FTS5 derived index；LIKE 只作基线 | local-first、可 rebuild、canonical remains truth；牺牲 substring 等价性 | real-data probe + benchmark |
| context invocation | Agent 再调用 expand / Retrieval 自动 expansion | Retrieval 自动 expansion | 保留 Stage1.3/ChatLab 已确认的数据流和 hit preservation | architecture + context tests |
| Tool boundary | Tool 重写 SQL/算法 / Tool 包装 Retrieval Core | Capability/Tool wrapper | 防止 contract、scope、排序和 trim 语义分叉 | architecture + contract tests |

## Why Not

- `currently unnecessary / waiting for evaluation evidence`: Elasticsearch、Meilisearch、PostgreSQL 等外部搜索服务；reconsideration trigger 是 local SQLite 在真实 Failure Case 下无法满足正确性或可接受 latency，且新 architecture decision 明确批准外部服务。
- `currently unnecessary / waiting for evaluation evidence`: Semantic/vector/hybrid/reranker；reconsideration trigger 是真实 Evaluation Dataset 和对应 Architecture/Technical Decision 完成，而不是当前 lexical 结果主观不满意。
- `currently unnecessary / waiting for evaluation evidence`: 完整 Trace backend、Evaluation runner、Router/Planner/Agent Runtime；reconsideration trigger 是 M3 contract 完成并开始下一条 M4 vertical slice。
- `permanently rejected for this task`: 在 Tool handler 内重复实现 SQL、FTS query、context merge 或 ordering；这会制造 Core/Tool 语义漂移。

## Failure Cases

> 初始状态只列已知 regression case / anticipated risk；真实运行发现后追加 `real failure`，不得把预期写成发生过。

| Classification | Input / scenario | Observed failure | Root cause | Fix / handling | Validation | Regression |
| --- | --- | --- | --- | --- | --- | --- |
| `regression test case` | 两 session 复用 source/reply ID | 预防跨 session 漏读 | source/reply 不是全局 ID | query 必须带 session predicate | structured/capability tests passed | test_structured_retrieval |
| `regression test case` | 相同 timestamp、seq 缺失 | 预防依赖 SQLite NULL 默认排序 | seq 是 optional hint | 显式 NULL ordering + internal ID tie-break | structured tests passed | test_structured_retrieval |
| `regression test case` | context window overlap | 预防重复消息 | 多 hit 窗口重叠 | stable identity merge/dedup | lexical tests passed | test_lexical_retrieval |
| `regression test case` | context expansion 超过 bound | 预防真实 hit 被 context 挤掉 | 简单 `results[:limit]` 会丢 hit | hit-preserving trim | lexical/capability tests passed | test_lexical_retrieval |
| `anticipated risk` | FTS5 不可用或真实规模 rebuild 慢 | 当前 runtime 已可用且 rebuild ~4004ms | SQLite build/runtime capability 或数据规模 | 显式 probe/rebuild error；不静默 fallback | real-data calibration passed | future evaluation trigger |
| `real failure` | 首版 FTS query 使用 `f MATCH ?` / `bm25(f)` | SQLite 报 `no such column: f` | FTS5 MATCH/bm25 需要使用虚拟表名而非该别名 | 改为 `messages_fts MATCH ?` / `bm25(messages_fts)` | lexical tests 通过 | test_lexical_retrieval |

## Evaluation / Evidence

### M1 clean import / rerun

| Run | Database path | Input scope | inserted | duplicate | conflict | errors | provenance/rerun observation | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| baseline from existing project record | existing M1 validation record | 14 raw files / 7 sessions | 473236 | 21392 | 2775 | 0 | documented baseline; not this run | measured fact from prior record |
| clean import | temporary DB | 14 raw files / 7 sessions | 473236 | 21392 | 2775 | 0 | messages=473236; sources=494628; variants=21392 | measured fact |
| rerun | same temporary DB | same 14 files | 0 | 494628 | 2775 | 0 | messages/sources/variants remained 473236/494628/21392 | measured fact |

### Retrieval cases

| Case | Query / scope | Expected behavior | Actual result | Failure signal | Classification |
| --- | --- | --- | --- | --- | --- |
| structured session/time | session `qq:1028505110`, one-day `[1772818482000,1772904882000)` | session isolation + `[start,end)` | `43` total / `20` returned；source lookup `qq:677019167 / 7529223158885421454` exact `1` | none | real-data + regression |
| lexical low-frequency | FTS5 keyword `MCP` | bounded hit set | `75` total / `20` returned，~`95ms` | none | real-data + regression |
| lexical high-frequency | FTS5 keyword `的` | measured latency + truncation | `272` total / `20` returned，~`107ms`；`truncated=true` | none | real-data + regression |
| lexical Chinese/multi-keyword | FTS5 `模型`、`代码`、`AI Agent` | expected FTS token behavior recorded | `模型=32`、`代码=25`、`AI Agent=93` total；各 bounded 到 `20` | FTS5 tokenization is not LIKE substring equivalence | real-data + regression |
| context adjacent hits | `MCP` with adjacent/overlapping windows | merged, deduped, chronological | fixture overlap/dedup/order tests passed；real case `75` total / `10` returned | none | lexical regression |
| context session boundary | same keyword in two sessions with explicit session scope | no cross-session message | sampled sessions returned `10` and `7` hits independently | none | real-data + regression |
| context trim | `MCP`, bound `10` | hit preservation + bounded result | `10` returned，`partial=true`，`truncated=true` | measured ~`2890ms` context expansion | real-data + regression |
| same keyword in different sessions | `MCP` with `qq:1028505110` vs `qq:1039179741` | scope controls returned hits | totals `10` vs `7`，未混入对方 session | none | real-data + regression |

#### Completed real-data cases

- `measured fact`: source count `473236` messages across `7` sessions; per-session counts were `73014`、`53944`、`119361`、`11422`、`42190`、`149211`、`24094`。
- `measured fact`: sender case `qq:1040412855 / qq:uid:u_vhXofZbr6D-axrefCOXnGQ` returned `total_hits=13656` and bounded `returned_count=5`。
- `measured fact`: one-day half-open sample on `qq:1028505110` returned `total_hits=43` and bounded `returned_count=20`。
- `measured fact`: source lookup `qq:677019167 / 7529223158885421454` returned exactly one hit。
- `measured fact`: a real timestamp group with `11` messages returned identical internal-ID order across repeated Structured queries。
- `measured fact`: FTS5 `AI Agent` returned `93` total hits and `20` bounded hits；two sampled sessions returned `MCP` totals `10` and `7` respectively。
- `measured fact`: `MCP` context case returned `75` total hits、`10` bounded messages、`partial=true`、`truncated=true` in approximately `2890ms`。

### Performance baseline

| Operation | Dataset | Result count | Latency | Build/rebuild time | Status |
| --- | --- | ---: | ---: | ---: | --- |
| FTS5 capability probe | current Python/SQLite | n/a | measured available | n/a | measured fact |
| FTS rebuild | temporary copy of real DB | 473236 | n/a | ~4004ms | measured fact |
| structured representative query | temporary copy of real DB | 20 returned / 43 total | measured in result metadata | n/a | measured fact |
| lexical low-frequency (`MCP`) | temporary copy of real DB | 20 returned / 75 total | ~95ms | n/a | measured fact |
| lexical high-frequency (`的`) | temporary copy of real DB | 20 returned / 272 total | ~107ms | n/a | measured fact |
| context expansion (`MCP`, bound 10) | temporary copy of real DB | 10 returned / 75 total | ~2890ms | n/a | measured fact |

LIKE comparison for the same read-only source: `Agent` 6754 rows/~179ms vs FTS5 689/~127ms；`AI` 12831/~189ms vs 1193/~172ms；`MCP` 358/~190ms vs 75/~95ms；`模型` 2824/~186ms vs 32/~101ms；`代码` 2417/~185ms vs 25/~110ms；`的` 94255/~226ms vs 272/~107ms。FTS5 is faster but not substring-equivalent to LIKE，尤其中文命中集合需要 future evaluation 定义。

## Observability / Debugging

- Structured/Retrieval result records query scope, filters, strategy, total, returned, coverage, partial, truncated, ordering and latency metadata without storing raw payload.
- Explicit errors identify query validation, storage SQL/read conversion, derived-index rebuild/query and capability contract ownership；未知异常不被 generic Tool error 静默吞掉。
- Validation records compare direct canonical count/identity with derived/retrieval results to distinguish retrieval miss, filter error, truncation, derived-index staleness and data problem。
- `pending`: Stage1.9 normalized Trace backend is not implemented in this task and must not be described as existing.
- `measured fact`: context `EXPLAIN QUERY PLAN` uses `idx_messages_session_time` for the session predicate but a temporary B-tree for the remaining explicit NULL-aware ordering terms；当前没有因为单次 bounded sample 直接新增 index。

## Scale / Performance

- `measured fact`: clean import/rerun contains 473,236 inserted messages across 7 sessions；rerun inserted `0`，duplicate provenance `494,628`，errors `0`。
- `engineering expectation`: canonical source remains queryable even if derived FTS data is deleted; rebuild cost and lexical latency must be measured before performance claims。
- `anticipated risk`: high-frequency term and context expansion may be dominated by returned/expanded row count；if observed, preserve correctness and record query plan before considering index changes。
- `measured fact`: current context sample is materially slower than direct FTS retrieval；reconsider expression index or batched window query only if larger cases show unacceptable latency or a repeatable context Failure Case。

## Boundary / Ownership

- Application/bootstrap owns composition and resource lifecycle。
- M1 ingestion/storage owns canonical facts, identity, conflicts, provenance and write transaction semantics。
- Read adapter owns SQLite connection, SQL, column selection and canonical-to-retrieval projection。
- Derived FTS adapter owns only rebuild/sync/query of derived search data；it never becomes evidence/source of truth。
- Retrieval Core owns structured/lexical/context/result semantics。
- Capability/Tool owns agent-facing validation, envelope, registry and scope projection；it delegates all retrieval behavior。
- Router/Planner/Runtime/Evidence/Trace/Evaluation remain outside this task。

## Evolution

Current baseline is local SQLite canonical + optional derived FTS5 + Retrieval Core + Capability wrapper. New architecture or optimization requires a real Failure Case, measured baseline or Evaluation evidence. Keep semantic/vector/hybrid, richer context, Trace, Evaluation runner and Agent Runtime pending until their own vertical slices have contracts and regression/evaluation evidence。

## Interview Defense Notes

| Question | Fact source |
| --- | --- |
| Why separate read adapter? | `design.md` boundary + read adapter code/tests |
| Why session-scoped source/reply? | M1 database guideline + duplicate-ID isolation regression |
| Why explicit ordering? | `design.md` SQL contract + seq/NULL tests |
| Why FTS5 vs LIKE? | validation probe, side-by-side real query measurements |
| Why automatic context expansion? | Stage1.3 decision + merge/trim/hit-preservation tests |
| Why does Tool stay thin? | Stage1.4 boundary + Tool/Core consistency tests |
| How are performance claims supported? | real-data count, build/rebuild, latency and returned-row tables |
| What triggers re-evaluation? | Evolution and Why Not entries above |
