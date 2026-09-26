# 验证记录

## 不计费工程门槛

| 检查 | 结果 |
| --- | --- |
| `uv run --extra dev --with tqdm pytest -q` | 630 passed |
| `uv run --extra dev ruff check src tests` 与三份新脚本 | All checks passed |
| `uv run --extra dev mypy src` | 115 source files，无问题 |
| `git diff --check` | passed |
| `task.py validate 09-26-planner-router-utility-closure` | passed；两份旧的大型 spec 在上下文注入时有截断警告，已按文件原文复核 |
| `trivae eval cases validate evaluation/cases/planner-utility` | 4 条新 CaseBundle valid |
| Suite / Variant / adjudication 离线检查 | 15 条 Case 同一 Snapshot、15 条 pending/uncertain、V2 两路 forced route 有效 |

## 真实身份与调用账本

第一与第二冻结环境的 canonical Snapshot、lexical、semantic、git commit gate 各 4/4 passed。每个小批的 raw run、Evaluation run/result 与 canonical Trace 一一对齐：共 14/14/14/14，run_id 和 trace_id 均唯一。Router Utility 分析入口现已直接拒绝缺失 Evaluation result、raw/Evaluation trace_id 不一致或 canonical Trace 不存在；用两条真实样本重算成功。7 次 planned 侧均调用 Planner，Standard 侧 0 次。5 对 zero-result 与 2 对 context recovery 的顺序 manifest 首次请求前 create-only 写入；第二轮同 Case 反转 Variant 顺序。Jev 两条 observation 的 Suite/Snapshot 与 forced treatment 对齐，Router Utility 两份结果均包含 1 条 `unadjudicated` 真实 observation。

Provider 请求账本在每个小批后重新生成并保留快照；最终 `planner=7`、`runtime=38`、`existing_router_llm=0`、`jev_decisions=2`，累计 47。一次 Planner `provider_length` 也计 1 次；没有自动重试。Jev 实际返回 cost 两条均可用，DeepSeek cost unavailable。剩余 13 次小于下一对 forced run 的 17 次理论最大值，已停止计费调用。两份 Router Utility 分析结果的 human utility 标签均 pending，没有计算准确率。

旧 37×2 Planner Development、历史 repeat、16 Case Jev diagnostic 和 sealed Holdout 均未改写；本轮包含私有答案的 raw、Evaluation SQLite、Trace 与账本只在 ignored `data/evaluation/planner-router-utility/2026-09-26/`。生产 Jev 配置审计仍为 `shadow`。本地提交后检查主工作树干净，不 push。
