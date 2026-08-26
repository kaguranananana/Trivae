# Real Provider paired answer quality evaluation

## Goal

在不改变既有预算实现、prompt、case 和质量标准的前提下，完成 fixed 16k、dynamic 128k run pool 与当前默认 dynamic run pool（1M context 下 250k）的真实 Provider A/B 评测，回答“更大的 tool-result budget 是否真正改善最终用户回答”这一问题。

## Background and confirmed facts

- 归档任务 `08-26-1m-context-budget-finalization` 已覆盖预算实现、合成 benchmark、真实 Provider runner 和首轮 report。
- 首轮真实实验固定为 36 个 cell，但 `real_ab.py` 对每个 cell 只给 Provider 30 秒；32 个 cell 被 harness timeout 截断，不能作为回答质量结果。
- 现有 runtime Trace 已记录 Retriever、canonical evidence、model projection、budget、tool round、usage、citation 和 graceful finalization 所需的 bounded facts。
- 现有 Evaluation 基础设施已有 `operational_measurements`、`query_result_snapshot`、`ReviewPacket` 和 deterministic checks；本任务应复用它们，不建立第二套质量评分框架。

## Requirements

### R1. 继承实验设计

审计并在本任务文档中引用归档 benchmark、`real_ab.py`、experiment report、validation 和已有 Trace；三组实验使用相同 prompt、case 顺序、scope、provider 配置和 repetition 设计。只把 variant 的预算设置作为自变量。

### R2. 可完成的真实实验 harness

- 单 cell timeout 从 30 秒提高到足以覆盖已观察 Provider latency 的明确上限，并作为可配置常量记录。
- 增加整个实验的 wall-clock deadline；deadline 到达后剩余 cell 显式记录为 `experiment_timeout`，不伪造 QueryResult 或质量结果。
- cell timeout、总 deadline、Provider runtime failure 与正常完成必须在输出中区分；timeout/runtime failure 不进入回答质量样本分母。
- 不增加无依据的 retry、fallback、降级或静默吞错。

### R3. 三组预算对照

完整执行以下 variant：

1. `fixed-16k`：fixed tool-result budget 16k。
2. `dynamic-run-128k`：dynamic per-call 128k，显式 run-level pool 128k。
3. `dynamic-default-250k`：dynamic per-call 128k，使用 1M context 的当前默认 run-level pool 250k，不通过实验变量覆盖默认值。

### R4. 完整链路证据

对于每个 completed sample，记录并可通过 Trace ID 回查：Retriever hits/candidates/returned messages、canonical 保留量、model projection 实际可见量、omission/truncation、tool calls/rounds、latency、token usage（Provider 不提供时为 `unavailable`）、citation/finalization 状态，以及现有 AnswerArtifact/ReviewPacket 提供的人工复核材料。

### R5. 成对质量材料

为同一 case/repetition 的 completed variant 生成可人工复核的 paired material，包含 bounded answer artifact、引用绑定和选中 source snapshot。人工判断只输出 `complete`、`partial`、`observed` 或 `unknown` 及证据说明，不伪造自动 enumeration score、evidence coverage score 或 omission score。

### R6. 实现边界

- 只有真实 completed Trace 明确暴露产品 bug 时，才修改 `src/` 产品代码；预算实现、prompt、case、质量 rubric 不因预期结论而调整。
- 评测 runner 可以扩展，但必须直接复用现有 Trace/Evaluation projection 和错误语义。
- 不 merge `main`，不创建或切换分支。

## Acceptance Criteria

- [x] `prd.md`、`design.md`、`implement.md` 完成，并记录归档实验基线和本轮的 change boundary。
- [x] 真实 runner 支持单 cell timeout 和总 wall-clock deadline，能够输出 planned/completed/timeout/runtime-failed 的完整 36-cell inventory。
- [x] 三个 variant 使用同一组 4 prompts、3 repetitions 和相同 provider 条件；默认 250k variant 未通过 env 覆盖 run pool。
- [x] 至少对所有 completed samples 输出 Trace-backed operational measurements；timeout/runtime failure 明确排除在质量样本之外。
- [x] 若存在同一 case/repetition 的多个 completed variant，输出 paired review material；质量结论只基于可复核材料，样本不足时明确报告“无法证明”。
- [x] 更新 experiment report、validation 和相关 Trellis spec/journal，保留关键 Trace ID、failure case、实验上限和下一步建议。
- [x] 通过相关 Evaluation regression，以及项目验证范围内的完整 pytest、Ruff、Mypy、compileall；裸扫基线限制见 validation。
- [x] 提交当前分支上的 work commits，并按 Trellis 流程归档任务和记录 session；没有 merge 或切换到 `main`。

## Out of scope

- 不重新设计或调优 dynamic budget 算法。
- 不新增 prompt、case、数据集、Provider 或自动 judge 评分器。
- 不把 timeout、runtime failure 或未人工复核的 operational improvement 宣称为最终回答质量提升。
