# Validation

## Planner-only identity

- ChatLab baseline commit: `3e0e0fbbfb2b80051d261d34bf8349d64ab4c6e8`。
- Trivae P0 source commit: `12f2f75`；P0 prompt 在八条 Case 上与该提交的 `_build_prompt` 输出逐字相同。P0/P1 共用当前未改动的 Plan parser、Provider completion boundary 和 `QueryContext` allowlist。
- Suite: 8 条 `planner-utility-development@v1` manifest 中的已暴露 Development Case；`run-config.json`/每条记录保存 Case 来源和版本。没有新 Holdout、sealed 或 blind generalization 数据。
- 输入：Case query、locale、同一个 compact Snapshot 和默认七个生产 Tool allowlist；无聊天正文、真实 Tool Result 或 Runtime 执行。每个 Case 每个 variant 3 次，顺序交替。
- Provider/model: DeepSeek `deepseek-flash`，temperature 0、completion max tokens 2048、JSON mode；P0/P1 仅 prompt 与 capability summary 不同。Provider 的随机性和 2048 output ceiling 保留。
- P1 运行期间把未登记 Tool guidance 的空值默认改为显式缺失错误；本实验的七个 Tool 均在 guidance 表内，48 次调用实际渲染的 prompt 已逐条保存在 `runs.jsonl`，该收紧对本轮 P1 输入没有影响。最终代码以提交后的状态为准。

## Operational results

| Measure | P0 | P1 |
| --- | ---: | ---: |
| Cases / repetitions | 8 × 3 | 8 × 3 |
| Provider calls | 24 | 24 |
| Valid Plan | 21 | 19 |
| `provider_length` | 3 | 5 |
| JSON invalid / timeout / empty | 0 / 0 / 0 | 0 / 0 / 0 |
| Input tokens | 10,494 | 29,982 |
| Output tokens | 34,250 | 35,151 |
| Total tokens | 44,744 | 65,133 |
| Mean latency | 6,525.4 ms | 7,212.7 ms |
| Median latency | 6,340.4 ms | 7,365.2 ms |
| Mean steps among valid Plans | 3.71 | 2.16 |
| Provider monetary cost | unavailable | unavailable |

全部 48 次均有 Provider/model、token usage、finish_reason、latency 和唯一 run ID；失败调用计入次数与 tokens。`runs.jsonl` 的 `parse_success` 与 `degraded/degradation_code` 分别由同条已保存的 Plan 与 failure 确定性投影，未重跑或补造 Provider 输出。`metrics.json` 保存逐 Case success 和 finish reason。Plan 原文与 JSON 在 `runs.jsonl`；盲审包 24 对，没有 P0/P1 标记，映射单独存放。没有运行 Runtime Tool Loop，也没有重新执行 Standard vs Planned E2E。

## Quality review and limits

`assistant-provisional-review.md` 对八项 rubric 和六个历史输出逐项对照。P1 成功 Plan 更少模板化步骤、通常避免机械双检索/无关身份查询，并在 dependent/archify 中强调实体与 direct-share→follow-up 证据关系；但 archify 个别 Step 仍只说“相关消息”，trend r3 仍多路径扩展。P1 的 Provider 完成率从 P0 21/24 降到 19/24，simple `dev-cite-archify` 仅 1/3 成功。当前不满足“更稳定地产生高信息量、低误导 Plan”的完整目标，不能进入 E2E 或生产收益声明。assistant 评价不是正式 human adjudication，盲包仍待人工审阅。

## Static checks

- `.venv/bin/pytest -q`: 632 passed（含新增 provider-free tests）。
- `.venv/bin/ruff check src tests`: passed。
- `.venv/bin/ruff check evaluation/planner-quality`: passed。
- `.venv/bin/mypy src`: passed（115 source files）。
- `git diff --check`: passed。
- `task.py validate`: passed。

全仓 `ruff check .` 未作为本任务 gate；已有 `.codex/.trellis/archive` lint 不在修改范围。本次修改的 `src`、`tests` 与新增 runner 均由定向 Ruff 检查覆盖。

## Repository / next stage

本任务停在 Planner Quality：P1 的 failure rate 尚不稳，先研究通用 prompt/summary 长度与 Provider `length` 的关系，并重新做 Planner-only 多次对照与人审。Router/Jev、Runtime、Retrieval、Evidence/Citation、zero-result proof 均未改；没有 push、Holdout 触碰或 E2E Treatment Utility 实验。最终提交 SHA 和工作树状态以收尾汇报为准。
