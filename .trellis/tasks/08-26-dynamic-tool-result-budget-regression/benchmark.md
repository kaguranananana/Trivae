# Benchmark

## 口径

- synthetic fixture 固定生成 canonical message，Agent 与 `https` 只代表两类正文形态；两类均通过同一个现有 projection boundary，单次 Tool call 按构造固定为 1。
- synthetic 每个 cell 重复 3 次，记录 projection latency 中位数；`build_ms` 是建立 canonical `ToolResultRecord` 的一次测量，不把 provider 网络延迟混入。
- `dynamic-128k` 使用显式 `context_window_tokens=128000`、50%，所以 run pool 和首个 Tool effective budget 都是 64000。
- `visible` 是 model projection 中的可见 message 数；`omit` 是 direct-hit omission，synthetic 没有邻居 context，因此 omitted context 恒为 0。

## Deterministic synthetic measured facts

| fixture | requested / canonical | fixed：tokens / visible / omit / truncated / projection ms | dynamic-128k：tokens / visible / omit / truncated / projection ms |
| --- | ---: | --- | --- |
| Agent | 100 / 100 | 14517 / 100 / 0 / yes / 7.798 | 30250 / 100 / 0 / no / 2.830 |
| Agent | 300 / 300 | 15895 / 141 / 159 / yes / 38.683 | 56050 / 300 / 0 / yes / 16.497 |
| Agent | 1000 / 1000 | 15896 / 141 / 859 / yes / 143.197 | 63913 / 571 / 429 / yes / 159.259 |
| https | 100 / 100 | 15547 / 100 / 0 / yes / 7.654 | 31280 / 100 / 0 / no / 2.920 |
| https | 300 / 300 | 15894 / 129 / 171 / yes / 42.133 | 59213 / 300 / 0 / yes / 17.395 |
| https | 1000 / 1000 | 15895 / 129 / 871 / yes / 151.103 | 63850 / 521 / 479 / yes / 166.907 |

Observed interpretation：dynamic 在 300 条时保留了全部 direct hits；在 1000 条时受 64k run pool 约束仍然发生显式 omission，但可见消息数明显高于 fixed。`truncated=yes` 不等于全部 direct hit 被省略，必须同时读取 omission metadata。canonical 数量在两种模式下都保持完整。

复现命令：

```text
./.venv/bin/python .trellis/tasks/08-26-dynamic-tool-result-budget-regression/benchmark.py
```

## Read-only SQLite archive benchmark

这是同一代码版本上对本地 archive 的补充测量，数据约 473236 条 canonical message；每个检索/建 record/projection cell 为 warm 三次重复中位数。两种模式复用同一 retrieval/canonical 输入，故 retrieval 与 build 不因预算模式改变。

| query | limit | total / returned / canonical | retrieval ms | build ms | projection ms fixed / dynamic | tokens fixed / dynamic | visible fixed / dynamic | truncated fixed / dynamic | omitted hits fixed / dynamic |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Agent | 100 | 689 / 100 / 100 | 104.885 | 0.333 | 2.384 / 2.281 | 12028 / 12028 | 100 / 100 | no / no | 0 / 0 |
| Agent | 300 | 689 / 300 / 300 | 107.540 | 0.557 | 37.560 / 6.930 | 15924 / 36749 | 133 / 300 | yes / no | 167 / 0 |
| Agent | 1000 | 689 / 689 / 689 | 103.457 | 1.433 | 94.250 / 108.900 | 15926 / 63892 | 133 / 511 | yes / yes | 556 / 178 |
| https | 100 | 2779 / 100 / 100 | 123.891 | 0.308 | 2.508 / 2.455 | 12915 / 12915 | 100 / 100 | no / no | 0 / 0 |
| https | 300 | 2779 / 300 / 300 | 134.150 | 0.787 | 40.977 / 7.372 | 15923 / 40247 | 124 / 300 | yes / no | 176 / 0 |
| https | 1000 | 2779 / 1000 / 1000 | 152.485 | 2.498 | 145.797 / 158.883 | 15925 / 63831 | 124 / 481 | yes / yes | 876 / 519 |

该 archive 测量证明的是 projection 预算与可见 evidence 边界，不是答案正确率。1000 条时 dynamic 仍按 64k pool 截断；这属于显式可观测边界，而不是扩大 retrieval hard cap。
