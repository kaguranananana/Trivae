# Implementation Plan

## 执行顺序

1. **依赖**：`pyproject.toml` dependencies 加 `textual>=1,<2`；`.venv` 安装并记录版本。
2. **Projection 纯逻辑**（`interfaces/tui/models.py`）：
   - [ ] `TuiBlock/TuiRound/TuiChange` dataclass + `_TOOL_LABELS/_ERROR_LABELS` 复用迁移
   - [ ] ProjectionEngine：begin_round / apply(全部 17 种事件) / collapse_finished_round
   - [ ] tool identity by tool_call_id；retrieval→running-tool 合并；answer delta 累积与 completed 替换
   - [ ] expanded/manually_expanded 策略
3. **测试先行跟随**（`tests/test_tui_projection.py`）：逐条对应 PRD 测试矩阵。
4. **Widgets**（`interfaces/tui/widgets.py`）：ToolRow(focus/expand/详情 scroll)、
   PlanBlock(Collapsible)、AnswerBlock(Markdown)、ErrorRow、ProcessGroup、RoundContainer。
5. **App**（`interfaces/tui/app.py`）：布局、Input worker、Ctrl+C 双语义、running timer、
   change→widget 映射、终端态恢复 focus。
6. **CLI 接线**：`--plain` flag、isatty 判定、tui 入口分支；确认既有测试路径默认 plain。
7. **应用级测试**（`tests/test_tui_app.py`，Textual Pilot）：键盘展开/收起、输入提交回路、
   Ctrl+C 中断、多轮。
8. **全量验证**：`.venv/bin/python -m pytest`、`ruff check src tests`、
   `.venv/bin/python -m mypy src/trivae/interfaces/tui`（及项目既有 mypy 范围）。
9. **真实 smoke**（DeepSeek）：简单问题 / 单工具问题 / 多工具问题各一轮，
   记录 TTFT、首个 process/tool block、answer 开始、总耗时到 validation.md。
10. **Spec 沉淀**：product-experience-guidelines.md 增补 TUI projection contract；
    interview-defense.md 追加本次设计叙事。

## 验证命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/python -m mypy src/trivae
```

## 回滚点

- 步骤 1-3 后任意中断：删除 tui 目录与依赖行即回滚，无行为影响。
- 步骤 6 是唯一行为切换点；失败时 CLI 默认路径回退 plain 即可（保留代码）。
