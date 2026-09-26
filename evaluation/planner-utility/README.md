# Planner-specific Utility Development Suite v1

`planner-utility-development@v1` 有 15 条 Case：11 条复用既有 Development CaseBundle，4 条新增但已暴露的 CaseBundle。所有 Case 绑定既有 `resume-benchmark-v1` Snapshot；这是 Development 子集，不是 fresh、blind 或 Holdout。`manifest-v1.json` 逐条标明来源与 workload slice。候选类型只说明要检验的任务结构，不是 expected route，也不是 treatment utility label。

新增的 count、ranking、aggregation Case 使用当前 canonical SQLite 的 UTC 半开区间 `[1786752000000, 1786838400000)` 确定性事实，分别为总数 883、最多消息的会话 `qq:677019167` 共 224 条、`text=814` 与 `reply=17`。这些数值被写入 CaseBundle；回答的语义对应、citation 和最终 treatment 判断仍需人工审阅。新增 dependent Case 复用已知 canonical 分享/回复消息对，问题明确要求先定位分享再追踪后续评价；新问题的 GT 适用性标为待人工审阅，没有把旧 Case 的人工确认自动继承为新问题的确认。

## Treatment Utility 人工裁决

`adjudication-v1.json` 初始 15/15 为 `pending` + `uncertain`。人工裁决先对相同 Snapshot、Variant 与成对 run 的答案和 Evidence 做盲配对审阅，再揭示 Standard/Planned 身份。每条已裁决记录必须填写 `snapshot_id`、两路 `variant_id`、所审 `run_id`、`reviewer`、`reviewed_at`、`rationale` 和质量轴；分析器拒绝与当前 run/Snapshot/Variant 不符的标签。

合法 treatment label：

- `planned_beneficial`：Planned 在任务完成、正确性、证据、上下文恢复或可依赖性上有可核验收益。
- `standard_preferable`：Standard 在任务完成、正确性、证据或可靠性上更好，或 Planned 有可核验损害；说明具体依据。
- `indifferent`：两路在已核验的质量和任务完成上等效，成本差异另行记录。
- `uncertain`：证据、重复性或人工一致性不足，不能决定。

`quality_axes` 分别记录 answer correctness、evidence completeness、context recovery、groundedness/citation、zero-result correctness、reliability 的 `planned` / `standard` / `same` / `uncertain` 方向和简述。Latency、token 与 Provider 真正返回的 cost 是 trade-off，不覆盖质量判断，不合成单分数。自动指标的 `same` 只表示可比字段相同，不能直接填 `indifferent`。对重复观察方向冲突的 Case 保留 `uncertain` 或说明不稳定性。

Jev 旧 16 条人工 route label 仍属于 **Route Classification**。本文件标签属于 **Treatment Utility**，只能由两路结果推导或人工裁决，不从 route label 反推。`analyze_router_utility.py` 对已裁决标签分别给出 planned→standard 与 standard→planned 误路由，对待裁决数据只展示路线与逐轴结果；Rule gate 和 Jev Provider 分开统计。当前生产 Jev 仍为 `shadow`。

## 本地执行入口

重复 `--cases-dir` 可把已有 Development 与新增 CaseBundle 一起加载；先用 `trivae benchmark gate`、`trivae eval cases validate` 和 Variant diff 做 preflight，再使用 `trivae benchmark run --paired-by-case --paired-order counterbalanced`。`execution-order.json` 在第一条请求前 create-only 落盘。真实运行须使用新提交 pin 的两个 Variant，且输出目录与 Evaluation DB 必须不存在。

`scripts/run_router_utility_jev.py` 对相同 CaseBundle 仅调用 Rule gate 和 Jev；`scripts/analyze_router_utility.py` 离线连接 forced raw、Evaluation DB、Jev route 和人工裁决。完整 15×2 及重复实验只是准备状态，不在本轮预算内自动执行。

本轮 Provider 预算按 **请求次数** 计算：通常目标 30～40，绝对上限 60。每次 paired run 预留两路最多 8 个 Runtime turn 加 1 个 Planner 请求，即 17 次；若还要在同一 Case 执行 Jev，额外预留 1 次。不得在剩余额度不足整对最坏上限时启动。每个小批完成后用 `scripts/build_provider_invocation_ledger.py` 读取该批 raw、canonical Trace 和 Jev routes，create-only 写入 ignored 本地 ledger，再决定下一批。账本按 `planner.started`、`model.turn.started` 和非 Rule gate Jev attempt 保守计数；失败/缺失 usage 仍占次数，cost 未返回则保持 unavailable。历史实验的 invocation 不计入本任务新增调用。

下一轮正式实验在**新预算与人工 GT 审阅后**可使用以下命令。输出路径需保持不存在；在新干净 execution commit 先捕获 Environment 并运行 gate。若届时生产代码变化，必须重新 pin 两份 Variant。完整 15 Case × 1 对 forced treatment + 每 Case 最多 1 次 Jev route 的理论上界为 270 次 Provider invocation，因此本轮只准备命令，不执行。真实大实验应先按小型 Suite 分批运行、每批后更新 ledger；下方展示单批覆盖全 Suite 的完整入口及参数。

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

人工裁决前，最后一步仍会把方向标为 `unadjudicated`。审阅当前 run 后应在新的私有 adjudication artifact 中填写 `run_id`、Variant、Snapshot、reviewer、rationale 和质量轴，再用新的输出路径离线重算分析；不改写历史结果。
