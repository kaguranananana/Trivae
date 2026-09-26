# Planner Retrieval Degradation Root-Cause & v3 Treatment Validation

## 目标

解释 Planned treatment 为什么未在当前 Development workload 上产生可证明的正向质量收益，以及 `pu-dependent-mattpocock` 中强一手使用证据为何比 Standard 更容易丢失。先基于真实 Trace 找到最早实质偏离，再按证据在 Planner、Runtime、Retrieval、Truncation、Evidence projection 中定位责任层；只有确认通用行为缺陷后才做最小修复，并以新的 v3 targeted paired treatment 验证。

本任务不重做 Planner / Agent 架构，不进入 Jev production rollout，不打开 Holdout，也不将复杂度当作 Planned label。

## 已冻结基线

- 当前 v2：6 道 Case、8 组 paired observations；`planned_beneficial=0`、`standard_preferable=2`、`indifferent=4`、`uncertain=0`。
- 15 道跨版本人工观察：`planned_beneficial=0`、`standard_preferable=4`、`indifferent=11`、`uncertain=0`。其中旧 Variant 观察不能冒充当前 v2 run。
- 当前累计 Provider ledger：74 次；Planner 11、Runtime 61、Existing Router LLM 0、Jev Decisions 2。ledger 按本地 Trace 起点重建并与存档事件核对。
- `pu-dependent-mattpocock` 的 GT target 未证明 corpus-exhaustive；required context 是人工检查点；已有 retrieval 为 partial/truncated。漏掉单条指定消息不能自动推出整体回答错误。
- `dev-context-archify` 的 v2 人工方向不稳定：第一组 Standard 找到关键 reply context，Planned 漏失；第二组双方均漏。
- 生产 Jev 仍为 `shadow`；没有 Holdout 实验；没有任何 `planned_beneficial`。

## 需求与约束

1. 完整重建 `pu-dependent-mattpocock` Standard 与 Planned 两条生产 Trace：User Query、route、Planner input/output、Runtime 对 guidance 的消费、tool selection/args、retrieval mode/results/limit/coverage、上下文扩展、Evidence projection 与 final answer。
2. 精确指出两条链路的 first divergence 和关键证据首次缺失的阶段，并区分 confirmed root cause、contributing factor、symptom、non-cause、unknown。
3. 对 `dev-context-archify` 分别复核 Standard r1、Planned r1、Standard r2、Planned r2，判断其与 dependent Case 是否共享同一根因；不得因表面症状类似而合并。
4. 对照 ChatLab 已有架构与 Retrieval/Runtime contract。没有明确 Failure Case 或技术冲突时，不新增 Agent、workflow、step executor、replan 或平行 Tool contract。
5. 只在 Trace 已证明具体的通用缺陷后修改责任层。禁止 Case ID/query 字面量特判、静默 fallback、无依据重试或放宽 zero-result positive-proof contract。
6. 新增 deterministic regression，覆盖 entity-rich investigation 不被无理由泛化、limit 到达时 partial/truncated 正确传播、既有 direct anchor 与 Standard 行为、以及 zero-result 正证明不退化。只有现有设计支持 refinement 时才要求 refinement 回归。
7. 形成新的 v3 Standard/Planned Variant pin 与 targeted execution identity，Standard/Planned 除 forced route 外配置一致；不改写 v2、GT、canonical 数据或 sealed Holdout。
8. v3 只跑 `pu-dependent-mattpocock`、`dev-context-archify`、一个 count/aggregation negative control、`dev-zero-empty-3`。两个重点 Case 各做 2 组 paired observations，control 与 zero 各做 1 组，顺序 counterbalanced。
9. Provider 新增调用理论上限为 102：6 组 pair ×（Standard 8 Runtime + Planned 8 Runtime + Planner 1）=102。预算不包含 Jev 路由；不自动 retry。失败请求照计。若某重点 Case 单次调用出现异常调查增长，停止该 Case 后续 repeat 并先分析。
10. 分开报告质量轴与 latency/token/provider returned cost；不能把运营成本合成质量分。运行后重建 Provider ledger，并核对 raw / Evaluation run / result / canonical Trace 与 Snapshot、Variant、forced route 身份。

## 验收标准

- [ ] 新任务报告写明 baseline、Trace first divergence、各层归因、ChatLab 对照和剩余不确定性；不把初步线索写成唯一根因。
- [ ] `dev-context-archify` 四条 v2 Trace 均有逐轮对照，且明确说明 repeat instability 与是否共享根因。
- [ ] 如有代码改动，只改证据指向的最靠近真实故障层的通用逻辑，并说明为何未改其它层；新增回归无 Case ID/query 特判。
- [ ] zero-result contract 原则保持；若改动触及该路径，运行现有 zero-result regressions。
- [ ] v3 Environment / benchmark gate / Variant diff / Snapshot identity 全部通过；执行使用 create-only 新路径，不覆盖旧 artifact。
- [ ] v3 完成 12 条 paired raw run；Evaluation run、result、canonical Trace 数与身份一一匹配，失败 run 保留。
- [ ] v3 质量结果含逐 Case Standard/Planned/repeat 的人工逐项 review 与自动指标；人工 review 明确标记审阅者来源。
- [ ] 新 v3 Provider invocation 不超过 102；按 Trace 重建账本并报告 input/output tokens、实际返回 cost 或 unavailable。
- [ ] Jev 保持 `shadow`；不执行 Holdout；不写 production rollout 或 generalization 结论。
- [ ] 相关 pytest、Ruff、mypy、diff check、Case identity/preflight 均通过；不可用命令如实记录。
- [ ] 变更形成清晰本地 commit，最终工作树只留预期状态，不 push。
