# TUI interaction repair implementation plan

## Execution order

1. Textual selection foundation
   - 将依赖改为 `textual>=2,<9`，更新本地环境到 8.2.8。
   - 修复唯一已知测试 API 迁移点，运行现有 TUI/CLI targeted suite，先证明基线兼容。
2. Failure Case 1 — thinking segments
   - 先加入多段 timeline/hidden/no-summary/abort failing tests。
   - additive 投影真实 turn lifecycle，reducer 改为 `thinking:<ordinal>` active segment。
   - 运行 query streaming + projection + app + plain regression。
3. Failure Case 4/6 — Tool detail and correlation
   - 先加入 Runtime record handoff、Query detail budget、same-name/乱序/explicit-parent failing tests。
   - Runtime adapter 传递同 call record；Query boundary 生成 `ToolResultDetail`；TuiBlock 合并 summary/detail。
   - 删除 last-running-tool 聚合，使用 parent identity；实现 Input/Result renderer 和 preview omission 文案。
   - 运行 runtime/query/projection/widget/app regression。
4. Failure Case 2 — Follow Tail
   - 新建 history scroll owner，替换所有无条件 `scroll_end(force=True)`。
   - 加 wheel/PageUp/PageDown/Home/End 与 streaming viewport Pilot tests。
   - 验证新 round、command note、sources/trace note 不抢历史阅读位置。
5. Failure Case 3 — selection/copy
   - Ctrl+C 改为 selection-first/running-interrupt/idle-no-op；Ctrl+Q 退出。
   - ProcessRow 限定 header click，正文不 stop selection；增加 disclosure glyph 和轻量视觉层级。
   - 加 Answer/Tool/Thinking drag selection、clipboard、toggle region Pilot tests。
6. Final answer/process regression
   - 验证 answer.delta incremental Markdown、authoritative replace、interrupt spinner cleanup、group collapse/manual state。
   - 未发现 profile 证据则不实现 batching。
7. Quality and real smoke
   - 更新两份 backend spec 与 interview-defense evidence。
   - 跑完整质量门；再用真实 `trivae chat` 做复杂问题 smoke，记录 live event order、scroll/selection/copy/tool detail/折叠行为和 provider public-summary 事实。
8. Handoff addendum slices (2026-08-27)
   - Slice A2：先写跨源一致性与孤儿 retrieval/死行/空 detail failing tests，定位双流 ID 漂移的真实差异点并统一 identity；显式暴露 record 缺失，不做静默降级。
   - Slice A3：新增"子组件冒泡 scroll"与"SGR mouse 序列端到端"两级验证；能代码级修复就修，不能则在 spec 记录终端兼容矩阵。
   - Slice A4：整理 R1 现有行为清单供用户逐项对照，不改 UI 直到拿到具体缺陷描述。
   - 验证命令沿用上方 Validation commands。

## Validation commands

```bash
uv run pytest -q tests/test_agent_runtime.py tests/test_query_streaming.py tests/test_tui_projection.py tests/test_tui_app.py tests/test_cli_renderer.py tests/test_cli.py
uv run pytest -q
uv run ruff check src tests
uv run mypy src
uv run python -m compileall -q src tests
git diff --check
python3 ./.trellis/scripts/task.py validate .trellis/tasks/08-27-tui-interaction-repair
uv run trivae chat
```

## Review gates

- 每个 Failure Case 完成后先看 targeted test，再看与上一切片相邻的 regression；不累计到最后统一排错。
- Tool detail review 必须证明 `partial/truncated` 与 `preview_truncated` 是不同字段、不同断言。
- Selection review 必须在真实 Textual selection 上断言 clipboard；不通过手工设置 bool 伪造。
- Smoke 不记录 hidden/public reasoning 正文到持久化 Trace；只记录 provider 是否提供和可见顺序。

## Rollback points

- Dependency/selection API migration。
- Thinking lifecycle/segment reducer。
- Tool record/detail/correlation vertical slice。
- Follow-tail controller。
- Header-only toggle/Ctrl+C/visual polish。

