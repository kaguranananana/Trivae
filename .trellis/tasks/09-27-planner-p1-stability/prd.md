# Planner P1 Quality Calibration / Stability Optimization

## Goal

在保留 P1 已观察到的 Plan 质量收益的同时，查明并降低 `provider_length`，完成新的 Planner-only 三路重复实验和质量门槛判断。

## Confirmed background

- 当前 HEAD 的祖先含 P1 实现 `68286d5`；旧 P0 prompt 固定于 `12f2f75`。上一轮归档任务的 8 个已暴露 Development Case 中，P0 有效 21/24、P1 有效 19/24，`provider_length` 分别为 3/24 和 5/24。
- Planner 仍通过 `planned_execution → SoftPlanner → validated Plan → soft guidance → 同一个 Agent Runtime` 工作。上一轮实验没有运行 Runtime Tool Loop。
- P1 的五次 `provider_length` 均达到 2048 output tokens；四次可见正文为空，一次只有截断的 JSON。当前 usage projection 没有保存 Provider 的 reasoning token 明细，原因尚未被唯一确认。

## Requirements

1. 先以旧实验的原始 prompt、request、usage、response 和同 Case/repeat P0 对照归因；区分事实、假设与缺失观测。
2. 仅在 Planner prompt/summary 与直接相关的完成诊断边界做通用最小修复；保留 metadata canonical purpose、allowlist、未知 Tool 过滤、Plan schema 和失败显式 skip。
3. 建立独立 P0/P1/P2 Planner-only 实验身份，至少 8 Case × 3 repeats × 3 variants，交错运行；每次保存完整 observation，失败计入分母，无自动重试。
4. 记录可靠性、token、延迟、Plan 步数、prompt 大小及 Provider 金额成本可用性；生成三路随机盲审包和单独映射，进行 assistant provisional review，并明确等待 human adjudication。
5. 对 dependent、archify、aggregation、zero-result 回归审阅，完成 provider-free 测试与全量 pytest、Ruff、mypy、diff check。
6. 在 Trellis 中沉淀研究、设计、实施、实验、验证、最终结论和精确提交身份；只在证据满足门槛时 promotion P2，且不执行三路 E2E。

## Scope boundary

- 不访问 Holdout；不改 Router/Jev、Runtime Tool Loop、Retrieval、Evidence/Citation、answer finalization 或生产路由。
- 不新增 step executor、replan、Planner retry、第二 Agent、固定 Tool 参数或新 workflow abstraction。
- 不为具体人名、项目名或 Case 字面量增加 prompt 特例。
- Development 结果只支持本套已暴露 Case 的判断，不作泛化或生产收益声明。

## Acceptance criteria

- [ ] 旧 P1 五次失败的完整 observation 和配对 P0 已可追溯，prompt 与输出行为分解可复核。
- [ ] P2 改动具有通用设计理由，保留现有软规划架构与 contract。
- [ ] 独立三路实验原始记录、指标、盲审包、映射和 provisional review 齐全。
- [ ] 明确判为 PASS / FAIL / INCONCLUSIVE；只有可靠性与质量证据都支持时才建议三路 E2E。
- [ ] 指定测试、静态检查与 diff check 通过；任务提交和仓库状态准确记录。
