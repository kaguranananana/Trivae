# Problem: Temporal Browsing 缺失 与 中文 Lexical 0-hit（v2 收口补全）

> Task: `.trellis/tasks/08-27-lexical-v2-zero-result`（第二轮收口）与 `.trellis/tasks/08-27-recent-messages-lexical-recall`。
> 真实 Failure Case 驱动修复记录。

## Problem

同一真实用户问题 `最近一两天大家都在讨论什么有价值的内容`：

1. Trivae 无法稳定回答（terminal failed），Agent 行为是"猜测主题 → semantic/lexical 检索猜测"；
2. `lexical_search("推荐")` 在 canonical 存在 `真心推荐 值得看一看` 的时间窗内返回 0 hits（coverage complete）。

## Evidence

- Trace `trace-87060c18023e46988f4df09a98a27f9f`（2026-08-27 11:28）：
  - semantic ×3 + lexical("推荐") + get_schema，0 命中；terminal failed / 5 tool calls / ~75s / final_answer not available。
- 同题 ChatLab 对照：单次 `get_recent_messages(2026-08-15~16, limit=200)` 返回 108 条消息后一次总结成功。
- 真实库诊断脚本（本任务目录 / 会话记录执行）：
  - `LIKE '%推荐%'` 全库 1596 hits；窗口内 14 hits；
  - FTS MATCH `"推荐"` 全库 258、窗口内 **0**；
  - 目标消息 `qq:1039179741:7674201141965536638` FTS row 存在；index count 473236==473236 非 stale；
  - fts5vocab 实测 unicode61 tokens：`真心推荐`、`值得看一看` 为整 run 单 token；`推荐这个repo` 混合串亦为单 token；
  - trigram tokenizer 探针：对 2 字查询 MATCH=0（trigram 最小 3 字符）。

## Root Cause

- Failure A（架构层）：Stage 1.4 Tool Surface 没有 temporal browsing 能力，prompt 引导把时间窗问题推向 keyword/concept retrieval；"猜测最近内容再搜索"必然 miss。空结果又被答案契约拒绝为 fatal → terminal failed。
- Failure B（派生索引层）：FTS5 unicode61 tokenizer 把连续 Han 字符 run 归并为一个 token，子串查询无任何 token 级匹配机会；与 session/scope/timestamp/freshness/escaping 无关（已逐一排除）。

## Options（Failure B）

| 方案 | 结论 |
| --- | --- |
| A. trigram tokenizer | rejected（measured）：2 字查询 0 命中，中文双字词占主导；ASCII substring 语义同时被破坏 |
| B. rebuild+query 双侧 CJK bigram 归一化 | selected |
| C. dual index | rejected：维护/一致性成本高，B 单索引即可同时覆盖 |
| D. query-time LIKE fallback | permanently rejected：silent fallback + 性能差 + 破坏 failure attribution |

## Decision

- A：新增 `get_recent_messages`（ADR Stage 1.4 §19 reopen 记录），复用 Structured Retrieval，selection latest-N→chronological return，limit 复用 structured bound。
- B：`sqlite_lexical_text.py` 纯函数归一化（Han run ≥2 → 重叠 bigram）；rebuild 经 SQLite 自定义函数应用；query 侧 `_fts_match_expression` 同函数归一化为保序短语；strategy id `unicode61+cjk-bigram-v1` 写入 `trivae_derived_meta`，read 侧不匹配即显式 stale。

## Validation

- 单元/回归：`tests/test_chinese_lexical_regression.py`（14）、`tests/test_recent_messages.py`（9）、全量 404 passed、ruff/mypy clean。
- 真实库：rebuild 473236 msgs / 9.0s；Smoke B 同窗口 total 157（此前 0），目标消息命中；Smoke A 连续多轮以 `get_recent_messages` 作为首个且唯一数据读取 Tool 完成（trace-3c348e06…、trace-e3b18400…、trace-41c05fb2…，1 tool call / 1 round / 23–36s / citations 3–5）。其中一次 provider runtime error（opencode-go）为模型服务侧故障，与本修复无关。

## Observability

- tool.call.started/completed 携带 request 与 result summary（returned/total/truncated/selection/resolved_time_range/latency_ms）；
- lexical 路径保留 strategy=lexical、coverage、returned/total、index diagnostics；strategy 不一致 → CAPABILITY_UNAVAILABLE + stale 提示，不静默降级。

## Scale

- measured：47.3 万消息 rebuild ≈9s（M2 MacBook）；窗口浏览 SELECT 单位毫秒级；bigram 仅作用于 Han run，非 Han 规模不变。

---

## 第二轮收口：FC-A mixed-script 边界 / FC-B zero-result 契约（2026-08-27）

### FC-A: CJK/ASCII 混排仍 miss（bigram v1 → v2）

**复现（修改前，真实 FTS5）**：

| document | normalized(v1) | query | hits |
| --- | --- | --- | --- |
| `abc推荐` | `abc推荐` | 推荐 | 0 |
| `推荐abc` | `推荐abc` | 推荐 | 0 |
| `推荐这个repo` | `推荐 荐这 这个repo` | 这个/repo | 0 |
| `repo推荐这个` | `repo推荐 荐这 这个` | repo/推荐 | 0 |

**Root Cause**：unicode61 把相邻字母/数字/CJK 视作一个 token；v1 只重写 Han run 内部且不建立
Han/non-Han tokenizer 边界——len==2 run 替换结果等于原文，首尾 bigram 与 ASCII 仍粘连。

**Decision（v2）**：每个 maximal Han run（含单字）一律用空格包裹（run≥2 生成重叠 bigram；
单字原样保留），ASCII 内容逐字不动；rebuild/query 双侧同函数。strategy bump 为
`unicode61+cjk-bigram-v2`：v1 索引被 read 侧显式 stale 拒绝（测试覆盖），必须 rebuild，
无 compatibility fallback。LIKE 仍是 diagnostic oracle，不是查询路径。

**Measured（真实库 rebuild 后）**：
- `lexical_search("推荐")` in-window session 0→157(v1)→**187**(v2)；global FTS **1596 = LIKE 全量**（100% recall vs LIKE oracle）。
- 真实 mixed-script 样本 4 条（如 `南大都做不了ai吗`、`我朋友sys两篇顶会二作研0`、`本科9的含金量高的一p`）
  的跨边界 query 全部 self-hit（FTS MATCH 直接命中原文档行）。
- rebuild 473,236 msgs / 8.7s；rebuild 前 read 侧正确报 stale。

### FC-B: 合法空窗查询被 final contract 升级为 terminal failed

**Evidence**：
1. `get_recent_messages({})` 在 SDK schema 合法（全参数可选），Capability 却抛 INVALID_ARGUMENT
   （"time_range or an explicit time window is required"）→ contract drift 实锤。
2. honest no-result final JSON（`{"claims":[],"limitations":[…]}`）在 strict parse
   （ModelAnswerCandidate requires claims）、graceful recovery（no readable claim）、validate_answer_artifact
   （MISSING_EVIDENCE tool-backed 必须有 evidence+binding）三层都被拒 → terminal failed。

**Decision**：
- `{}` ≡ relative recent 2 days anchor=archive_latest（无 wall clock）；SDK=Capability 一致；
  description/prompt 写明。真实 smoke 中模型自然发出 `{"limit":100}` 即成功。
- 新显式 zero-result final 形态 `{"kind":"no_result","summary":…,"limitations":…}`：
  - 放行条件 Host 可验证：`tool_results_have_result_facts()==False`（无 message_items 且无非-schema structured rows），
    schema tables[] 不算事实；冲突时 strict 层 `INVALID_FINAL_OUTPUT` fatal，不产生降级 artifact。
  - 不允许携带 claims 字段（含空数组），杜绝混合形态绕过 citation contract。
  - 空 trusted scope 上 relative 无 archive_latest 时 Capability 返回合法空结果（coverage complete）而非参数错误。
    该分支曾有一个中间缺陷（漏传时间界导致返回全 session 最新消息充当"空结果"，被 smoke当场抓出并修复）。

**Validation（pytest 确定性回归 + 真实 smoke）**：
- `tests/test_chinese_lexical_regression.py`（18 个用例含 v1-stale/重建恢复/mixed-script 矩阵）、
  `tests/test_no_result_finalization.py`（8）、`tests/test_temporal_zero_result_integration.py`（3）。
- 真实 Smoke E3（trace-0d3a998d…）：空窗 → get_recent_messages ok ×1 → no_result valid artifact
  （1 block/0 evidence/0 citations）→ completed；E1/E2（trace-a179e8dd…/f966aba3…）completed 且唯一数据工具为 recent。
- 已知 provider 噪声案例 trace-f3fc2a1d…：模型输出自我声明的 "Placeholder" no_result 被 guard 正确拒绝
  ——防护机制在真实环境生效的正面证据。

### Evaluation 定位说明

EvaluationRunner.resolve_snapshot 要求 case snapshot status=="available"；bind-at-run design seed
不能作为已执行 evaluation 报告。确定性回归落在 pytest 层；「模型优先选择 recent」依赖真实推理，
以 smoke trace 取证。两个 seed 保持如实标注（annotation_completeness=unknown）。
