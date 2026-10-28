# Trivae Agent 评测闭环与面试讲解 · 2026-10-28

## 一页评测结果

- **评测集：** `eval@v1` 固定 16 道真实用户问题和同一冻结数据快照。题面、开放式 Ground Truth、证据包、引用原文及上下文记录在 ignored 本机目录 `data/evaluation/eval-v1-20261028/`。
- **真实 Baseline：** 16 个 Case 均有 Run/Trace；14 个 Agent Run 成功，2 个是运行失败：Case 03 `AnswerDeltaParseError`（Provider 返回 HTTP 200 后答案增量解析失败）和 Case 14 `APIStatusError`（未取到 HTTP 状态码）。两题没有完整回答，不进入回答质量分母。
- **原始 Judge v2：** 14/14 成功回答有 GPT-6.1 Sol / Medium、ChatGPT OAuth 的模型辅助 Review。任务满足度分布 4/3/2 = 8/3/3；回答可信度 = 0/2/12；46 条结构化诊断（轻微 13、中等 33、严重 0）。所有 Review 都是 provisional，未人工确认。
- **Judge v2.1 校准复评：** 同一批 14 个保存回答重新评审，全部成功，单独 Store；评分分布为任务满足度 8/4/2、可信度 0/7/7；41 条诊断（轻微 13、中等 28、严重 0）。v2/v2.1 评分差异来自规则澄清，不能当 Agent 性能变化。详细逐题裁决建议见[校准审阅文件](Evaluation校准审阅-20261028.md)，全部待人工确认。
- **单轮真实 Candidate：** 六个重点 Case 都重新执行，Candidate 6/6 completed、Trace 6/6 complete；同一 Judge v2.1 评审 Baseline 与 Candidate。Case 07、12 的可信度评分提高，Case 10 的任务满足度从 4 降至 2，遗漏最贴近题意的手机远控 Codex/微信实例。综合逐题证据，拒绝将 Candidate Prompt 变更合入生产；不宣称质量提升。

## 2 分钟口述

我做的不是让一个模型给 Agent 打总分，而是把实际运行和质量判断拆开，保留出问题时能追到原始证据的链路。我们先固定了 16 道 Eval v1 用户问题、Ground Truth、证据包和同一份聊天快照，再通过现有 EvaluationRunner 为每道题生成 Run 和 Trace，保存模型、检索工具调用、引用、回答、Token、耗时和失败信息。真实 Baseline 是 14 个成功回答、2 个运行失败；失败题没有回答，所以不拿来评质量。

Judge 从保存的回答开始，读取原始问题、完整答案、Ground Truth、被引用的消息及其邻近上下文。Ground Truth 是开放参考，Judge 接受参考清单外但有原文支持的答案。Judge v2 有任务满足度和回答可信度两个独立的 0–4/unknown 维度，具体问题用结构化诊断记录类型、严重程度、原文证据和用户影响。校准时我们发现两个边界：Case 05 的原题并没有要求必须讲一个完整真实项目；Case 06 的一个中等范围误读影响局部结论，但不一定要把整份回答可信度压到 2。于是增加了 v2.1 的两段规则说明，保留 v2 原始 Prompt 和评审记录，并用 v2.1 单独重评 Baseline。所有模型判断仍待人工抽审。

最后我只试了一次四行 Prompt 约束，用同一 Case、快照、模型和预算重新跑六题，并用同一个 v2.1 Judge 评两边。它帮助 Case 07、12 更谨慎地说明证据范围，但 Case 10 因为漏掉最贴合用户问题的已有手机远控实例，任务满足度从 4 降到 2，所以我拒绝这项改动。这个六题单次对照只能说明本次结果，不代表统计显著或整体准确率提升。我的交付是可回放的 Run/Trace/Review、明确的运行失败分母、待人工确认的校准建议和一次有明确采纳/拒绝结论的真实实验。

## 从用户问题到校准与实验

```mermaid
flowchart LR
    Q[原始用户问题与范围] --> GT[开放式 Ground Truth 与证据包]
    GT --> RUN[固定 Suite / Snapshot / 模型条件]
    RUN --> TRACE[Agent Run / Trace / 完整回答]
    TRACE --> JUDGE[Judge v2 或 v2.1]
    JUDGE --> DIAG[双维评分与证据化诊断]
    DIAG --> HUMAN[人工校准建议待审]
    HUMAN --> AB[保存回答 Baseline 与实际 Agent Candidate 对照]
    AB --> DECISION[逐题核对、采纳或拒绝]
```

1. **用户问题与 Case：** Suite 锁定 Case 身份、版本、查询时间和数据范围，避免根据答案修改原问题。
2. **Ground Truth 与证据：** GT 提供核心需求、参考事实、边界和来源；不是限定消息 ID 的穷举答案。冻结证据审计重读来源 ID、会话、时间、正文、转发路径及上下文。
3. **Agent Run：** 固定 Model Variant、工具面、快照和预算。保存完整回答、每个引用、运行状态、模型使用量和异常。运行失败保留 Trace，独立于质量分数统计。
4. **Judge：** 从保存回答评审，重新读取引用原文与上下文；材料无法支持可靠判断时用 `unknown`。任务满足度衡量有没有完成用户实际需求，回答可信度衡量证据、归属、时间和适用范围。
5. **结构化诊断：** 每条问题保留一个主维度、问题类型、minor/moderate/severe、回答摘录或遗漏标记、证据/证据缺口和对用户的影响。严重程度是局部问题属性，不能直接当作整体分数映射。
6. **人工校准：** 模型 Review 只进待审队列。审阅文件逐题并列原始 v2、v2.1 Baseline 分和模型辅助建议；人工确认区为空，禁止把模型输出标成 human-confirmed。
7. **优化对照：** Baseline 使用原始保存答案；Candidate 重新运行真实 Agent。冻结 Case、Snapshot、模型及其他运行条件，单独记录 Prompt Variant 和代码身份；用现有 PairedComparison 校验 Case、快照、范围与 Variant 对应关系并保存运行指标。两边必须由同一个 Judge 版本评审，再逐题检查遗漏、引用和 Trace，不把单次打分差异当作总体收益。

## 两个可追溯 Bad Case

### Case 07：把局部例子升格为 MCP / Skills 通用选型规则

- **问题：** “MCP 和 Skills 做工具扩展，大家一般怎么选？”
- **发现：** Baseline 回答把“需要真实外部系统/账号动作就用 MCP、固定套路就用 Skills”写成实操分界。原始上下文也有 Skills 可以用脚本、大多数工具可由 CLI + Skill 实现、MCP 用于鉴权，以及两者组合的例子；这些材料不能证明通用边界。
- **根因判断：** 从少数用途示例推出普遍选型规则，并把来源的建议性质写成群体经验；不是检索中没有出现 MCP 或 Skills。
- **方案与验证：** v2/v2.1 保留为错误选型负例，可信度 2/4；Candidate Prompt 取消较确定的普遍分界，Candidate 的 v2.1 可信度为 3/4。但 Candidate 仍缺少按网络、鉴权、CLI 和上下文成本选择的具体条件，故只算局部修正，不证明选型回答已解决。
- **原始材料：** `eval-v2-baseline-20261028/cases/cap1-07-mcp-skills/attempt-01/input.json`、`review.json`；Candidate 对照在 `eval-agent-evidence-claim-20261028/candidate-reviews/cap1-07-mcp-skills/attempt-01/`。

### Case 10：错域名及不可靠产品信息

- **问题：** “想用手机远程让 AI 帮我写代码，有没有人试过？”
- **发现：** Baseline 把引用原文 `vibe42.ai` 写成 `vjbe42.ai`，又加入证据未支持的 OpenClaw iOS/Android App 信息，还把个人账号中断经历归纳成普遍封号风险。错误域名会让用户找不到工具，产品和风险表述会影响采用判断。
- **根因判断：** 长工具清单中的域名未逐字保真；来源里的个人经历、推测和产品摘要没有维持各自的证据等级。
- **方案与验证：** v2 将可信度评为 2/4；v2.1 对同一回答评为 3/4，但人工建议暂仍是 2/4，因为域名正是直接使用入口。Candidate 没有保留错误域名，却漏掉更贴近题意的手机调用 Windows Codex/微信线索，任务满足度降至 2/4、可信度 2/4。因此拒绝 Candidate Prompt，而不是以修好一个错名掩盖新遗漏。
- **原始材料：** `eval-v2-baseline-20261028/cases/cap1-10-mobile/attempt-01/input.json`、`review.json`；Candidate 对照在 `eval-agent-evidence-claim-20261028/candidate-reviews/cap1-10-mobile/attempt-01/`。

## 面试官可能追问

1. **为什么把任务满足度和可信度拆开？** 任务可能答到点但引用错，或引用都准确却漏掉用户的核心目标。分开记录可说明“答案有用到什么程度”和“用户能否相信”不是同一件事，也避免同一问题在两个维度机械重复扣分。

2. **为什么不报告 Agent 准确率？** Ground Truth 是开放式，参考消息不是穷举；语义审核和 Judge 目前是模型辅助、人工未确认，不具备可靠的人类金标准分母。可以报告 Run 完成情况和逐题分布，但不能把模型评分平均数称为准确率。

3. **引用证据怎么核验？** Judge 输入里保留完整回答和引用工件，程序在冻结 Canonical 数据库重读被引用原文、会话、时间和转发信息，并附邻近上下文。Ground Truth 外但有证据支持的回答也接受；结构化 SQL 值没有重新执行时不冒充原文支持。

4. **Judge v2.1 到底改了什么？** 只补了两个判分边界：先看原始问题，不把理想化 GT 案例变成题面硬要求；再把局部问题 severity 与整体轴分分开，结合结论中心性和用户影响。两轴、unknown、开放式 GT 和诊断语义均保留。v2 原始规则和 Review 没有覆盖。

5. **Case 06 为什么 moderate 还给可信度 3？** moderate 指一个范围误读会影响局部复杂度选择。RAG 混合检索、切分、评测闭环的主要建议仍有来源支持，且误读没有支配整份回答，因此整体分可为 3；不能让 severity 自动决定评分。

6. **怎么证明实验可比？** 两侧来自相同六个 Eval Case 和冻结 Snapshot，DeepSeek Flash、配置模型、工具面、索引、运行预算相同；Baseline 读取原始已保存回答，Candidate 使用独立数据库真实重跑。整个 checkout 的代码身份不同，但 Agent `query/runtime` 差异只有一段 Prompt；这一身份差异和其余评测代码差异均在 manifest/协议中保留。

7. **实验结果如何决定 Prompt？** Candidate 6/6 运行完成，Trace 均完整；v2.1 对两侧各评六题。Case 07/12 可信度评分上升，但 Case 10 任务满足度从 4 降到 2，Case 01 仍出现更严重的范围/因果外推。逐题核对后拒绝 Candidate，不以平均分决定。

8. **样本能说明普遍提升吗？** 不能。六题是定向小样本，每 Case 一次，有随机生成差异，也没有独立人工盲审。它支持一次有证据的工程采纳/拒绝决定，不支持统计显著性、总体准确率或提升百分比。

9. **失败 Run 怎么计？** 原始 16 Case 的 14 个成功、2 个失败分别报告。Case 03 `AnswerDeltaParseError` 和 Case 14 `APIStatusError` 没有可评分完整答案，不进入回答质量统计，也不伪造结果。

## 简历可用事实

- 基于现有 EvaluationRunner、Judge、Suite、Store 与 Trace，完成 16 题 `eval@v1` 真实 Baseline；14 个成功 Run 全部保留完整回答/Trace 并完成模型辅助 Review，另外 2 个 Provider/解析运行失败单独记录。
- 设计并落地 Judge 双维度 0–4/unknown 与结构化证据诊断；对 14 个成功回答记录 46 条 v2 诊断，并进行单独 v2.1 校准复评。该数量是诊断记录数，不是人工确认缺陷数或准确率。
- 完成六题真实 Prompt 对照：两侧各 6/6 Run 完成，用同一个 v2.1 Judge；发现 Case 10 的关键遗漏后拒绝候选变更。不得写质量提升百分比或显著性结论。
