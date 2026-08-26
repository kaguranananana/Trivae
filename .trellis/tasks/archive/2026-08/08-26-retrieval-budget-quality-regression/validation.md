# Validation

## 自动化验证

在 `codex/retrieval-budget-quality-regression` 分支执行：

| 检查 | 结果 |
| --- | --- |
| `python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-26-retrieval-budget-quality-regression` | passed（仅现有 spec 自动注入大小 warning） |
| `.venv/bin/python -m pytest -q` | 319 passed（binary projection 优化后最终复跑） |
| `.venv/bin/ruff check src tests` | passed |
| `.venv/bin/python -m mypy` | passed，82 source files |
| 新增 `tests/test_retrieval_budget.py` | 8 passed；覆盖 independent defaults/caps、schema、direct-hit/context source budget、canonical >100、16k projection、Prompt/taxonomy |

关键回归包括：

- lexical 默认 1000、hard cap 5000；semantic 默认 10、hard cap 20；`dense_top_k=40` 不随 lexical 放大。
- 150 条 canonical lexical message 可以进入 Tool Result；structured/member/SQL 仍拒绝超过 100。
- direct hits 已占满结果容量时不读取邻居；有剩余容量时自动 context source hit 最多 20，且 direct hit 不会被邻居挤掉。
- 16k projection 先省略 context、再压缩正文、最后显式省略尾部 direct hits，并保持可见 provenance 一致。
- partial/truncated 与 mention/recommendation、intent/use、review/personal usage、hit/entity 的回答安全 contract 存在。

## 真实 SQLite archive 分层性能

数据规模：`data/trivae.sqlite3`，约 473,236 条 canonical message；每项为 warm median（三次重复）。`retrieval` 包含 FTS 与 context expansion；`build` 是 canonical `ToolResultRecord` 建立；`projection` 包含 16k model projection；`canonical/projected bytes` 是对应 JSON 序列化大小；Trace 只保存 bounded retrieval summary，故其大小稳定在约 314–320 bytes。

| query | limit | total/returned | context source hits | retrieval ms | build ms | projection ms | canonical / projected bytes | estimated tokens | truncated / omitted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `Agent` | 100 | 689 / 100 | 0 | 100.6 | 0.2 | 2.5 | 111,712 / 36,625 | 12,162 | no / 0 |
| `Agent` | 300 | 689 / 300 | 0 | 102.7 | 0.6 | 38.6 | 341,066 / 47,758 | 15,873 | yes / 169 hits |
| `Agent` | 1000 | 689 / 689 | 20 | 2,215.8 | 1.7 | 97.4 | 1,230,962 / 47,702 | 15,854 | yes / 80 context + 559 hits |
| `https` | 100 | 2,779 / 100 | 0 | 116.1 | 0.2 | 2.7 | 111,602 / 39,284 | 13,049 | no / 0 |
| `https` | 300 | 2,779 / 300 | 0 | 118.8 | 0.8 | 41.6 | 340,461 / 47,628 | 15,830 | yes / 178 hits |
| `https` | 1000 | 2,779 / 1000 | 0 | 131.7 | 2.6 | 151.0 | 1,179,496 / 47,880 | 15,914 | yes / 878 hits |

对照旧基线：`Agent` 100/300/689 的 DB median 约 107.7/107.5/111.0ms，`https` 1000/2779/2779 约 131.3/146.0/144.6ms；旧 context 2/2 曾对 100/300 direct hit 产生约 15.5/45.3s 的无界逐 hit I/O。当前 direct hit 已填满容量时跳过邻居；有空间时只对前 20 个 source hit 读取。初版 1000-hit model projection 的 2–4.6s 逐尾删除瓶颈已复现并以二分省略修复，不能通过调小 lexical limit 掩盖。

## 真实四问题 Before / After

Provider input/output token 口径与 `research/before-baseline.md` 一致；After 的 citation unresolved 均为 0（finalizer 成功且所有 visible source handle 可解析）。人工质量是本次对答案正文的 10 分制复核，不是自动指标或 human gold。

| Case | Before → After Trace | Tool sequence / rounds | Retrieval coverage | Tool/result + provider tokens | Citation | 人工答案质量 |
| --- | --- | --- | --- | --- | --- | --- |
| 综合 GitHub / Skills / 资源 | `trace-0f20c501badd495f8cc9064439ae6327` → `trace-6ca8d89c59314618b71ad908e77fe108` | lexical → lexical → lexical；3 calls / 1 round | lexical 93/93、32/32、0/0，均 complete；均 `limit=5000`、context source 0 | Tool est. 22,710，1 projection truncated；input 33,944，output 2,179 | 3 / 0 | Before 6–6.5；After 7.5：按仓库/Skill/学习资源分组并保留链接，明确只列代表性条目；仍不是唯一实体全量枚举 |
| Agent 学习资料 | `trace-0b2409b0c5104cf78b57004ac949b8be` → `trace-f8436e5c895648f78683597660266ade` | lexical → semantic；2 calls / 1 round | lexical 192/192 complete；semantic 11 hits、100 messages，partial=false、truncated=true（expanded 134），`dense_top_k=40` | Tool est. 26,193，1 projection truncated、省略 69 hits；input 35,375，output 2,782（cached 4,608） | 1 / 0 | Before 7；After 8.5：找回并保留 joye Agent 入门指南 URL，不再错误断言“无链接”；同时明确检索边界 |
| taste-skill | `trace-621002d125374e90910c2b8283927698` → `trace-11abb471a2384ebabe83b4b93bfbed0a` | lexical → semantic → get_message_context；3 calls / 2 rounds | lexical 1/1、5 messages complete；semantic 20 hits、100 messages，partial=true、truncated=true、coverage partial，`dense_top_k=40`；explicit context 继续 bounded | Tool est. 15,064；input 43,989，output 2,206（cached 22,784） | 2 / 0 | Before 7.5；After 8.5：明确阿鑫的测试行为与他人对产出的评价，不把 joye 看过/评价推成独立使用 |
| DeepSeek 项目 | `trace-c0b77d168967490babe7130402050bbf` → `trace-cb18866a6ded4196b0e861fa6cb3709c` | lexical；1 call / 1 round | lexical 40/40 complete，partial=false、truncated=false，`limit=5000` | Tool est. 7,882；input 17,713，output 1,262（cached 9,472） | 1 / 0 | Before 8.5；After 8：日期改为可读区间且保留主要链接，但本次正文未列出 name-only `deepseek helan`、dsh-web-ui/整合包，存在 `ENUMERATION_INCOMPLETE` |

### After 质量判断与 Failure Label

- A：`retrieval_recall` 与 `evidence_coverage` 明显改善；visible answer 没有把 93 条消息当成 93 个实体，但“代表性”仍意味着 `enumeration_completeness` 未满分。
- B：指定 URL 的 `MISSING_EXPLICIT_RESOURCE` 已解决；semantic expansion 与 lexical model projection 都有边界，答案没有把未见内容写成强否定，不触发 `PARTIAL_TO_NEGATIVE_ASSERTION`。
- C：扩大语义覆盖没有导致更大胆推断；`INTENT_TO_ACTUAL_USE`、`REVIEW_TO_PERSONAL_USAGE` 均未在 visible answer 触发。
- D：lexical coverage 完整且日期/主要链接可读，但最终正文在本次 run 漏掉 name-only `deepseek helan`、dsh-web-ui/整合包，属于 `ENUMERATION_INCOMPLETE`，需要后续 evidence/枚举评估，不在本任务增加特例检索。
- 全部 After Run 的 `citation unresolved=0` 只证明 source handle 语法与 current-run provenance 正确，不证明每个 claim 的事实蕴含正确。

## 未解决边界

### Retrieval Coverage Failure

`ENUMERATION_INCOMPLETE` 仍存在于 DeepSeek 的项目清单（dsh-web-ui/整合包未在最终正文展开），A 也只输出代表性资源。该问题不能靠继续扩大 lexical hard cap 直接证明解决；需要下一轮有标注的实体/枚举评估。

### Claim Grounding Failure

扩大 recall 后，A 的 visible answer 已比 Before 更谨慎，但仍依赖模型把推荐、分享、自荐和价值评价分组；C 的当前 run 已通过 intent/review safety，不能据此宣称整个 claim-grounding 问题已解决。后续若复现 `MENTION_TO_RECOMMENDATION`、`HIT_COUNT_TO_UNIQUE_ENTITY_COUNT` 或 `PARTIAL_TO_NEGATIVE_ASSERTION`，应保存具体 evidence/claim 并单独开启 Evidence/Claim Grounding 任务。本任务不继续加入 query 特例或重构 Evidence。
