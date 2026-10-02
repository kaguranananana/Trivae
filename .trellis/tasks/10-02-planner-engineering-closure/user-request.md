请基于当前 Trivae 仓库状态继续完成 Planner Evaluation 的最终工程收口。

仓库：
https://github.com/kaguranananana/Trivae

当前相关提交链已经包含：

- `2da57b9`：恢复 P1 canonical prompt，并保留 DeepSeek Flash Planner 专用 `reasoning_effort=none`
- `23a3e9b`：Planner P1 low vs none 单变量实验
- `361a38e`：targeted low vs none production E2E
- `221f57a`：Archify Frozen Plan Runtime replay

请先完整阅读这些提交及对应 Trellis task、report、design、validation、相关源码和测试，再开始修改。

这次任务的目标是：

1. 停止继续扩大 `Planner low vs none` 实验。
2. 修复 Frozen Plan replay 已明确暴露的两个生产 Failure Case。
3. 用当前生产版本做一次小规模 `Standard vs Planned` E2E 收口实验。
4. 如果没有新的明确严重回退，就正式结束 Planner Evaluation，不再继续扩大付费实验。

不要把任务扩展成论文式统计研究，不要重新跑 37×2 全量 Development，也不要擅自设计新的 Planner 架构。

---

## 一、先确认当前生产身份

开始前必须审计并记录当前实际生产配置。

预期应为：

```text
Planner:
P1 canonical prompt
DeepSeek official deepseek-flash
reasoning_effort=none

Runtime:
DeepSeek official deepseek-flash
reasoning_effort=low
```

确认 Router、Planner、Runtime 三者的 ModelSettings 分离，没有因为历史实验代码产生配置漂移。

同时确认：

- Thin Planner 仍然只产生 soft guidance。
- Planner 不拥有 Tool execution。
- Planner 不拥有 Step Executor / Workflow / Replanning Loop。
- Standard 与 Planned 最终进入同一个生产 Agent Runtime。
- Retrieval / Tool selection / Tool arguments / Evidence selection 仍归 Runtime。
- 不改变 ChatLab-style Thin Planner 的既有架构边界。

如果当前代码与上述身份不符，先查明原因，不要直接按假设修改。

---

# 二、结束 low vs none 研究线

不要继续追加：

- low vs none 重复实验
- Frozen Plan 大规模 replay
- 固定 ToolResult 的 Answerer 方差研究
- 统计显著性分析
- 新 reasoning effort treatment
- 新 Planner prompt treatment

已有证据足够支持工程决策：

- `none` 解决过 `low` reasoning 消耗 2048 completion budget 导致的 `provider_length` / Plan 截断问题。
- 已有 P1 + none 消融出现过 24/24 valid Plan、0 provider_length。
- targeted production E2E 中 none Planner validity 高于 low。
- Frozen Plan replay 已证明固定 Plan 后，下游 Runtime 仍然存在 Tool arguments、context expansion、Evidence selection、Answer synthesis 方差。
- 当前证据不能证明 none 的最终答案质量稳定优于 low。

最终文档应把这项决策描述为：

> Planner `reasoning_effort=none` 是 completion reliability / latency 的工程选择，不宣称其答案质量稳定优于 `low`。

---

# 三、Failure Case 1：修复 source_id / message_id 参数契约

Frozen Plan replay 已经得到一个重复性很强的真实 Failure Case：

4/4 runs 都出现模型先调用：

```text
get_message_context(
    message_id="m1-1"
)
```

导致：

```text
MESSAGE_NOT_FOUND
```

随后改成：

```text
get_message_context(
    source_id="m1-1"
)
```

才成功。

这里的语义必须明确：

```text
source_id
```

用于当前 ToolResult 暴露给模型的 run-local source handle，例如：

```text
m1-1
m1-2
m2-3
```

而：

```text
message_id
```

用于 canonical internal message ID。

请检查：

- `src/trivae/query/runtime/openai_tools.py`
- `get_message_context` Tool schema
- Tool description
- Pydantic / SDK generated schema
- Runtime prompt 中对这个 Tool 的说明
- source handle resolver
- Trace normalization

不要通过：

```text
如果 message_id 长得像 m1-1，就偷偷按 source_id 解析
```

这种 silent compatibility 来掩盖错误。

优先修复模型可见的参数契约，让模型在 schema / description 层就能理解：

```text
mN-K handle → source_id
canonical ID → message_id
```

如果技术上合理，可以进一步考虑是否应该：

- 将 `source_id` 放在参数说明中的主要位置；
- 将 legacy `message_id` 明确标记为 canonical / legacy；
- 避免两个参数的 description 使用模糊的 “message_id or source_id” 合并描述。

但不要破坏已有 canonical ID 调用能力。

### 必须增加 provider-free regression

至少覆盖：

1. Tool schema 中 `source_id` 的说明明确包含 run-local handle / `mN-K` 语义。
2. `message_id` 的说明明确表示 canonical internal message id。
3. ToolResult 暴露 `source_id="m1-1"` 后，模型可见 schema 与 projection 的身份语义一致。
4. `source_id="m1-1"` 能解析到 canonical message。
5. canonical `message_id` 仍正常工作。
6. 不增加 silent `message_id → source_id` fallback。
7. Trace 继续区分：
   - Provider 原始 arguments
   - SDK / adapter normalized canonical arguments

这部分完成以后，不需要为了它做大规模 Provider 实验。

---

# 四、Failure Case 2：保存并覆盖真实日期关系错误

Frozen Plan replay 中 `low-r2` 已经得到一个非常适合作为 regression 的真实案例。

ToolResult 已正确取得：

```text
7k:
2026-07-23T09:25:23Z

9.5k:
2026-08-06T02:40:20Z
```

实际相隔约 13 天 17 小时。

但最终 Evidence / Answer 把它们写成：

```text
同一天
```

这说明：

```text
retrieval facts 正确
→ Evidence relation / Answer synthesis 写错
```

请把这个真实案例保存为事实关系回归测试。

重点防止以下类型：

- 两个时间戳相隔多天，却生成 “same day / 同一天”。
- 较早 / 较晚关系颠倒。
- Evidence finding 本身引入错误时间关系。
- Citation 指向正确消息，但 Claim 增加来源中不存在的时间关系。

优先复用现有 Evaluation / Evidence / citation contract，不要新建第二套评测系统。

如果现有 deterministic checker 无法直接判断这类 semantic relation，可以采用最小方案：

- 建立专门 regression fixture / evaluation case；
- 明确保存两个 canonical timestamps；
- 在最终人工 / Judge 检查包中突出 temporal relation；
- 如果已有 Judge 可以判断 grounded claim，则复用它。

不要为了一个 failure case 引入复杂 NLI 系统或通用 temporal reasoning engine。

---

# 五、完成修改后的 provider-free 验证

生产代码修改后，先完整执行：

```text
pytest
ruff
mypy
git diff --check
```

以及相关 targeted regression。

要求：

- 全部已有测试继续通过。
- source_id/message_id regression 通过。
- temporal relation regression 能稳定捕获旧错误。
- 不修改原实验 artifact。
- 不删除历史失败记录。
- 不通过修改 GT 来让结果变好。

只有 provider-free 验证通过后，才允许进行下面的小规模真实 Provider E2E。

---

# 六、最后一次实验：Current Standard vs Planned

这次实验回答的唯一业务问题是：

> 在当前已经修复过的生产版本中，多一次 Thin Planner 调用，是否仍能给复杂调查类 Query 带来值得保留的收益？

不要再次比较 low vs none。

Treatment：

## Standard

```text
Query
→ production Agent Runtime(low)
→ Tools
→ Evidence
→ Answer
```

## Planned

```text
Query
→ production Thin Planner(none)
→ soft guidance
→ 同一个 production Agent Runtime(low)
→ Tools
→ Evidence
→ Answer
```

唯一 treatment 差异应为：

```text
是否经过当前生产 Planner
```

其余必须一致：

- Dataset Snapshot
- Query / Case
- Runtime model
- Runtime reasoning
- Tool schemas
- Retrieval
- max turns
- max tool rounds
- output budget
- Evidence / Citation contract
- Finalizer
- Evaluation
- conversation isolation

---

# 七、Case 数量严格限制

不要跑旧的 37×2。

优先复用当前已经反复研究、GT 较明确的 8 个 exposed Development Case。

建议覆盖：

1. dependent multi-stage
2. context recovery
3. citation / Archify
4. temporal overview
5. verified zero-result
6. exact lexical
7. ranking
8. aggregation

应优先直接复用当前仓库已有 Case，例如已有的：

```text
pu-dependent-mattpocock
dev-context-archify
dev-cite-archify
dev-temporal-30d
dev-zero-empty-3
dev-lexical-forge
pu-rank-utc-session
pu-aggregate-utc-types
```

但必须先核对它们当前 GT / Snapshot / contract 是否仍然有效。

不要为了凑 8 条而重新生成没有人工 GT 的新题。

正式运行规模默认：

```text
8 Case × 2 treatments × 1 repetition
= 16 logical E2E runs
```

采用 AB / BA counterbalance。

不要默认重复。

---

# 八、真实实验前必须做 preflight

在任何付费请求前检查并落盘：

- 当前 execution commit
- git status
- Snapshot identity
- Case identity
- GT identity
- Provider / model identity
- Planner `reasoning_effort=none`
- Runtime `reasoning_effort=low`
- Standard Planner call = 0
- Planned Planner call = 1
- Tool schema hash / identity
- Runtime settings
- Evaluation settings
- run order
- output directory create-only
- credential configured，但不能写入 artifact

如果 preflight 失败：

```text
0 formal attempts
0 Provider calls
```

修好以后重新 preflight。

---

# 九、每次运行必须保存完整链路证据

至少保存：

```text
Query
→ Route override
→ Planner（仅 Planned）
→ rendered guidance
→ Runtime model turns
→ Provider raw function arguments
→ normalized Tool arguments
→ ToolResult
→ Evidence
→ Citation binding
→ AnswerArtifact
→ Evaluation
→ Trace
```

尤其要保留：

```text
Provider 原始 Tool arguments
```

不能只看 normalized Trace。

因为 Frozen Plan replay 已经证明：

```text
Provider:
source_id="m1-1"

SDK normalized:
message_id=<canonical-id>
```

两者 ownership 不同。

---

# 十、本轮重点评价什么

不要再造一个复杂综合分数。

每个 paired Case 重点看：

### 1. Final Answer correctness

人工检查是否存在明确事实错误、内部矛盾、错误关系。

### 2. Evidence / Citation semantic support

Citation 能解析只是必要条件。

必须检查：

```text
来源真实
+
引用真的支持 Claim
```

特别关注：

- 时间关系
- 回复关系
- 人名 / sender_name 与 message content 混淆
- “唯一 / 没有 / 全部”这类 broad claim
- 相邻消息是否真的构成 reaction

### 3. Retrieval / Context

观察：

- 是否找到 required evidence
- context anchor 是否正确
- 是否出现明显漏取
- 是否出现明显无意义扩大检索

### 4. Efficiency

记录：

- E2E latency
- Planner latency
- Provider request count
- Runtime request count
- Tool call count
- input tokens
- output tokens
- reasoning tokens（Provider 有返回才记录）
- cached tokens

如果 monetary cost unavailable，就保持 unavailable，不自行估算价格。

---

# 十一、停止条件

这次任务必须有明确停止规则。

### 默认：

16 次正式 E2E 完成后停止。

### 只有以下情况允许追加 targeted repeat：

发现一个新的、明确的、可能影响生产决策的严重 regression，例如：

- factual contradiction
- wrong temporal relation
- wrong citation entailment
- verified zero 被破坏
- required evidence 稳定漏失
- Finalizer / Tool contract 真实异常

对该单一 Case：

```text
Standard 再 2 次
Planned 再 2 次
```

用于判断是否稳定复现。

不要因为：

- 答案措辞不同
- Tool sequence 不一样
- latency 波动
- 少量 token 波动
- 一次 harmless retrieval 差异

就追加实验。

禁止：

```text
37×2
全量 Development rerun
Holdout
自动无限补跑
为了刷成功率重复失败 Case
```

---

# 十二、最终工程判断规则

实验完成以后，不要求证明 Planner “统计显著优于” Standard。

请按工程使用价值做判断。

如果：

- Planned 没有新的稳定严重质量回退；
- 在 dependent / context recovery / complex investigation Case 中至少存在明确实际收益；
- 额外 latency / token 在可接受范围；

则可以保留：

```text
Rule / Jev Router
→ 对复杂 Query 进入 Planned
→ Planner(none)
→ Runtime(low)
```

如果 Planned 仍然几乎没有实际收益，或者稳定产生明显质量回退，则如实记录：

```text
Planner architecture 保留
production routing 继续保守
```

不要为了让项目看起来完整而强行宣布 Planner 有收益。

---

# 十三、最终文档必须回答这些问题

最终 report 用工程语言回答：

1. 为什么 Planner 从 low 改成 none？
2. none 解决了什么已确认问题？
3. 为什么不能声称 none 答案质量优于 low？
4. Frozen Plan replay 证明了什么？
5. source_id/message_id Failure Case 根因是什么？
6. 修复采用什么 contract，为什么不做 silent alias fallback？
7. 日期关系 regression 如何建立？
8. 当前 Standard vs Planned 的最终结果是什么？
9. Planned 的收益具体出现在哪些 Case？
10. Planned 的风险 / overhead 是什么？
11. 当前生产最终选择是什么？
12. 哪些结论仍然不能声称？

明确区分：

```text
confirmed facts
observed Development evidence
reasonable interpretation
not proven
```

---

# 十四、任务完成后的收口

如果本轮没有新的阻断性问题：

1. 将 Planner low vs none 研究线标记为 closed。
2. 将当前 Standard vs Planned validation 标记为 final engineering closure。
3. 不再自动创建新的 Planner Evaluation task。
4. 更新相关：
   - PRD
   - design
   - validation
   - report
   - technical decision / runtime guideline
   - interview-defense / project evidence（如果仓库已有）
5. 保留所有历史实验 artifact 和 Failure Case。
6. 确认 README / 架构文档描述与当前生产身份一致。

最后检查 Git ancestry。

目前 `221f57a` 相对远端默认 `main` 存在一条领先提交链。请确认本任务是在正确分支上继续执行。

不要擅自 force push。

如果当前任务分支已经包含完整且应保留的 14 个后续提交，则在最终报告中明确说明：

```text
current HEAD
origin/main
ahead / behind
recommended integration action
```

如果仓库工作流允许且没有冲突，完成正常 commit / push；不要通过重写历史解决分支关系。

---

## 最终汇报格式

任务全部完成后一次性汇报，不要中途停下来询问。

按以下结构：

### 1. 最终生产配置

```text
Router:
Planner:
Runtime:
```

### 2. 修复的两个 Failure Case

- source_id/message_id
- temporal relation

分别写：

```text
现象
根因
修改
Regression
```

### 3. Standard vs Planned 实验身份

```text
commit
snapshot
cases
provider
run count
treatments
```

### 4. 逐 Case 结果表

至少：

```text
Case
Standard
Planned
quality judgment
Evidence / Citation
Tool behavior
latency
```

### 5. 聚合结果

只报告可支持的事实，不造综合评分。

### 6. 最终 Planner 决策

明确写：

```text
保留 / 限制使用 / 暂不依赖
```

以及依据。

### 7. 停止说明

明确说明：

```text
Planner low vs none evaluation closed
Standard vs Planned engineering validation closed
No further paid Planner experiment scheduled
```

除非发现新的真实生产 Failure Case。

### 8. 工程验证

```text
pytest
Ruff
mypy
diff check
```

### 9. Git 状态

```text
HEAD
origin/main
ahead/behind
commit
push status
working tree
```

---

最重要的执行约束：

**这次任务的目标是工程收口，不是继续扩大研究。**

不要因为实验结果存在随机性就无限追加样本。

已有证据足够停止 `low vs none`；新的付费实验只用于回答当前版本的 `Standard vs Planned` 是否值得保留这一项工程问题。

完成这次以后，如果没有新的明确 Failure Case，就结束 Planner Evaluation。