# Planner-only quality calibration

> 历史实验记录。2026-10-03 Planner Evaluation已工程收口，当前生产为P1 canonical /官方DeepSeek Flash /none，Router与共享Runtime low；none只证明已观察的completion可靠性/延迟优势，不证明最终答案更好。下方“当前”、treatment与运行命令指原实验时点，不再安排付费扩样。见[最终report](../../.trellis/tasks/10-02-planner-engineering-closure/report.md)。

本实验只调用单次 `SoftPlanner.plan`，不运行 Router、Agent Runtime、Tool Loop、Retrieval、Evidence 或最终答案评测。P0 是任务起点提交 `12f2f75` 的原始 prompt；P1 是当前 Planner prompt 与从 Capability metadata 派生的摘要。两路使用同一 Provider completion boundary、JSON parser、allowlist、2048 completion token 配置和 Case 输入。P0 模板已与起点源码在八条 Case 上逐字比对。

`run_planner_only.py` 从既有 `evaluation/planner-utility/manifest-v1.json` 中取 8 条已暴露 Development Case：dependent、archify、aggregation、verified-zero、30 天话题、forge 精确检索、archify 简单 lookup、会话排名。来源和版本写入每条运行记录；不会读取 Holdout 或 sealed Case。Snapshot 只投影 message count、首末时间与 lexical index 存在性，两路一致。没有聊天 corpus、Tool Result 或真实 direct hit 进入 Planner。

运行：

```bash
.venv/bin/python evaluation/planner-quality/run_planner_only.py \
  --output-dir data/evaluation/planner-quality/next-run \
  --repeats 3
```

输出 `runs.jsonl` 每次完成后立即写入，包括失败；`run-config.json` 记录实验身份；`blind-review-packet.md` 每个 Case/repeat 随机匿名 A/B；`blind-key.json` 单独保存揭盲映射。Reviewer 应先看 packet，填写 A better/B better/indifferent/uncertain 与理由，再读取 key。assistant 的初步审阅另存，不可覆盖正式 human adjudication。

## 逐轴审阅指引

- **Entity preservation**：特定人、仓库、产品或 URL 是否维持为 primary anchor；泛类别词是否仅补充。
- **Scope discipline**：是否无依据扩大为全局类别或最近消息浏览。
- **Tool relevance**：每个建议 Tool 是否服务必要目标；lexical/semantic 是否机械成对，`find_members` 是否误用于内容问题。
- **Incremental value**：每一步是否提供用户 Query 本身没有的调查方向、依赖、证据关系、边界或完成条件。
- **Evidence alignment**：所需证据是否匹配推荐/用法、后续反馈、亲自使用或确定性数值等实际需求。
- **Context/relation quality**：需要 reply/follow-up 时是否先找与关系目标最相关的 direct share/usage discussion，再围绕它取 context；是否区分热度更新与实际使用。
- **Redundancy**：是否有重复 context、空泛归纳或无信息增量的“搜索→分析→总结”。
- **Overplanning**：简单 lookup、完整空窗或 schema+SQL 已充分回答的聚合是否又加额外检索/验证。
- **Failure rate**：invalid JSON、provider length、timeout、empty response 独立计数，不把成功 Plan 的质量与失败率合成单分。

Rubric 是审阅维度，不是自动加权分数；不因步骤少就扣分。Planner-only 结果即使改善，也只决定能否进入下一阶段 Standard vs Planned-P0 vs Planned-P1 E2E 研究，不证明最终答案质量或生产收益。
