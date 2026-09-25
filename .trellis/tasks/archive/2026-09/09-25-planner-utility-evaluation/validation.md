# Planner Utility Evaluation：验证记录

## 运行门槛与身份

- 起点 `6fd7e93b8c73439069a5457980e2d31f2d42f880`、本地 `main`、起始 worktree clean；已有历史和未推送提交未改写。执行冻结于 `f94fffb4d050d9c5b506480f6fce2a48a1921e96`。
- 独立 Environment gate 4/4；正式 preflight passed：官方 DeepSeek 主模型与 Planner、`shadow` Router 配置、显式主仓库 `.env`、Canonical DB、473236 lexical 消息、semantic index、Snapshot、ExecutionScope、七个 Tool、37 条 Development GT、create-only 输出/Evaluation DB、Variant 配置仅 forced route 不同。凭据值未输出。
- 冻结 commit worktree 的独立 smoke 为 4 Case × 2、8/8 completed；standard 无 Planner event，planned 4/4 Planner completed；该结果不在正式分母。先前另一次仪表 smoke 的 Provider transport/connection failures 已保留在本地，未计 Planner quality。
- 主运行 37×2×1：raw 74、Evaluation runs 74、Evaluation results 74、canonical Trace 74；37 个完整配对，route / Planner invocation / Provider-Model / Snapshot 违例均 0；37/37 planned Planner completed、standard 0 Planner call。独立 targeted repeat：6 Case × 2 Variant × 2 次，raw / Evaluation runs / Evaluation results / Trace 各 24；均与主实验分离。
- 主分析入口 `scripts/analyze_planner_utility.py` 核对 run/trace identity 并输出 `summary.json`、`run-ledger.json`、`trace-index.json` 和私有 `review-packet.json`；repeat 入口 `scripts/analyze_planner_utility_repeat.py` 核对 24 个 repetition 身份，输出 `repeat-summary.json`。产物置于 ignored `data/evaluation/planner-utility/2026-09-25/final/analysis/`，不进入 Git。

## 工程门槛

| 命令 | 实际结果 |
| --- | --- |
| `uv run --extra dev --with tqdm pytest -q` | **621 passed**（16.31s） |
| `uv run --extra dev ruff check src tests` | **All checks passed** |
| `uv run --extra dev mypy src` | **Success: no issues found in 114 source files** |
| `uv run --extra dev ruff check scripts/analyze_planner_utility.py scripts/analyze_planner_utility_repeat.py` | **All checks passed** |
| `git diff --check` | **passed**（无输出） |
| `python3 ./.trellis/scripts/task.py validate 09-25-planner-utility-evaluation` | **passed**；补齐 implement/check 的真实 spec context 后复检 |

Variant JSON 的执行配置深比较仅有 `execution_override.forced_route` 一处差异；按预期归档路径预检本轮新 Markdown relative links，missing 0；`review-packet.json` 匹配 `.gitignore` 的 `data/evaluation/` 规则。Git 变更清单不含历史 benchmark、v1 Holdout 或本地 Provider artifacts。

归档后仍需复核真实 Markdown relative links、移除本轮冻结临时 worktree，并确认主 worktree clean；这些是收尾步骤，不改变实验结果。任何后续验证失败必须更新此记录，不得沿用上表 passed 声称。
