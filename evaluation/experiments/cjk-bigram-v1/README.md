# CJK bigram v2 独立实验（2026-10-20）

先读 [report.md](report.md)。该实验不改写已有 benchmark 或 sealed holdout。

- [queries.json](queries.json)：64个固定字面Query；类别数量20/12/12/12/4/4。
- [oracle-v2-summary.json](oracle-v2-summary.json)：正式质量结果，含逐题分子分母、macro/micro及分类结果；其中时序为与Agent并发的原始记录，不作为最终延迟headline。
- [oracle-correction.json](oracle-correction.json)：LIKE 在 NUL 后漏读的修订记录；Query与Scope未改。
- [results-summary.json](results-summary.json)：首版LIKE Oracle结果，保留审计，**不得用于质量claim**。
- [metrics-derived.json](metrics-derived.json)：固定44条中文/混排和32条纯中文切片。
- [latency-final.json](latency-final.json)：Agent/测试结束后的独立warm SQL延迟，320样本/侧。
- [agent-summary.json](agent-summary.json)：真实Flash、7完整配对+1中断的脱敏结果与32–33次HTTP尝试账目。
- [面试与简历证据](../../../interview-docs/CJK检索实验-简历与面试.md)。

私有正文、完整身份、快照、FTS数据库、Reference、全深度排名、失败样例、Trace和审核包只保存在 ignored `data/evaluation/cjk-bigram-v1/`。其中 `oracle-v2` 通过符号链接复用完全相同的快照/FTS；不要移动链接目标。快照中的会话/Trace表由本次真实Application使用，messages及其canonical revision保持不变。

## 从可用快照复现

在项目根目录执行。输出目录必须不存在，不覆盖既有结果：

```bash
uv run python scripts/cjk_bigram_benchmark.py prepare --root data/evaluation/cjk-replay --source data/trivae.sqlite3
uv run python scripts/cjk_bigram_benchmark.py discover --root data/evaluation/cjk-replay
uv run python scripts/cjk_bigram_benchmark.py freeze --root data/evaluation/cjk-replay
uv run python scripts/cjk_bigram_benchmark.py run --root data/evaluation/cjk-replay
uv run python scripts/cjk_bigram_benchmark.py time --root data/evaluation/cjk-replay
```

`queries.json`已固定，discover仅解释混排词来源，不在重放时更换题目。上述命令使用当前指定数据：要复现本次精确指标，必须使用保存的原快照；当前生产数据继续变化时不能期待相同数字。

本次Oracle修订显式使用相同索引并登记原build.json：`run --root data/evaluation/cjk-bigram-v1/oracle-v2 --reuse-indexes`。新一轮默认应完整build；不改metadata绕过校验。

真实Agent入口为 `uv run python -m scripts.cjk_bigram_agent`；它读取显式`.env`并预检官方Flash，执行预先冻结的8题、最多40次HTTP，不使用mock。该入口固定本次ROOT且拒绝覆盖已有agent目录，不能直接重跑本次记录。`--continue-interrupted`只用于报告中已经登记的首批中断续跑，预扣19次HTTP并跳过已完成项/中断A；不是通用失败重试开关。后续独立实验需新ROOT、题目登记与预算，不复用首批计数。

`uv run python -m scripts.cjk_bigram_report`是本次产物的审计/报告生成器，依赖保存的首批与续跑记录；只创建新的派生JSON，防止覆盖原始证据，不是通用Benchmark runner。公开数字全部由本地真实结果生成，人工审核状态保持false。
