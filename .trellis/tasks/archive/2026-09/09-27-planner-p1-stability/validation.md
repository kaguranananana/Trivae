# Validation

> 2026-09-27 补充：下文 `Gate` 的 `PASS` 记录的是 assistant provisional review 时点。assistant blind adjudication 完成后的最新 P2 promotion gate 为 `FAIL`；见 `experiment-final/assistant-blind-adjudication-unblinded.md`。代码测试结果不受这次文档揭盲影响。

## Formal Planner-only identity

- 正式实验 `experiment-final/run-config.json`：source commit `d4b20deda37f71bf8e2c252d59aee5b0a0bacef3`，P0 prompt source `12f2f75eb1c9e52171ba04c35c8817ce2c6028b5`，P1 implementation/prompt source `68286d569025718c88029b66bc028e89a5a10c72`。
- 8 条已暴露 Development Case × 5 repeats × P0/P1/P2 = 120 单次 Provider calls，顺序按 Case/repeat 轮换；DeepSeek `deepseek-flash`、JSON mode、2048 completion ceiling、同一 compact Snapshot 与七 Tool allowlist。P0/P1 `low`，P2 已验证 Planner 专属 `none`。没有自动 retry、Runtime Tool Loop、E2E、Holdout 或生产 route policy 改动。
- 独立校验命令核对 120 唯一 run ID、每 Case/repeat 三路恰好一次、P0/P1/P2 exact prompt 与 provider request、`provider_length` 阶段、metrics 原始记录再计算、40 组盲审 A/B/C 映射和 packet 不泄漏版本标签，全部通过。每条记录保留 run ID、Case source/version、prompt、request、provider/model、latency、usage、finish、raw、parse/Plan/failure、cost unavailable。

## Formal results

| Metric | P0 | P1 | P2 |
| --- | ---: | ---: | ---: |
| Valid Plan | 35/40 | 36/40 | 40/40 |
| `provider_length` | 5 | 4 | 0 |
| Invalid JSON / timeout / empty / generation error | 0 | 0 | 0 |
| Input tokens | 17,490 | 49,970 | 46,330 |
| Output tokens | 55,943 | 50,752 | 6,504 |
| Total tokens | 73,433 | 100,722 | 52,834 |
| Mean / median latency | 6.70 / 6.54 s | 6.70 / 6.33 s | 1.36 / 1.36 s |
| Mean successful Plan steps | 3.94 | 2.19 | 1.98 |
| Mean prompt chars | 1515 | 5568 | 5174 |
| Monetary cost | unavailable | unavailable | unavailable |

`reasoning_tokens` 对 P0/P1 40/40 有 Provider 明细，对 P2 0/40 未返回，故 P2 标记 unknown，不写成零。P2 相比 P1 input −7.3%、output −87.2%、total −47.5%、平均 latency −79.7%。这些是本 Development 调用的观测，不是长期成本预测。有效 Plan 平均步骤数仅供诊断，不能直接当质量分数。

## Quality and limits

正式随机盲包和 key 分开；assistant 揭盲后的八轴观察在 `assistant-provisional-review.md`。P2 dependent/archify 5/5 保留实体及 direct share→context/firsthand 关系，aggregation/rank 5/5 只 schema→SQL，zero-result 5/5 只完整日窗口读取。cite-archify 3/5 次含 recent，是局部范围疑点；human adjudication 尚无，assistant provisional review 不构成 Router label 或 production gate。没有运行 Runtime，因此不声称实际空窗证明、检索质量或最终答案改善。

## Static and deterministic checks

- `.venv/bin/pytest -q`：632 passed。
- `.venv/bin/pytest -q tests/test_query_execution_core.py tests/test_agent_runtime.py tests/test_router_jev.py tests/test_evidence.py tests/test_web_streaming_contract.py`：144 passed。
- `.venv/bin/ruff check src tests`：passed。
- `.venv/bin/ruff check evaluation/planner-p1-stability`：passed。
- `.venv/bin/mypy src`：115 source files passed。
- `git diff --check` 与 staged diff check：passed。
- `task.py validate 09-27-planner-p1-stability`：passed。

## Gate

`PASS` — **限于已暴露 Development Case 的 Planner-only quality/reliability gate**。P2 40/40 有效、不劣于本轮 P0 35/40；`provider_length` 由本轮 P1 4/40 降为 0/40，探索性同提示 24/24 也无此类失败；主要 Plan 质量收益在 assistant provisional review 中无明显整体回退，prompt/token/latency 已记录，原始失败和盲包齐全，检查通过。样本规模无法证明真实失败概率为零；人工盲审待完成，尤其检查 cite-archify 的 recent 选用。可准备下一阶段 `Standard vs Planned-P0 vs Planned-P2` 设计，但本轮不运行 E2E，也不作生产 gate 或收益声明。
