# Implementation and decision record

> 历史 P2 实施记录。2026-09-28 生产 prompt 已直接恢复到 `68286d5` 的 P1；保留的只有 Planner 专属 non-thinking Provider 配置。当前工程结论见 `final-conclusion.md` 的「Minimal production closure」，本文件下述 P2 prompt 不再是生产实现。

## Problem / Motivation

旧 Planner-only 任务中 P1 valid Plan 为 19/24、P0 为 21/24，五次 P1 `provider_length` 妨碍进入 E2E。原始五次有四次可见正文为空；本任务将近端根因定位为 DeepSeek thinking 消耗 2048 completion budget，而非可见 Plan 字段普遍过长。

## Design rationale / alternatives

先冻结 P0/P1 prompt、逐条保存 raw pairing；新增 Provider 实际返回的 `reasoning_tokens` 数值投影。第一轮 interleaved 96 次中，13 次 `length` 均到 2048 output tokens，reasoning 消耗 1821–2048；仅压缩 prompt 的 P1-B 仍 5/24 截断。非思考消融消除截断但第一版质量回退；原 prompt + 非思考仍有 zero-result 与双检索回退；提高到 3072 的 24 次均成功，但最大实际输出 2020，无法证明提高上限有必要。

选择 P2-v3：对全局调查规则和 capability selection guidance 去重，Registry metadata `description` 继续作为 canonical purpose；根据多个 Case 的共同回退明确“只有用户要求的证据关系才规划后续 Tool”、实体先 lexical、无机械双检索、无假设结果分支、schema→SQL 分步与完整空窗即止。官方 `deepseek/deepseek-flash` 的 Planner completion 使用 `reasoning_effort=none`，Router 仍是 `low`；其它 Provider 保持原档位，未经验证不声称等价。`max_tokens=2048`、JSON mode、Plan schema、parser、allowlist 与 Runtime soft guidance 边界不变。

不引入 step executor、replan、retry、第二 Agent、固定 Tool 参数、Router/Runtime Tool selection 或 Retrieval 改动。关闭 thinking 只用于单次 Planner 结构化 JSON；它不是 Planner failure fallback，也不会在失败时触发第二次调用。

## Code and observable contract

- `planner.py`：压缩 summary selection guidance 与全局通用规则；保留 entity primary anchor、direct-hit→context、anti-overplanning、verified zero-result、5/5 Plan bounds。生产仍从 `CapabilityRegistry.metadata()` 注入 canonical purpose。
- `openai_adapter.py`：增加 Planner 专属 request/调用方法，当前只对已实测 DeepSeek Flash 传 `reasoning_effort=none`。通用 completion 方法与 Router 仍传 registry `low`；完成 usage 仅在 Provider 返回时附加 `reasoning_tokens`。
- `application.py`：Router 与 Planner 共用原 client，但注入不同 completion 方法；有效 Plan 仍只作为 soft guidance 传给同一 Agent Runtime，失败显式 skip。
- `run_planner_only.py` 与冻结 prompt fixture：固定 P0/P1、逐 Case/repeat 交错、每调用实时写 prompt/request/usage/finish/raw/parse/Plan/failure/cost；生成 metrics 与三路盲包。`run_p1_ablation.py` 保存独立诊断探针。
- Provider-free tests 锁定 metadata、allowlist、未知 Tool 过滤、规则存在、Router low 与 Planner none、usage 数值、失败分类。测试不声称模型必遵守提示。

## Failure Cases / observability / scale

`finish_reason=length` 在 JSON decode 前归属 `provider_response/provider_length`；空正文与非闭合 JSON均保留 raw observation，无 retry。输入增长是否使 thinking 变长仍未被证明。其它 Provider 的非思考质量未验证，故保持原模式。生产 Trace 只投影安全 request 与 usage 数值，不存 reasoning 正文；Planner prompt/response 只进入已有 debug Trace 语义。

P2 prompt 平均 5174 字符，P1 5568；正式五重复的 P2 input/output/total 为 46,330/6,504/52,834，P1 为 49,970/50,752/100,722。降低的主要来源是没有隐藏推理输出，而非把 summary 砍成不完整文档。模型与 Provider 行为变化时需重新验证；Development 结果不证明真实 Tool 效用或泛化。

## Interview Defense Notes（事实索引）

- Why：原始五组 pairing 在 `research/failure-pairs.json`，第一轮 reasoning attribution 在 `research/ablation-results.md`。
- Alternatives：prompt-only、none-only、3072 budget 与逐版质量回退均保存原始 runs；没有依据时不升高共享上限。
- Debug：`reasoning_tokens`、finish reason、parse stage 和 raw response 能区分隐藏预算耗尽与普通 JSON 错误。
- Verification：`experiment-final/` 的 120 次、40 组三路盲包、`assistant-provisional-review.md` 和 `validation.md`；human adjudication 尚未完成。
- Boundary：Plan 不执行 Tool，Router/Runtime/检索/证据不由本任务优化；Future Work 仅在真实 E2E 后再讨论。
