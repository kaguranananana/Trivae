# Before Baseline

## Real answer traces

| Case | Before Trace | Tool sequence / calls / rounds | Retrieval | Tool Result / provider tokens | Citation | 人工质量 |
| --- | --- | --- | --- | --- | --- | --- |
| 综合资源 | `trace-0f20c501badd495f8cc9064439ae6327` | lexical → semantic / 2 / 1 | lexical 31/31 complete；semantic 9 hits、74 messages complete | tool est. 14396；input 24546；output 2064 | 1 / unresolved 0 | 约 6～6.5；把消息 hit 与资源价值/唯一资源混淆 |
| Agent 学习资料 | `trace-0b2409b0c5104cf78b57004ac949b8be` | semantic → lexical / 2 / 1 | semantic 26 hits、100 messages partial/truncated；lexical 31/31 complete | tool est. 17191；input 27705；output 1891 | 1 / unresolved 0 | 约 7；漏 joye URL 并错误称无链接 |
| taste-skill | `trace-621002d125374e90910c2b8283927698` | lexical → semantic / 2 / 1 | lexical 1 hit、5 messages；semantic 5 hits、65 messages；complete | tool est. 8548；input 19042；output 1224 | 2 / unresolved 0 | 约 7.5；把发起测试/评价产出推成二人均实际使用 |
| DeepSeek | `trace-c0b77d168967490babe7130402050bbf` | lexical → lexical / 2 / 1 | 8/8 + 10/10 complete | tool est. 4745；input 16113；output 1209 | 1 / unresolved 0 | 约 8.5；positive control，但漏 name-only 项且显示原始毫秒时间 |

Provider input/output tokens 为该 Trace 内 usage events 求和；Tool Result estimate 为现有 trace 等价字段。After 阶段必须用同一提取方式，避免口径漂移。

## Recovered original questions

1. `最近的这一个月之内，有没有讨论过一些有价值的 GitHub 仓库、Skills、有价值的一些资源之类的东西`
2. `最近一个月群里推荐过哪些 Agent 学习资料？`
3. `群里对 taste-skill 的评价是什么？有没有人实际用过？`
4. `最近两周讨论过哪些 DeepSeek 相关项目？`

## Known explicit resource

Agent 学习资料 Case 的真实消息包含：

`https://www.joyehuang.me/blog/20260517---agentonboardingguide/post`

After 回答必须保留该 URL；若 retrieval/projection 不完整，不得声称“没有链接”。

## Read-only SQLite performance baseline

Archive 约 473,236 messages。

| Query | Candidate limit / returned | Median DB duration |
| --- | --- | ---: |
| `Agent` | 100 / 100 | 107.651 ms |
| `Agent` | 300 / 300 | 107.533 ms |
| `Agent` | 1000 / 689 | 110.992 ms |
| `https` | 1000 / 1000 | 131.272 ms |
| `https` | 3000 / 2779 | 146.048 ms |
| `https` | 5000 / 2779 | 144.607 ms |

Context 2/2 的对照：

- `AI` 100 direct hits → 490 expanded candidates，约 15.528 s。
- `AI` 300 direct hits → 1411 expanded candidates，约 45.311 s。

结论：纯 FTS 扩到 1000/5000 仍为合理 interactive 范围；context expansion 的逐 hit I/O 才是主要性能风险，需要独立 source-hit budget。
