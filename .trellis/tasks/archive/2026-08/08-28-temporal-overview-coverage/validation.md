# Temporal overview coverage：验证记录

## 1. Root Cause replay

只读检查真实 Trace `trace-3ca9975108534180b73ce7f518d7c1c4` 与
`data/trivae.sqlite3`：

- `archive_latest=1786847688000`，即 `2026-08-16T02:34:48.000Z`。
- relative two-day window 为 `[1786674888000,1786847688001)`，即
  `[2026-08-14T02:34:48.000Z,2026-08-16T02:34:48.001Z)`。
- canonical count 为 `2699`；旧 Trace 只返回 `100`，model projection 未达到 token truncation。
- 因此旧根因是 recent 复用 structured `100` hard cap 且没有 continuation；六月/八月错配是
  Host range 没有成为统一的 UTC metadata，模型自行从原始毫秒推导日期。

## 2. Real database Case A-E

验证脚本只使用 SQLite read-only connection 和现有 Capability/Tool/Evidence projection。

| Case | 输入 | total | returned/retrieved | projected | omitted | coverage/truncated |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| A | `GetRecentMessagesInput()`，relative 2 day | 2699 | 1000 | 164 | 836 | partial / true |
| B | relative 1 day，`archive_latest` | 911 | 911 | 170 | 741 | complete / false |
| C | two-day explicit page，`limit=1000` | 2699 | 1000 | 165 | 835 | partial / true |
| D | 2026-08-15 22:00–23:00 UTC | 1 | 1 | 1 | 0 | complete / false |
| E | archive latest 之后的 future window | 0 | 0 | 0 | 0 | complete / false |

Case A 的 default 页面明确 partial；它不会把 1000 条写成整个窗口。Case C 原样回传三页
cursor 后得到 `1000 + 1000 + 699 = 2699`，page overlap `0`，unique message count `2699`，
末页 coverage complete。所有窗口使用 half-open boundary，citation canonical timestamp 经过
同一范围校验。

## 3. Performance smoke

同一只 read repository 先预热，随后每个 limit 取 3 次稳定样本的 median；当前库总消息数为
`473236`，two-day window 为 `2699`。model projection budget 为 `16000` estimate tokens。

| limit | retrieve | record | projection | retrieved/projected | omitted | estimate | Trace result payload |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 28.51 ms | 0.15 ms | 2.07 ms | 100/100 | 0 | 9807 | 1143 B |
| 1000 | 33.56 ms | 1.57 ms | 125.20 ms | 1000/165 | 835 | 15876 | 1146 B |
| 5000 | 39.43 ms | 4.71 ms | 513.51 ms | 2699/175 | 2524 | 15911 | 663 B |

独立 tracemalloc diagnostic peak 为约 `0.44/4.08/11.39 MB`（100/1000/5000）。tracemalloc 会
影响耗时，因此该列只作为对象分配量的诊断，不作为生产 latency SLA。Trace result payload
保持 bounded，不复制 2699 条正文。

## 4. Quality gates

最终实现完成后执行并记录：

```text
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests
./.venv/bin/mypy src
python3 -m compileall -q src tests
git diff --check
python3 ./.trellis/scripts/task.py validate temporal-overview-coverage
```

目标是全量 pytest、静态检查、编译、Trellis task contract 和 whitespace 检查全部通过；任何
失败都先修复实现主链路，不修改测试掩盖失败。
