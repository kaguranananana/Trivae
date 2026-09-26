# 技术设计：Planner Retrieval Degradation Root-Cause & v3

## 边界

沿用 Trivae 当前主链路：Rule/forced route → 可选 SoftPlanner → 共享 Agent Runtime → 现有 capabilities/retrieval → Evidence/Citation finalization。Planner 仍只是软指导；不增加第二 Agent、固定 workflow、step executor、replan、生产路由或独立检索协议。先审 Trace，根因确认前不改 Prompt 或代码。

Trace 已确认主 Failure 的最早实质偏离发生在共享 Runtime 的 follow-up 查询选择：两个 run 首轮都用 `mattpocock` 完整返回 8 条命中，Standard 第二轮仍以 `matt` 为 anchor 并完整返回 23 条，Planned 则改用泛类别词 `skills`，返回 100/244 并明确标记 partial/truncated。Evidence 没有丢弃已返回的 firsthand source；强证据在 Planned 的宽搜候选集里首次缺失。

`dev-context-archify` 的机制与之不同：四条 Trace 的 `archify` 直接检索都完整返回 5 条命中；r1 Standard 扩展了最初分享邀请对应的上下文并找回回复，Planned 选了其它命中；r2 两路都没有选中该上下文，且双方 semantic retrieval 都失败。它说明 context-anchor 选择不稳定，但不是 dependent Case 的宽泛 query + top-100 截断机制。

本任务的具体边界由已观察到的 Trace 归因决定：

1. 本轮最小修复落在共享 Runtime instructions：保持具体实体作为 follow-up lexical 搜索 anchor，并在查回复/后续反馈时优先扩展与该关系对应的直接命中上下文。
2. 不改 Planner contract：本次 plan 保留实体与 firsthand-use 成功标准，已捕获的计划没有把 entity 泛化成类别词。
3. 不改 Retrieval：100-hit cap 正确返回 partial/truncated；工具投影未丢弃已返回消息。Trivae 已有 bounded automatic context expansion，ChatLab 对照也未显示需要增加 continuation/refinement Tool。
4. 不改 Evidence / Citation / zero-result proof：关键 firsthand source 在 Planned retrieval candidate set 中已经缺失，且已有 partial limitation 被正确保留。
5. Runtime instructions 是软指导，Trace 不能单独证明 provider 收到的完整 prompt bytes或证明单次 prompt 改动必然改善结果；v3 paired repeats 负责评估实际效果，不把 prompt 文字测试误写成模型行为保证。

所有分支都保持 `get_recent_messages` 完整空窗正证明 contract：SQL-only、partial、error 不能推导空；实际消息存在时不能输出 verified zero。

## Trace 证据模型

主问题用同 Snapshot、同 v2 Variant pair、同 Case 的真实 run/trace IDs 配对。按 sequence 重建：

`request → route/planner lifecycle → model-visible Runtime input → tool call/arguments → capability/retrieval result metadata and projection → next Runtime input → evidence/citation/finalization → answer`

记录每一条 retrieval 的 tool 名、lexical/semantic/search mode、原始 query、result count、candidate/result/tool limits、partial/truncated/error metadata、continuation/refinement/context expansion 是否存在，以及目标 message 是否进入 Tool output、后续 model context、Evidence sources、citations 和 final answer。若 Trace capture boundary 不保留某层原文，标为 unknown，并从现有 canonical Trace/本地 run artifact 交叉查证；禁止推测 Provider 未看到的内容。

对 `dev-context-archify` 使用 r1/r2 四条 Trace 独立记录，不以整体 summary 抹平方向冲突。相同根因必须由双方 first divergence 和相同责任机制支持。

## 实现与测试决策

完整 Trace 归因已写入 `research/trace-root-cause.md`。实际改动边界见本任务 `implementation.md`：只修改共享 Runtime prompt 与 deterministic prompt-contract regression；Provider 实验不用于反向调节答案。

回归测试是 deterministic 且 provider-free：锁通用输入/输出 contract，而不是特定 Case 或 Query。只要求当前产品 contract 支持的行为；若 continuation/refinement 并非现有架构能力，不为本次测试单独创造该能力。先复用已有 Test fixtures 与 benchmark/evaluation helpers。

## v3 执行身份与隔离

- 实现先形成代码 commit；其后单独提交 v3 Suite / 两个 Variant pins，确保 Variant 指向已提交代码版本且 execution tree clean。
- 两个 focus Case 组成 2-repeat paired suite；negative control 与 zero-result 组成单-repeat paired suite。两个 suite 都使用 deterministic counterbalanced 顺序。
- 先 capture 新 Environment，再 gate，检查 Provider、Canonical Snapshot / lexical / semantic identity、git commit 与 Case/Variant identity。此后不改代码。
- 使用全新 create-only raw output、Evaluation DB、execution-order 和 ledger 路径；不覆盖 v2，也不连接 Holdout。
- Provider invocation 上限 102；按 batch 记账，计数开始事件，失败照计，不自动 retry；无 Jev request。

## 结果解释

逐 Case 比较 answer correctness、evidence completeness、context recovery、groundedness/citation、zero-result correctness、reliability。Latency、tool calls/rounds、input/output/total tokens、Provider returned cost 另列。人工 review 记录审阅者来源与依据；不将 assistant review 伪装成用户 review。小 Development 样本、Repeat instability 与无 Holdout 必须作为限制。
