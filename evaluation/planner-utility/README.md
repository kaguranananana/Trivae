# Planner-specific Utility Development Suite v1

`planner-utility-development@v1` 有 15 条 Case：11 条复用既有 Development CaseBundle，4 条新增但已暴露的 CaseBundle。所有 Case 绑定既有 `resume-benchmark-v1` Snapshot；这是 Development 子集，不是 fresh、blind 或 Holdout。`manifest-v1.json` 逐条标明来源与 workload slice。候选类型只说明要检验的任务结构，不是 expected route，也不是 treatment utility label。

新增的 count、ranking、aggregation Case 使用当前 canonical SQLite 的 UTC 半开区间 `[1786752000000, 1786838400000)` 确定性事实，分别为总数 883、最多消息的会话 `qq:677019167` 共 224 条、`text=814` 与 `reply=17`。这些数值被写入 CaseBundle，四个新增 Case 的 GT 适用性已由人工 Accept；当前 v2 的答案质量另作 treatment 裁决。新增 dependent Case 复用已知 canonical 分享/回复消息对，问题明确要求先定位分享再追踪后续评价；其 target 集合仍未证明 corpus-exhaustive。

## Treatment Utility 人工裁决

`adjudication-v1.json` 当前有 6 道 Case 的 2026-09-26 v2 正式裁决；其中 `dev-zero-empty-3` 与 `dev-context-archify` 各含两组 v2 paired observation，其余四题各一组。正式 v2 合计为 `planned_beneficial=0`、`standard_preferable=2`、`indifferent=4`、`uncertain=0`。另外 9 道旧 Variant 输出也已人工审阅，但仍在正式 v2 artifact 中保留 `pending` + `uncertain`，不冒充当前 v2 run。15 道逐题理由和跨版本统计见 `human-review-2026-09-27.md`；跨版本合计 `0 / 4 / 11 / 0` 不是单一 v2 的正式统计。人工裁决先对相同 Snapshot、Variant 与成对 run 的答案和 Evidence 做盲配对审阅，再揭示 Standard/Planned 身份。每条已裁决记录必须填写 `snapshot_id`、两路 `variant_id`、所审 `run_id`、`reviewer`、`reviewed_at`、`rationale` 和质量轴；分析器拒绝与当前 run/Snapshot/Variant 不符的标签。

合法 treatment label：

- `planned_beneficial`：Planned 在任务完成、正确性、证据、上下文恢复或可依赖性上有可核验收益。
- `standard_preferable`：Standard 在任务完成、正确性、证据或可靠性上更好，或 Planned 有可核验损害；说明具体依据。
- `indifferent`：两路在已核验的质量和任务完成上等效，成本差异另行记录。
- `uncertain`：证据、重复性或人工一致性不足，不能决定。

`quality_axes` 分别记录 answer correctness、evidence completeness、context recovery、groundedness/citation、zero-result correctness、reliability 的 `planned` / `standard` / `same` / `uncertain` 方向和简述。`uncertain` 也用于说明某轴不适用于当前问题，不能据此推断整体标签不确定。Latency、token 与 Provider 真正返回的 cost 是 trade-off，不覆盖质量判断，不合成单分数。自动指标的 `same` 只表示可比字段相同，不能直接填 `indifferent`。对重复观察方向冲突的 Case 保留 `uncertain` 或说明不稳定性。

Jev 旧 16 条人工 route label 仍属于 **Route Classification**。本文件标签属于 **Treatment Utility**，只能由两路结果推导或人工裁决，不从 route label 反推。`analyze_router_utility.py` 对已裁决标签分别给出 planned→standard 与 standard→planned 误路由，对待裁决数据只展示路线与逐轴结果；Rule gate 和 Jev Provider 分开统计。当前生产 Jev 仍为 `shadow`。

## 本地执行入口

重复 `--cases-dir` 可把已有 Development 与新增 CaseBundle 一起加载；先用 `trivae benchmark gate`、`trivae eval cases validate` 和 Variant diff 做 preflight，再使用 `trivae benchmark run --paired-by-case --paired-order counterbalanced`。`execution-order.json` 在第一条请求前 create-only 落盘。真实运行须使用新提交 pin 的两个 Variant，且输出目录与 Evaluation DB 必须不存在。

`scripts/run_router_utility_jev.py` 对相同 CaseBundle 仅调用 Rule gate 和 Jev；`scripts/analyze_router_utility.py` 离线连接 forced raw、Evaluation DB、Jev route 和人工裁决。下方 15×2 命令是归档 v1 全量实验的复现参考；当前 root-cause / v3 工作只允许按新 Trellis task 中记录的 targeted Case、repeat 与预算执行，不据此启动 15 Case 全量运行。

2026-09-26 已归档阶段的 Provider 预算按**请求次数**计算：目标 30～40、阶段上限 60；该阶段结束时 ledger 为 47。每组 paired run 预留两路最多 8 个 Runtime turn 加 1 个 Planner 请求，即 17 次；若还要在同一 Case 执行 Jev，额外预留 1 次。后续获准的 v2 dependent 与数值 control 运行又增加 27 次；截至 2026-09-27，从所有本地 raw 与 canonical Trace 起点重建的累计 ledger 为 74 次（Planner 11、Runtime 61、Existing Router LLM 0、Jev 2）。这 74 次是累计观测，不是新的预算上限。后续真实运行必须先为新批次计算单独的最坏调用上界，并在每批后重建 ledger。账本按 `planner.started`、`model.turn.started` 和非 Rule gate Jev attempt 保守计数；失败/缺失 usage 仍占次数，cost 未返回则保持 unavailable。

以下是归档 v1 全量实验的复现参考，不是当前 v3 执行计划。当前 root-cause task 应先完成 Trace 归因，再只运行 dependent、archify、一个 negative control 与一个 zero-result Case。任何真实运行都要为自己的 paired repeat 数按两路各最多 8 个 Runtime turn、Planned 1 个 Planner request 计算理论上界；输出路径需保持不存在，并在新 execution commit 捕获 Environment 后运行 gate。历史 15 Case × 1 对 forced treatment + 每 Case 最多 1 次 Jev route 的理论上界为 270 次 Provider invocation。

## Targeted v3 execution pin（2026-09-27）

Root cause 与 Runtime anchor-preservation 调整的代码版本为 `4a4675ef99fee00fc367ba7a98115a4fc5c51a82`。新的 Standard/Planned Variant 与两个小型 Suite 在 `targeted-v3-experiment.json`、`evaluation/variants/`、`evaluation/suites/` 中锁定；Controlled Variant configuration diff 仅为 `execution_override.forced_route`。focus 两题各跑两组配对观察，第二 repeat 反转 arm 顺序；`pu-aggregate-utc-types` 和 `dev-zero-empty-3` 各跑一组负控制。总计 6 组 pair / 12 个 run，Provider invocation 最坏上界 102；无 Jev 调用、自动重试或 Holdout。所有原始输出、Evaluation DB、Environment、Gate 与 ledger 使用全新 `data/evaluation/planner-router-utility/2026-09-27/v3/` 路径。运行结果与 reviewer 来源在新 Trellis task 的 validation 报告中补记。

```bash
uv run --extra dev --with tqdm trivae eval --env-file .env benchmark capture-environment \
  --database data/trivae.sqlite3 --benchmark resume-benchmark-v1 \
  --output data/evaluation/planner-router-utility/next-paid/environment.json
uv run --extra dev --with tqdm trivae eval --env-file .env benchmark gate \
  --database data/trivae.sqlite3 \
  --manifest data/evaluation/planner-router-utility/next-paid/environment.json
uv run --extra dev --with tqdm trivae eval --env-file .env benchmark run \
  --database data/trivae.sqlite3 \
  --evaluation-database data/evaluation/planner-router-utility/next-paid/evaluation.sqlite3 \
  --manifest data/evaluation/planner-router-utility/next-paid/environment.json \
  --suite evaluation/suites/planner-utility-development-v1.json \
  --cases-dir evaluation/cases/benchmark/dev \
  --cases-dir evaluation/cases/planner-utility \
  --variant evaluation/variants/planner-utility-standard-20260926-v2.json \
  --variant evaluation/variants/planner-utility-planned-20260926-v2.json \
  --paired-by-case --paired-order counterbalanced --repeat 1 \
  --output-dir data/evaluation/planner-router-utility/next-paid/treatment
uv run --extra dev python scripts/run_router_utility_jev.py \
  --suite evaluation/suites/planner-utility-development-v1.json \
  --cases-dir evaluation/cases/benchmark/dev \
  --cases-dir evaluation/cases/planner-utility \
  --env-file .env \
  --output data/evaluation/planner-router-utility/next-paid/routes.json
uv run --extra dev python scripts/build_provider_invocation_ledger.py \
  --raw data/evaluation/planner-router-utility/next-paid/treatment/raw-records.json \
  --routes data/evaluation/planner-router-utility/next-paid/routes.json \
  --canonical-db data/trivae.sqlite3 \
  --output data/evaluation/planner-router-utility/next-paid/provider-ledger.json
uv run --extra dev python scripts/analyze_router_utility.py \
  --raw data/evaluation/planner-router-utility/next-paid/treatment/raw-records.json \
  --evaluation-db data/evaluation/planner-router-utility/next-paid/evaluation.sqlite3 \
  --canonical-db data/trivae.sqlite3 \
  --standard-variant-id planner-utility-standard-20260926-v2 \
  --planned-variant-id planner-utility-planned-20260926-v2 \
  --routes data/evaluation/planner-router-utility/next-paid/routes.json \
  --adjudications evaluation/planner-utility/adjudication-v1.json \
  --output data/evaluation/planner-router-utility/next-paid/router-utility.json
```

对当前 v2 已绑定的 6 道 Case，离线分析可读取本文件夹的正式裁决；余下 9 道在新的 v2 run 产生前仍为 `unadjudicated`，即使它们已有旧 Variant 的历史人工观察。当前结果没有 `planned_beneficial`；Jev production 仍为 `shadow`，没有 Holdout 实验，也不支持 production rollout 或“复杂问题 → Planned”的结论。未来的新 run 仍须另建裁决 artifact，填写对应 run ID、Variant、Snapshot、reviewer、rationale 和质量轴，再用新输出路径分析；不能复用本次或历史标签冒充新 run 的人工审阅。
