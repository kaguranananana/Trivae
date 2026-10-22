# Trivae 开发状态

> 整理时间：2026-10-22。此页是跨 Agent 接手的快速入口；当前事实请以代码、测试和 Git 为准，不能仅凭较旧的记录推断。

## 项目目标

Trivae 是使用 Python 分析高噪声群聊技术信息并产生可追溯原始消息的证据型回答的系统。完整背景参见 README.md 和 .trellis/spec/project/overview.md。

## 已记录的最近进度

- 2026-10-22 Runtime 预算可靠性与 Collector 修复完成本地验证：原 10-18 私有快照/参数重放由第四结果投影失败，变为完整返回 4 个 Tool Call、明确预算错误后无工具综合，先前 Citation 校验通过。新增整轮控制结果预留、最小准入、完整投影开销记账及 SDK 异常链预算归因；不扩大 16k 池，仍为 3 工具轮 / 8 模型回合。
- Collector 已修复异常中断时轮次高估和 last_usage 漏计；未知响应/字段用 known_* 下界及 responses_without_usage 表达，Trace/Evaluation 与终态对齐。完整回归 1,217 passed / 1 skipped / 0 failed，产品与测试脚本 Ruff、mypy（129 文件）通过；全树另有 53 项未修改 Trellis 归档 lint 问题。报告：`evaluation/experiments/runtime-budget-reliability-20261022/report.md`。
- GPT-6.1 Sol Medium 尚未验证：生产账号目录核验被 AUTH_OIDC（ID token iat 尚未生效）阻断，推理 HTTP 0/4。未扩能力白名单、未改 .env、未启用 High 代替或独立付费路径、未重启未经验证的配置。下一步先恢复有效 OAuth，再在持久化四请求预算内确认 Medium 并补配置/请求测试与本地启用。
- 2026-10-21 工具轮次审计完成：本地 1,537 条唯一历史 Evaluation、1,534 条可判断工具轮次、166 次三轮触顶，按批次/Provider/模型/Variant/执行版本分别统计。报告位于 `evaluation/experiments/tool-round-budget-20261021/report.md`。
- 同日完成严格 3 Case × 2 配置、6 Query、20 HTTP 的真实 DeepSeek Flash 对照，无重试/补跑/Judge。B 无第4/5轮；miner 的4/4 GT恢复发生在前三轮策略差异中；archify两组均可回答；written-test B为流式解析失败。建议默认维持3轮，待用户决定，未修改产品或GT，实验阶段按指示未提交/推送；后续用户已授权提交并推送工作区变更。
- 10-21 暴露 Collector 在 observer 解析失败时的轮次高估与 last_usage 漏计，已零费用复现；统计缺陷已在 10-22 修复，真实坏正文未保存、JSON根因仍未确认。公价成本下界约 $0.07251，包含一条未知usage的保守上界约 $0.23234，精确Provider账单不可用。
- 2026-10-20 的旧 Journal Session 75：完成历史 Evaluation 审计、正式 A/B 和补充复测；对候选方案未发现可信质量收益，恢复生产基线。
- 同一会话记录了测试、Ruff 和 mypy 的实际验证，并标记人工质量审核为 pending。精确结果和提交号参见旧 Journal 原文，不在此重复可能过时的数值。
- 旧 Trellis 工作流已退出日常开发；其历史开发记录和技术规范仍保留以供查询。

## 仍需确认的事项

- 旧 Session 75 中的人工质量审核是否已经完成。
- .trellis/spec/project/overview.md 提到的 human-verified 标注、长期参数阈值和 HTTP 产品交互，应按当前源码及新任务实际情况逐项核对；这些是旧文档记录的待办，不保证仍未完成。
- 下一个开发目标应以新的用户请求和当前代码状态确定，避免把旧文档的待办直接当成新授权。

## 历史资料索引

- 新开发记录：docs/DEVLOG.md
- 原 75 次会话：.trellis/workspace/anontokyo/journal-1.md
- 原任务 / 评测实验：.trellis/tasks/（包含实验数据，不是缓存）
- 架构及决策：.trellis/spec/project/architecture.md、.trellis/spec/project/technical-decisions/
- 真实问题案例：.trellis/spec/project/problems/
- 后端契约：.trellis/spec/backend/
- 代码和验证：src/、tests/、evaluation/

## 更新规范（轻量）

实质开发/调试/评测完成后，根据已确认结果更新近期进度和待确认项，并在 docs/DEVLOG.md 追加一条事实性记录。无需 Trellis Task、固定 Phase、PRD 或再次批准。简单问答不产生记录。
