# Interview Defense Evidence

> 这是 Trivae 所有实现任务的长期质量门槛。目标是形成事实索引，不是编写背诵式面试答案。

## 适用范围

每个实现任务完成时适用，尤其适用于 Retrieval、Tool、Agent Runtime、Context、Evidence、Evaluation、Storage、Application Boundary 等关键模块。纯问答、纯状态查询或不产生实现结果的工作不需要强行创建本记录。

## 记录原则

只记录能够由以下来源证明的内容：

- architecture decision；
- implementation；
- test / regression test；
- 真实数据运行；
- benchmark / evaluation；
- 真实 Failure Case 的复现与定位。

禁止为了面试制造不存在的复杂度、虚构 Failure Case、虚构性能数字或包装不存在的设计过程。没有证据的内容必须明确标为未知、`anticipated risk`、`engineering expectation` 或 `waiting for evaluation evidence`。

## 面试回答的来源边界

Interview Defense Notes 的默认回答应从 Trivae 自己的 Problem、Constraint、Design Decision、Implementation、Test、真实数据运行和 Failure Case 出发：

- 不把 ChatLab、参考实现或“参考某个成熟开源项目”作为设计理由、技术结论或答案主线；
- 不在没有必要时主动引出 ChatLab 或外部参考来源；
- 不把外部项目的存在当作“为什么当前实现正确”的证据，当前项目的测试、测量和真实 Failure Case 才是证据；
- 内部架构文档可以保留真实的参考来源，不为了面试表达而篡改项目历史；
- 如果面试官直接询问参考来源，必须如实说明，再把重点转回 Trivae 的边界适配、取舍、实现和验证，不能声称不存在外部参考。

因此，回答“为什么这样设计”时优先使用：

```text
Trivae 的具体问题 / 约束
→ 考虑过的方案
→ 当前选择与 trade-off
→ 代码 / 测试 / benchmark / Failure Case 证据
```

## 必须覆盖的内容

实现/验证/评审记录至少包含以下章节。可以放在任务目录的 `validation.md`，也可以放在项目已有的 implementation / review 文档中，但必须能回指具体证据位置。

### 1. Problem / Motivation

- 解决的具体问题是什么；
- 没有该模块时会出现什么 Failure Case；
- 为什么问题归属当前层，而不是其他层。

### 2. Design Rationale

对重要设计记录：

```text
problem
→ considered options
→ selected option
→ reason
→ trade-off
```

只写真实存在或被正式架构 / 实现证据支持的 alternatives。

### 3. Why not

对容易被追问的未采用方案，明确标记：

- `permanently rejected`；或
- `currently unnecessary / waiting for evaluation evidence`。

第二类必须记录未来的 reconsideration trigger。等待证据不等于永久否定。

### 4. Failure Cases

每条记录明确分类：

- `real failure`：真实运行中发生并被复现的问题；
- `regression test case`：为契约或已知边界建立的回归保护；
- `anticipated risk`：尚未发生、但基于设计可解释的风险。

推荐字段：

```text
input / scenario
observed failure
root cause
how it was located
fix / current handling
validation
regression protection
```

### 5. Evaluation / Evidence

记录能支撑技术判断的真实证据，包括适用时的 dataset size、canonical count、query type、hit / returned count、latency、truncation、correctness observation 和对比结果。

必须区分：

- `measured fact`：实际运行测得或测试直接断言的结果；
- `engineering expectation`：尚未由当前项目运行证明的推测或扩展判断。

### 6. Observability / Debugging

至少说明：能看到什么信号、错误在哪一层分类、如何定位到具体输入 / batch / query / entity、如何区分 retrieval miss、filter error、truncation、data problem 或其他层错误。不要把尚未实现的 Trace / logging 写成现有能力。

### 7. Scale / Performance

记录当前真实规模、查询量级、实测瓶颈、代表性耗时，以及数据扩大后的工程预期。没有 benchmark 或真实数据证据时，不写成性能事实；没有真实 Failure Case 时，不以“可能慢”为理由擅自增加复杂索引或基础设施。

### 8. Boundary / Ownership

明确写出：

```text
what it owns
what it explicitly does not own
upstream
downstream
dependency direction
```

重点区分 Application、Interface Adapter、Storage、Derived Data、Retrieval、Tool、Agent Runtime、Router、Planner 等边界。

### 9. Evolution

对暂缓能力写出证据化演进路径：当前 baseline、触发 Failure Case 或 Evaluation、需要的 regression / paired evaluation、再决定是否引入新能力。没有触发证据时保持当前最小实现。

### 10. Interview Defense Notes

只建立问题到事实来源的映射，不生成标准答案：

```text
Q: 为什么这么设计？
Evidence: architecture / decision / code / test / benchmark / failure case
```

## 完成质量门禁

任务完成 review 时，连续追问以下问题必须能从仓库找到证据：

```text
为什么这么设计？
有哪些真实替代方案？
失败过吗，如何定位？
怎么证明改动有效？
规模上去后最先担心什么？
这个模块拥有和不拥有什么？
未来什么证据会让你重新评估？
```

如果答案只能是“代码就是这么写的”，记录不合格；如果必须虚构项目经历才能补齐，记录方式不合格。

## M5a Evidence / Citation 事实索引

M5a 的事实来源集中在归档的 [task PRD](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/prd.md)、[design](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/design.md)、[implementation](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/implement.md) 与 [validation](../../tasks/archive/2026-08/08-23-m5-evidence-citation-finalization/validation.md)：

- 为什么不能只返回 `[1]`：`QueryResult.answer_artifact` 保存 claim-level binding，`query/evidence.py` 再确定性解析 source identity；显示编号不承担 provenance。
- 为什么需要 current-run provenance：测试覆盖 fabricated run/tool/result/item ID、old run 和 scope violation；source 必须命中本轮 Tool Result，不能从 prior assistant context 借用。
- 为什么 Retrieval Candidate 不等于 Final Evidence：Retrieval 只提供 bounded candidate / structured result，Agent final synthesis 组织 question-specific finding，validator 只验证结构、locator、scope 和可信 hydration。
- 为什么不引入 Evidence Agent / Judge：Stage 1.8 ownership 与当前实现都把 semantic entailment 留给 M7 Evaluation；M5 没有第二套 Agent Loop。
- 为什么 invalid citation 不 silent fallback：finalizer 通过 `finalization_error` 阻止正式 `final_answer`，不会删 binding、换来源或 retry；对应 bad cases 在 `tests/test_evidence.py`。
- 当前限制：Conversation / Assistant Message durable persistence 仍是 M5b；Trace backend、semantic quality 和 bounds calibration 仍待 M6/M7 或 real-run evidence。
