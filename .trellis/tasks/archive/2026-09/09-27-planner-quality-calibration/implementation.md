# Implementation

## Problem / motivation

旧 Plan 的结构校验已稳定，但高层调查建议缺少区分力。历史 v3 dependent r2 的“`mattpocock 或 skills`”使泛类别词可取代实体；archify r1/r2 的“看上下文”没有指导从多个 direct hits 中选哪个；aggregation 在 SQL 后又建议 recent/context；不同 Case 还有 `find_members`、机械 lexical+semantic、模板式汇总步骤。v2 Runtime Trace 同时证明真正的候选丢失首先发生在 Runtime 后续 `skills` 查询，故本任务只校准 Plan artifact，不伪称修复 Runtime。

## Design rationale

考虑三种方案：扩充 `QueryContext`、在 Planner 复制 SDK Tool descriptions、从已注册 Capability metadata 构造 Planner projection。选择第三种：Registry 严格返回每个已注册 Tool 的 `CapabilityMetadata`，Application 只在默认 Planner 创建处注入；Planner 从 description 取 purpose，再以局部 map 拥有短的选用 guidance。这样 `available_capabilities` 仍是 allowlist，Router 输入和 Runtime Tool descriptions 不漂移成第二份长期文档。代价是每新增 Tool 必须显式补 Planner guidance；这是开发期可见的维护约束。

Prompt 增加五类通用约束：每步信息增量；高辨识度实体主锚；direct hit 与 reply/follow-up/firsthand-use 的证据关系；按用途建议 Tool；简单/确定性事实避免多余步骤。保留原先 zero-result 特殊条款、Schema、5/5 bound、解析过滤和失败分类。没有 Case 名/字面量特例，也没有参数生成、SQL 生成、自动重试或 replan。

## Files / ownership

- `src/trivae/capabilities/registry.py`：暴露 canonical metadata，缺失或名称不匹配时显式失败。
- `src/trivae/bootstrap/application.py`：默认 Planner 读取 Registry metadata；Router 与 Runtime 构造不变。
- `src/trivae/query/planner.py`：`PlannerCapabilitySummary`、精简 guidance、allowlist 过滤和 P1 prompt；Plan parser/render 与调用次数不变。
- `tests/test_capabilities.py`、`tests/test_query_execution_core.py`：provider-free 元数据和 prompt/allowlist regression；原有失败、边界、Router/zero-result tests 继续运行。
- `evaluation/planner-quality/`：固定 P0、八条 Development Case 的 Planner-only runner 和逐轴审阅说明。脚本不调用 Runtime Tool Loop。
- `.trellis/tasks/09-27-planner-quality-calibration/`：PRD、设计、旧 Trace/ChatLab 对照、48 次输出、盲审与初步评价、验证。
- Stage 1.6 ADR 与 backend Agent Runtime guideline：记录已实现的 summary 契约和未来 Tool 新增时的维护规则。

## Failure / observability

`SoftPlanner` 仍将 `finish_reason=length` 分类为 `invalid_output/provider_length`，空结果、timeout、JSON/Plan invalid 各有原有 detail code。实验每个 invocation 即时记录 run ID、Provider/model、request 参数投影、prompt、response、usage、latency、finish_reason、parse stage、完整 Plan 或 failure；没有 retry。P1 在 24 次中 5 次 provider length，是实测回退，不得由成功样本遮盖。

## Scale / performance and evolution

P1 prompt 增加每个已开放 Tool 的 compact summary；本轮 Provider 返回的 P1 输入 tokens 明显高于 P0。其 failure rate 与 prompt 长度之间的因果尚未证明，需要后续 Planner-only 校准，不应直接调 Runtime/retrieval。新增 Tool 时应先有 CapabilityMetadata，再补 Planner guidance 和 contract test。任何基于 Planner-only 结果改变 Router/Jev 或宣称最终答案收益都超出本次证据。

## Interview Defense Notes (fact index)

- **Real failure**：v3 六个旧输出与 v2 Runtime root-cause，见 `research/current-and-chatlab.md`；Plan 语义问题与 Runtime 实际查询失误分开归因。
- **Measured evidence**：8 Case × 3 repeats × 2 prompts 的原始 Plan/Provider observation、`metrics.json`、blind packet 与 `assistant-provisional-review.md`；human adjudication 未完成。
- **Regression test**：Provider-free metadata/prompt/allowlist 契约；完整 pytest/lint/type-check 见 `validation.md`。
- **Anticipated risk**：未来 Tool metadata 与 Planner guidance 维护；新 Tool 缺 guidance 显式失败。触发再考虑改变机制的是多工具长期 drift 的真实证据，不是本次的假设。
- **Currently unnecessary**：Workflow、第二 Agent、replan、retry、扩大 retrieval limit；仅在后续独立 Failure Case 和 ADR 支持时重开。
