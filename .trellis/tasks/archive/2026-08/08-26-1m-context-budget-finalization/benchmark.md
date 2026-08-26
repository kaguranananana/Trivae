# 1M Context Budget Calibration Benchmark

## Scope

本 benchmark 只测量现有 `Tool Result -> model projection` 边界和 SQLite archive 的运行事实，不给回答质量打分，也不把 visible token 增加自动解释为答案更好。

- synthetic fixture：`Agent` 与 `https` 两类正文形态，100/300/1000 个 hit。
- archive fixture：读取当前 `data/trivae.sqlite3` 的真实 canonical read/retrieval 链路，规模同上。
- variants：`fixed-16k`、`dynamic-run-128k`、`dynamic-run-256k`；另保留 `historical-dynamic-run-64k` 作为上一轮参照。
- 1M dynamic 条件的 per-call ceiling 固定为 `min(floor(1,000,000×50%), 128,000)=128,000`；run-level 条件分别显式覆盖为 128k/256k。

运行命令：

```text
.venv/bin/python .trellis/tasks/08-26-1m-context-budget-finalization/benchmark.py
.venv/bin/python .trellis/tasks/08-26-1m-context-budget-finalization/archive_benchmark.py
```

## Synthetic median results

表中 `visible` 是可见 message 数，`tokens` 是 Host projection estimate，`omit` 是 context/hit omission 合计，`trunc` 是 projection 是否发生截断，`ms` 是 projection median。

| query / hits | fixed-16k | dynamic-run-128k | dynamic-run-256k |
|---|---:|---:|---:|
| Agent / 100 | 100 / 14517 / 0 / yes / 32.953 | 100 / 30250 / 0 / no / 12.069 | 100 / 30250 / 0 / no / 11.944 |
| Agent / 300 | 141 / 15895 / 159 / yes / 235.814 | 300 / 90450 / 0 / no / 37.223 | 300 / 90450 / 0 / no / 37.757 |
| Agent / 1000 | 141 / 15896 / 859 / yes / 1523.194 | 1000 / 122485 / 0 / yes / 403.383 | 1000 / 122485 / 0 / yes / 402.153 |
| https / 100 | 100 / 15547 / 0 / yes / 34.483 | 100 / 31280 / 0 / no / 12.580 | 100 / 31280 / 0 / no / 12.653 |
| https / 300 | 129 / 15894 / 171 / yes / 248.442 | 300 / 93613 / 0 / no / 37.199 | 300 / 93613 / 0 / no / 37.329 |
| https / 1000 | 129 / 15895 / 871 / yes / 1484.348 | 1000 / 122448 / 0 / yes / 474.374 | 1000 / 122448 / 0 / yes / 475.510 |

结论：dynamic 在 300 条时恢复全部 message 且没有 omission；1000 条时仍受单次 128k cap 的真实边界约束，保留 truncation 事实。由于 fixture 每行只有一个 Tool call，128k 与 256k 的 visible projection 相同；这不能证明两个 run pool 在多 Tool call 场景等价，只说明单 call per-call ceiling 先成为瓶颈。

## Archive median results

同样字段下，archive 的 retrieval latency 单独记录，避免把 SQLite/FTS 成本误归因于 token projection。

| query / hits | fixed-16k | dynamic-run-128k | dynamic-run-256k |
|---|---:|---:|---:|
| Agent / 100 | 100 / 12028 / 0 / no / 13.298 | 100 / 12028 / 0 / no / 14.066 | 100 / 12028 / 0 / no / 12.991 |
| Agent / 300 | 133 / 15924 / 167 / yes / 270.668 | 300 / 36749 / 0 / no / 41.051 | 300 / 36749 / 0 / no / 39.087 |
| Agent / 1000 | 133 / 15926 / 556 / yes / 883.393 | 689 / 123787 / 0 / yes / 148.973 | 689 / 123787 / 0 / yes / 145.032 |
| https / 100 | 100 / 12915 / 0 / no / 13.092 | 100 / 12915 / 0 / no / 12.767 | 100 / 12915 / 0 / no / 12.955 |
| https / 300 | 124 / 15923 / 176 / yes / 269.382 | 300 / 40247 / 0 / no / 38.455 | 300 / 40247 / 0 / no / 38.378 |
| https / 1000 | 124 / 15925 / 876 / yes / 1600.066 | 939 / 127830 / 61 / yes / 1131.281 | 939 / 127830 / 61 / yes / 1001.095 |

archive 1000 条的 `dynamic-run-128k` 与 `dynamic-run-256k` 仍有相同 per-call visible/omission；`256k` 只留下更多 run pool 余额。`https/1000` 的 256k projection latency 在这次单 call 测量中低于 128k，但不构成质量或稳定性结论。

## Calibration decision

- dynamic 默认和 1M verified context 解析已经落地。
- per-call 128k 是当前明确 safety ceiling。
- run-level 128k/256k 已有 synthetic/archive operational comparison，但真实 provider A/B 未形成有效完成样本时，不宣布 256k 是质量最优默认。
- known context 的通用公式仍是 `min(floor(context×25%), 256k)`，所以 1M 的默认计算值为 250k；实验 override 只用于校准和 rollout 控制，不能与 per-call 128k 混称。
