# Research: Current State

## 审计结论

- 本任务从当前 `main` tip 创建；上一轮 retrieval-budget 任务的分支 tip 与当前基线一致，worktree 在开始时 clean。
- 上一轮已落地的 retrieval contract 保持不变：lexical 默认 1000、hard cap 5000；semantic 默认 10、hard cap 20；dense top-k 40；trusted scope 5000；structured/member/value 100；automatic context source cap 20；expanded final cap 100。
- 既有 `project_tool_result_for_model()` 已经拥有固定 16000 token budget、canonical record 和 model projection 两条数据形态；缺口是 Runtime 没有把每次 run 的显式预算传到 projection，也没有共享累计账本。
- 当前 settings 没有可靠的 provider context-window metadata registry。因而 dynamic 只读取显式环境变量，不从 model name 推测 capacity；未知 context 走可观测的 16000 safe run pool。
- 同一 run 的模型可见输入由 SDK history 继续传递；预算归因放在 `RuntimeContext` 与 `RuntimeToolCall`，不会复制或改变 canonical Evidence。

## 研究边界

本任务只验证 Tool Result projection 的容量、累计记账、Trace 解释性和质量 A/B 关系。retrieval acquisition、模型 registry、tokenizer、retry 和 prompt contract 均不是本任务的可变因素。

真实 A/B 使用本地 `data/trivae.sqlite3` archive 与现有 provider 配置。该数据仅用于本地验证，报告只记录 bounded operational facts、Trace ID 和质量判断，不复制群聊答案正文。
