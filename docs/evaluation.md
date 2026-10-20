# Evaluation 与质量边界

Trivae 的评测用于回答两个不同的问题：系统有没有按合同完成一次查询，以及答案是否真正找到并正确使用了相关证据。前者依赖确定性检查和 Trace，后者需要面向具体问题的参考证据与质量评审。

自动化测试通过数量、Runtime 的 `completed` 状态、Token 减少或调用次数减少，都不能直接当作答案准确率。

## 复用生产查询链路

[EvaluationRunner](../src/trivae/evaluation/runner.py) 通过 `TrivaeApplication.query()` 执行 Case，读取同一条链路的答案与 Trace，再保存运行和检查结果。Runner 不持有另一套 Router、Runtime 或检索实例。

| 对象 | 固定什么 | 为什么需要 |
| --- | --- | --- |
| Dataset Snapshot | 数据与索引状态身份 | 避免数据变化被误认成实现收益 |
| Case Bundle | 问题、访问范围、参考 Finding、来源和评审策略 | 让预期结果与证据边界可以核对 |
| Controlled Variant | 模型、Prompt、工具、预算及执行覆盖条件 | 明确 Baseline 与 Candidate 的变化 |
| Versioned Suite | 指定版本的 Case 集合 | 保留回归历史，避免静默替换题目 |
| Evaluation Run / Result | 执行事实、检查与答案引用 | 保留成功和失败，而不只收集好结果 |
| Review / Paired Comparison | 质量轴、盲测分组和裁决 | 将答案质量与运行成本分开判断 |

Snapshot 不匹配时 Runner 会拒绝执行，而不会自动把旧 Case 绑定到新数据。异常运行先保存诊断，再向调用方重新暴露异常，不能被记录成成功答案。

## 先查工程合同，再评答案

确定性检查覆盖数据快照、范围、引用来源、时间边界、局限传播及结果状态等事实。Trace 则提供路由、计划、工具序列、检索覆盖、Finalizer 状态和可用的 Usage，用于定位问题发生在哪一层。

Finalizer 可能保留正文并移除局部无效引用，形成可交付的 `degraded` Artifact。Evaluation 将这种状态单独记录，不会把它标成证据全部通过。Runtime 完成后也可能因最终答案校验失败而没有正式 Query 答案；评测必须以整条生产链路的结果为准。

当前共享的质量轴见 [quality.py](../src/trivae/evaluation/quality.py)：

| 质量轴 | 关注点 |
| --- | --- |
| `retrieval_recall` | 目标消息是否被实际召回并送达模型 |
| `evidence_coverage` | 关键结论需要的证据是否覆盖 |
| `citation_validity` | 引用能否回到真实、正确的来源 |
| `claim_evidence_entailment` | 引用内容是否支持结论 |
| `enumeration_completeness` | 列表是否遗漏题目要求的项目 |
| `overclaim_unsupported_inference` | 是否把提及升级为推荐、意愿升级为实际使用等 |
| `user_facing_readability` | 最终回答是否清楚、可用 |

这些维度不会被自动压成一个“准确率”。默认尚未评审的质量轴保留 `not_reviewed`；LLM Judge 是可注入的离线辅助评审端口，不能凭空生成已验证结论。

## Reference 的完整度决定结论强度

Reference 按具体 Finding 保存证据、标注方法、Snapshot、Scope 和完整度：

- `exhaustive`：在声明的范围内完成了穷尽标注，可据此检查完整集合。
- `partial`：已知部分相关证据，可检查这些目标是否被找到，不能据此声称全库召回率。
- `unknown`：完整度未知，需要保留不确定性。

部分标注之外的检索结果不自动是假阳性，未列入 Reference 也不自动意味着不存在。机器辅助标注必须保留 provisional 身份，不能当作新增人工 Ground Truth。私有语料上的结果还受数据可获取性限制：克隆仓库不能完整复现未公开语料的质量实验。

## 对照实验与 Planner Utility

比较前先固定 Case、Snapshot、Scope 和非实验条件，声明 Candidate 相对 Baseline 的差异。Paired Comparison 验证配对条件并随机化 A/B 身份；质量评审与后续运行成本比较分开。

Planner Utility 使用 forced standard / forced planned 路径：绕过 Router 选择，两侧继续经过同一个 QueryOrchestrator 和 Runtime，只有 Planner 介入及其指导不同。它回答“这类问题是否值得规划”；随后才能评价 Router 是否正确识别这些问题。路由标签正确率本身不能证明 Planner 提高了答案质量。

工程合同有离线回归覆盖，包括两条路径共用 Runtime、Planner 调用零次或一次、快照漂移拒绝、配对身份保存、异常持久化以及降级答案不会被误判为 grounded pass。入口见 [评测测试](../tests/test_evaluation.py)、[Planner 工程收口测试](../tests/test_planner_engineering_closure.py) 和 [Router Utility 测试](../tests/test_router_utility.py)。

## 当前可以公开说明的结论

当前已实现并经过确定性测试的能力包括：版本化 Case / Suite、Snapshot 校验、Controlled Variant、生产链路 Runner、独立 Evaluation Store、工程检查、ReviewPacket、盲配对和失败归因。真实运行覆盖过索引构建、检索对照、Planner 调查和 Prompt 候选验证，但不同实验的样本、模型与标注强度并不相同。

截至 2026-10-19，最近一次 GPT High Prompt 精简实验的最终决定是**拒绝发布精简候选，保留生产 Prompt**。候选出现关键目标召回与引用退化；其他候选也存在端到端门禁失败。局部样本改善、Token 或耗时变化不能抵销质量退化，不能作为已经落地的性能收益。该实验的 Agent 证据复核也不能替代尚未完成的人工盲审。

此前词法与语义检索对照中的机器辅助 provisional 标注，同样只能支持相应样本的诊断，不能作为人工验证的全库准确率。本文不发布跨模型排名、总体回答准确率或稳定提速数字。

已知待验证或待改进事项包括：广泛人工校准、穷尽 Reference、长期回归阈值、模型检索与参数选择波动，以及共享证据预算接近耗尽时的工具投影失败与错误分类。网络、协议、额度错误与答案质量失败应分别归因，不能混入同一个“准确率”分母。

## 本地验证入口

安装开发依赖后，可先运行不需要真实模型请求的检查：

```bash
# 检查仓库自带的版本化 Case 合同。
uv run trivae eval cases validate evaluation/cases

# 查看失败回归映射；该命令不等于重新执行真实模型评测。
uv run trivae eval regression

# 验证评测、共享执行链路和证据合同。
uv run pytest tests/test_evaluation.py tests/test_query_execution_core.py tests/test_evidence.py

# 查看生产链路评测命令参数。
uv run trivae eval run --help
uv run trivae eval compare --help
```

真实模型评测需要准备自己的合法数据、匹配该数据的 Snapshot / Case / Suite，以及与当前运行配置一致的 Variant。仓库中的设计 Seed 或历史 Variant 不能直接作为任意新数据的质量基准。`eval run` 会调用所配置的 Provider，模型请求的额度和费用按实际 Provider 处理。

Case 格式与历史评测工具入口见 [evaluation/README.md](../evaluation/README.md)；应用边界、来源检查和预算机制见 [系统架构](architecture.md)。公开实验材料前，还应检查其中的问题、Reference、ReviewPacket、Trace 和来源摘录是否包含私人数据。

## CJK 字面检索对照的解释边界

2026-10-20的[独立CJK实验](../evaluation/experiments/cjk-bigram-v1/report.md)将字面完整性、top10排序和真实Agent分开。LIKE会在原文NUL处截断，完整正文Oracle改用`instr(lower(text), lower(term))`；首版证据保留，修正版Reference先冻结再复测。mixed-script分隔符等价、ASCII exact token和单字限制都必须独立说明。实验中的99.993%是44个固定中文/混排Query的全深度字面micro覆盖，不能称为Agent准确率。面试材料见[CJK检索实验-简历与面试.md](../interview-docs/CJK检索实验-简历与面试.md)。
