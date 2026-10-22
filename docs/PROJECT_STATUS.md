# Trivae 开发状态

> 整理时间：2026-10-22。此页是跨 Agent 接手的快速入口；当前事实请以代码、测试和 Git 为准，不能仅凭较旧的记录推断。

## 项目目标

Trivae 是使用 Python 分析高噪声群聊技术信息并产生可追溯原始消息的证据型回答的系统。完整背景参见 README.md 和 .trellis/spec/project/overview.md。

## 已记录的最近进度

- 2026-10-22 进一步零模型诊断真实回复遗漏：三题首轮canonical消息身份与顺序均重放一致，目标原消息已模型可见（rank43/14/6、m1-43/14/6）。Matt-1只改正确anchor即可在原7,352额度恢复；Matt-2正确回复首轮已取回，却被搜索投影一次删除全部72条非hit context，最终仅用8,449/15,801；改正确anchor补查可在原6,954额度恢复。Archify原704额度下，即使正确anchor/仅关系补查仍只剩原消息；足够的离线额度才能恢复。新增诊断脚本，未改产品/GT/索引/预算，无新增模型请求。报告：`evaluation/experiments/reply-context-live-20261022/miss-diagnosis.md`，工作提交 `7176aae`。
- 2026-10-22 补完真实模型终端验收：Plan / gpt-6.1-sol / medium，三条原始 Development + 一条隔离合成控制，共12次真实推理、全部response.completed、0次门禁阻断、无重试/Judge。原预算3轮/8turns/16k与原问题保持；三题均completed且自主开启include_replies，42项确定性检查通过/3项不适用，但旧required reply均未送达模型（Archify/Matt-2有预算阻断，另有anchor选择和context裁剪问题），未证明质量提升。
- 合成控制中，真实模型自行通过回复关系找回相隔143条噪声的唯一反馈，最终保留正负两面并引用真实reply；3请求/2工具轮。四题合计Usage输入167,113/输出3,377/总170,490，均完整。未修改产品；新增实验/分析脚本与报告，定向15passed、Ruff和mypy通过。报告：`evaluation/experiments/reply-context-live-20261022/report.md`，工作提交 `a224fc8`。
- 2026-10-22 关键回复恢复审计与修复完成：`get_message_context` 新增显式 `include_replies`，按同会话/直接转发容器的真实回复边补查，保持原容量与 16k 预算；模型投影保留原始回复关系及当前结果内可唯一解析的短 handle，目标裁剪后不留下悬空关系。修复 20 锚点上限未披露的截断事实，Trace/Evidence 同步新参数与回复边界。本轮普通 `git push` 仍在 25 秒后超时，尚未推送。
- 原始最小复现 2 failed，修复后新增 12 项回归通过；真实 10-20 Development 快照固定 anchor 配对：Archify、Matt-1 从 1/2 目标到 2/2，Matt-2 保持 2/2，关系与目标 Citation 均通过，模型请求 0 次。完整 pytest 1,241 passed / 1 skipped / 0 failed，Ruff、mypy（129 文件）通过。未验证真实模型自主选 anchor/新参数或答案收益；未修改预算分配、历史压缩和索引。报告：`evaluation/experiments/reply-context-20261022/report.md`，工作提交 `25e7438`，开发记录提交 `bc35810`。
- 2026-10-22 后续 Plan Medium 实验完成：用户追加并放宽至 24 次/每 Case 8 次，保留旧 4/4 账本；实际新用 12 次、4 条 Development Query 均 completed、无实验门禁阻断。Archify 真实触发两个预算错误，四个 SDK Tool Call 均有响应，最终综合与四组 Citation 绑定通过。Runtime/Trace/Evaluation 的轮次及累计 Usage 一致；没有自然复现坏 JSON，未声称质量提升或 A/B 收益。
- 新实验发现前三条 Case 的 canonical ToolResult 限制未进入 Trace，最小修复 Collector 的一次 emit；原始失败 Evaluation 保留，Matt 零 HTTP 原输出序列/快照重放后检查通过，稳定 Evidence/答案/Citation 不变，修复后新 Archify 全部检查通过。完整测试 1,229 passed / 1 skipped / 0 failed，Ruff 和 mypy（129文件）通过。Web 已重启加载修复，Medium readiness=ready。报告：`evaluation/experiments/runtime-budget-followup-20261022/report.md`。
- 2026-10-22 Runtime 预算可靠性与 Collector 修复完成本地验证：原 10-18 私有快照/参数重放由第四结果投影失败，变为完整返回 4 个 Tool Call、明确预算错误后无工具综合，先前 Citation 校验通过。新增整轮控制结果预留、最小准入、完整投影开销记账及 SDK 异常链预算归因；不扩大 16k 池，仍为 3 工具轮 / 8 模型回合。
- Collector 已修复异常中断时轮次高估和 last_usage 漏计；未知响应/字段用 known_* 下界及 responses_without_usage 表达，Trace/Evaluation 与终态对齐。完整回归后续补齐至 1,224 passed / 1 skipped / 0 failed，产品与测试脚本 Ruff、mypy（129 文件）通过；全树另有 53 项未修改 Trellis 归档 lint 问题。报告：`evaluation/experiments/runtime-budget-reliability-20261022/report.md`。
- OAuth 阻塞已修复：公开官方时间快约 3.462 秒，原 JWT 零容差导致新授权在 iat 校验失败；固定十秒 leeway 的完整登录与超界回归通过，既有会话及 CLI models 已成功。账号目录明确支持 Medium，能力白名单和 Settings/三条共享 HTTP 参数测试已补齐。首轮真实推理严格 4/4（一个 JSON 探针内容失败、独立预算协议三请求成功），真实 Medium 预算退出与 Citation 通过；不是质量 A/B。ignored .env 已改 Plan / gpt-6.1-sol / medium，关闭独立 Jev shadow，Web 8710 readiness=ready。旧四次账本已封存，后续授权追加实验见上方记录。
- 2026-10-21 工具轮次审计完成：本地 1,537 条唯一历史 Evaluation、1,534 条可判断工具轮次、166 次三轮触顶，按批次/Provider/模型/Variant/执行版本分别统计。报告位于 `evaluation/experiments/tool-round-budget-20261021/report.md`。
- 同日完成严格 3 Case × 2 配置、6 Query、20 HTTP 的真实 DeepSeek Flash 对照，无重试/补跑/Judge。B 无第4/5轮；miner 的4/4 GT恢复发生在前三轮策略差异中；archify两组均可回答；written-test B为流式解析失败。建议默认维持3轮，待用户决定，未修改产品或GT，实验阶段按指示未提交/推送；后续用户已授权提交并推送工作区变更。
- 10-21 暴露 Collector 在 observer 解析失败时的轮次高估与 last_usage 漏计，已零费用复现；统计缺陷已在 10-22 修复，真实坏正文未保存、JSON根因仍未确认。公价成本下界约 $0.07251，包含一条未知usage的保守上界约 $0.23234，精确Provider账单不可用。
- 2026-10-20 的旧 Journal Session 75：完成历史 Evaluation 审计、正式 A/B 和补充复测；对候选方案未发现可信质量收益，恢复生产基线。
- 同一会话记录了测试、Ruff 和 mypy 的实际验证，并标记人工质量审核为 pending。精确结果和提交号参见旧 Journal 原文，不在此重复可能过时的数值。
- 旧 Trellis 工作流已退出日常开发；其历史开发记录和技术规范仍保留以供查询。

## 仍需确认的事项

- 回复补查路径与真实模型使用能力已验证；真实三题未恢复旧required reply。零费用对照已定位搜索投影整批删context、补查anchor选择及Archify单次余额不足的不同影响；下一步优先验证搜索自动上下文的关系保留/裁剪，再评估首轮预算和候选关系线索。尚未修复这些策略问题，没有质量A/B或稳定收益证据。
- 10-22 修复已本地提交，但 GitHub DNS/SSH 网络阻断普通推送；后续实验收尾的普通推送仍在 25 秒后超时，网络恢复后需执行 git push。
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
