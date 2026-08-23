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
