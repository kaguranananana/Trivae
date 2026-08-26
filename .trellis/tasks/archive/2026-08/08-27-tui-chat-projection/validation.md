# Validation 记录

## 自动化验证（2026-08-27）

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest -q` | **370 passed**（含新增 `test_tui_projection.py` 16 例、`test_tui_app.py` 5 例 Textual Pilot 应用测试） |
| `.venv/bin/ruff check src tests` | All checks passed |
| `.venv/bin/python -m mypy` | Success: no issues found in 88 source files |
| Plain 回归 | `tests/test_cli_renderer.py` / `tests/test_cli.py` / `tests/test_query_streaming.py` 全部未改动、全绿 |

## 真实 DeepSeek smoke（headless TrivaeChatApp，真实 provider + 真实 Canonical Store）

驱动方式：`run_test()` headless 运行真实 TUI，`_on_stream_event` 打点记录首个事件到达时间，
`export_screenshot` 输出 SVG 取证（top/final 两视角）。

### #1 简单问题「用一句话介绍你自己」（群1）

```json
{"total_seconds": 5.76, "ttft_query_started": 0.01, "first_thinking_delta": 5.7,
 "group_title": "执行过程 · 2 步 · 0.0s", "answer_chars": 44,
 "event_order": ["query.started","route.completed","thinking.delta","thinking.completed",
                 "usage.updated","answer.completed","query.completed"]}
```

结论：thinking → answer 直达链路正常；route/thinking 折叠为 2 步组；回答渲染正确。

### #2 单工具「最近群里有没有人推荐过 GitHub 上的项目或工具？」（群1）

```json
{"total_seconds": 63.97, "first_process_block": 32.63, "first_tool_block": 32.95,
 "event_order": [...,"thinking.delta","tool.started","retrieval.started","retrieval.completed",
                 "tool.completed",...,"answer.completed","query.completed"],
 "group_title": "执行过程 · 3 步 · 29s", "answer_chars": 488}
```

结论：**retrieval.completed 合并进运行中的 tool block**（无重复 Retrieval 行，3 步而非 4+ 步）；
工具行的 collapsed 行呈现计数 chips；长 thinking 期间轮容器与 route 行即时可见。

### #3 多工具+真实失败「查一下群里推荐过的学习方法…」（群1）

```json
{"total_seconds": ~46, "first_tool_block": 13.46,
 "event_order": [..., "plan.completed", ..., "tool.started","retrieval.started","retrieval.completed",
                 "tool.completed","retrieval.failed","tool.failed","answer.completed","query.completed"],
 "group_title": "执行过程 · 7 步 · 46s", "answer_chars": 369}
```

结论：planned execution 下 plan 块出现；一次工具失败后 run 继续并诚实回答（0 命中总结）；
失败块自动展开红行；查询最终 completed 正常回到输入态。

### #4 多工具 15 步「群里最近两周讨论过哪些不同的技术主题？」（群1）

```json
{"total_seconds": 76, "first_tool_block": 14.41, "group_title": "执行过程 · 15 步 · 76s", "answer_chars": 913}
```

结论：15 个过程块全程按事件流式落位、结束后单行折叠；
期间每个 tool start/complete 即时可见，无「终端完全没反应」时段。

### #5 同问题重跑触发真实 provider 失败（意外覆盖 failure matrix）

```json
{"event_order": [...,"tool.failed",...,"query.failed"], "group_title": "执行过程 · 8 步 · 45s"}
```

结论：query.failed 终态渲染 error row，历史保留，输入恢复可用；SVG 中 ✓/✗ 同时可见
（成功工具与失败工具视觉区分明确）。

## 截图取证

`/var/folders/ct/c_406rh940z5g1k0nj8vlmrw0000gn/T/opencode/smoke*/{top,final}.svg`：
top 视角含 `You > … / ▶ 执行过程 · N 步 · Xs / 回答` 三层结构；
final 视角聚焦 Markdown 渲染的回答正文；中文宽字符未破坏边框。
