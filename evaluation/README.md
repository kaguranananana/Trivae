# Trivae Evaluation Catalog

这里保存 version-controlled 的 Case、Suite 和 Controlled Variant 定义，不保存聊天正文、完整 Trace 或运行结果。

`cases/seed-*.json` 是第一版 Design / Seed contract 样例。它们故意使用 `unavailable` 的占位 Snapshot：真实数据 Case 必须由当前 Canonical Store 建立 Snapshot 后显式 materialize，不能把漂移数据静默绑定到旧 Case。

`variants/last-stable.json` pin 到 M6 完成后的 `cce944d`，表示当前 stable reference，不表示最优方案。`forced-standard.json` 与 `forced-planned.json` 只改变显式 execution override，供同 Case 的 Planner Utility 实验使用。

`variants/deepseek-json-budget-m7.json` 是 M7 provider-boundary candidate `deepseek-json-budget-m7-v2`：只增加显式 JSON completion budget，不能与 `last-stable-m6` 混称为同一 Variant。

运行结果、Review、Comparison 和 Failure Diagnosis 写入独立 SQLite Evaluation Store，不写入 Canonical Chat Store。

## Real snapshot and semantic smoke

当前 Canonical Store 可以通过 Application facade materialize 为不含聊天正文的 Snapshot manifest：

```bash
python -m trivae eval snapshot \
  --database data/trivae.sqlite3 \
  --output evaluation/snapshots/<snapshot-name>.json
```

该 manifest 记录 schema、source metadata、消息数量、时间范围和 lexical index presence；它不替代人工 Finding annotation。若 Snapshot 需要进入长期 Core / Calibration Suite，应在固定 Snapshot 上补充逐 Finding 的 reference evidence，并显式记录 annotation completeness 与 provenance。真实 Snapshot 只应保留在受控本地/评测环境，不把私有 source metadata 或聊天正文提交到仓库。

Semantic derived index 的状态和 rebuild 不隐式发生：

```bash
python -m trivae semantic status --database data/trivae.sqlite3
python -m trivae semantic rebuild --database data/trivae.sqlite3
python -m trivae semantic smoke \
  --database data/trivae.sqlite3 \
  --query "大家为什么觉得一些 Agent 框架太重？"
```

`semantic smoke` 默认只输出 candidate locator、score、coverage、latency 和 index identity，不输出消息正文；`--rebuild` 可显式把 rebuild 与一次 query 放在同一 smoke 中。索引缺失、stale、模型加载失败和 retrieval partial 都保持可见，不改写成 lexical success。

`semantic status`、`rebuild` 和 `smoke` 的 index projection 还包含 `operational_guidance`：missing/stale/failed/partial 指向显式 rebuild，building 指向 status polling，completed 指向 bounded smoke；CLI 不会自动执行建议命令。

## Retrieval relevance annotation

真实 lexical/semantic module comparison 使用固定 query set 与两个 retrieval-only Controlled Variant：

```bash
trivae eval retrieval-packet \
  --database data/trivae.sqlite3 \
  --queries evaluation/retrieval/semantic-vs-lexical-provisional-v1.json \
  --lexical-variant evaluation/variants/lexical-only-retrieval-control-v1.json \
  --semantic-variant evaluation/variants/semantic-only-retrieval-candidate-v1.json \
  --output-dir data/evaluation/semantic-vs-lexical-provisional-v1
```

输出目录已由 `.gitignore` 排除。`blind-packet.json` 含真实候选正文和 bounded context，但隐藏 retrieval source、rank、score 与 variant；`sealed-metadata.json` 保存 canonical identity、两种方法的 rank/score、expanded IDs 和运行诊断。两者都不得 commit 或 push。

配置好现有 OpenAI-compatible 模型环境后，可进行 LLM-assisted 初筛：

```bash
trivae eval retrieval-annotate \
  --packet data/evaluation/semantic-vs-lexical-provisional-v1/blind-packet.json \
  --sealed data/evaluation/semantic-vs-lexical-provisional-v1/sealed-metadata.json \
  --output-dir data/evaluation/semantic-vs-lexical-provisional-v1
```

`annotations.json` 中的每条自动标签固定为 `llm_assisted_provisional`，并带 confidence/notes；它不是 human ground truth。`audit-queue.json` 优先列出 uncertain、低 confidence、partial relevance、单方法前排、排名冲突和影响质量指标的 positive label。人工复核时同时查看 blind packet 和 audit queue，修改标签/notes，并仅把真实检查过的条目标记为 `human_verified`。只复核部分条目时把 annotation set 的 `annotator_type` 改为 `mixed`；全部条目复核且全部 verification status 都是 `human_verified` 后，才改为 `human`。

指标入口为：

```bash
trivae eval retrieval-metrics \
  --sealed data/evaluation/semantic-vs-lexical-provisional-v1/sealed-metadata.json \
  --annotations data/evaluation/semantic-vs-lexical-provisional-v1/annotations.json \
  --output data/evaluation/semantic-vs-lexical-provisional-v1/metrics.json
```

报告支持 Precision@k、merged-candidate-pool Recall@k、MRR、Top-k hit/success、relevant message coverage 与独立 partial relevant coverage。missing/uncertain label 会令依赖它的指标 `unavailable`，不会被当作 negative；没有 corpus-exhaustive reference 时 corpus Recall 始终 unavailable。由自动标签产生的所有数字都明确标记为 `llm_assisted_provisional`，不能作为 production gate。
