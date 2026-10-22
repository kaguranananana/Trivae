# Trivae 开发增量日志

从 2026-10-20 开始使用此轻量日志。此前 75 条开发会话记录位于 .trellis/workspace/anontokyo/，历史 Task、技术决策和评测数据仍保留在 .trellis/ 中。

重要开发任务、问题修复或评测结束后，追加一条包含实际变更、涉及文件、真实验证结果、未完成事项的记录。无强制任务创建和文档模板，不记录琐碎闲聊。

## 2026-10-20 · 将 Trellis 从强制工作流改为知识沉淀

- 停用强制规划、开发阶段、固定 implement/check 子 Agent、Trellis Task 归档以及 Codex/OpenCode 工作流状态注入。
- 保留 75 条旧开发会话、实验数据、已有技术决策和问题记录。
- 保留 trellis-session-insight、trellis-spec-bootstrap；精简 trellis-update-spec；新增 project-memory 用于跨 Agent 进度接力。
- 新增 docs/PROJECT_STATUS.md 作为当前状态入口。根目录 AGENTS.md 保留原先的提交/推送约定和面试文档目录约定。
- 验证方式：静态检查 Skill、Hook、项目配置的变更及文档引用；未修改产品代码，不宣称完整产品测试已通过。
- 后续：重新开启 Codex/OpenCode 会话确认不再自动进入 Trellis Phase；下一次实质开发完成后继续追加本日志。

## 2026-10-21 · 工具轮次预算审计与小规模配置对照

- 新增 `audit_tool_round_budget.py`、`run_tool_round_budget_experiment.py`、`analyze_tool_round_budget_experiment.py`，复用 Evaluation/Trace/GT/HTTP Ledger，未重构 Runtime 或修改生产预算。
- 本地 ignored 历史为 1,537 条唯一 Evaluation，1,534 条轮次可分析、1,537 份Trace可关联，分167组；166个finalizing与166个预算标记是同一组事件。两份Holdout库仅在初始文件库存中读suite/variant数量，内容审计、GT与选题均排除。完整分组/比例、质量关联和典型Case见 `evaluation/experiments/tool-round-budget-20261021/`。
- 真实实验严格3个Development Case各A/B一次，共6 Query、20 HTTP，强制Standard、同一811,892条Snapshot与索引、同Prompt/Tools/Evidence预算/max_turns=8，仅max_tool_rounds=3/5变化。所有B均未执行第4/5轮；miner B恢复4条目标并正确使用核心事实，但在前三轮完成，不能归因额外两轮；archify旧GT缺失但其他实际反馈充分；written-test A漏真实经历、B为AnswerDeltaParseError失败，不补跑。
- 失败核对发现Collector observer异常分支把下一模型turn的tool_round当消耗轮次，并只保留last_usage。通过真实parser/Collector的零费用合成事件复现该统计缺陷；没有声称重放未保存的真实坏字符。生产缺陷保留，建议独立修复。实际20次HTTP中19次完整usage可见，按官方非峰价格观测下界$0.07251、最坏补齐未知响应上界$0.23234，非Provider精确账单。
- 验证：三脚本Ruff通过、compileall通过；既有agent runtime相关测试2 passed / 58 deselected，execution core预算测试2 passed / 26 deselected，observer/parser相关测试4 passed / 25 deselected；统计缺陷离线复现断言通过。独立完整性检查6 Evaluation/6 result/6 Trace、20 HTTP、0 Planner、1 finalizing一致；三份Case仅身份改变，GT/query/scope等逐字段相等，canonical条数保持811,892。未运行完整产品测试。
- 建议维持3轮默认；五轮统一采用的证据不足，暂无新增付费实验。完整私有原始数据、账本和复现保存在 `data/evaluation/tool-round-budget-20261021/`。实验阶段用户明确要求不Commit，当时未暂存、提交或推送，保留既有工作区改动；后续用户已授权提交并推送整个工作区的有效改动，空锁文件与空Obsidian临时文件保留本地。

## 2026-10-22 · Runtime Tool Result 预算可靠性与 Collector 统计修复

- 修改前使用 10-18 原独立快照与工具参数，只读重放 15,866 / 16,000 已消费、134 剩余的真实预算故障，确认 Capability 已执行后 ProjectionError 被 SDK UserError 包装为通用 Runtime 错误。历史工件不覆盖。
- budget.py / openai_tools.py / openai_adapter.py 新增最小准入、同轮全部控制结果预留、失败投影退款、显式预算错误结果及整轮闭合后综合；SDK 包装后保留预算 code/type。evidence.py 修复漏算 metrics/meta 自身开销，未扩大预算或修改 Evidence/Citation 契约。原快照修复后记账 15,758 / 16,000、剩 242，4 调用均有结果、最后为预算错误，Runtime completed、1 Citation binding 通过；第四次 Capability 仍执行，不能宣称消灭全部无用检索或改善真实模型答案质量。
- Collector 按完成工具事实计轮次；新增 usage.py 统一完整累计与 known_* 下界/未知响应语义；projection.py 用终态快照替换逐响应累加，避免漏计或翻倍。终态/Trace/Evaluation 一致性、无依据零结果拒绝、SDK 归因与协议闭合均有确定性回归。
- 新增 16 项预算可靠性测试通过；完整 pytest 1,217 passed / 1 skipped / 0 failed（27.03s）；ruff check src tests scripts 通过；mypy src 通过（129 文件）；diff --check 通过。额外全树 Ruff 的 53 项均为未改动 .trellis 旧脚本/归档问题，不做无关批量修复。
- Medium 阻塞：既有 OAuth 在生产 models 核验前返回 AUTH_OIDC（ID token iat 尚未生效），没有绕过校验或检查凭证正文。推理 HTTP 0/4，账本已保存；未扩白名单、未改本地配置或重启，未用 High/独立付费路径替代。后续恢复有效会话后才能完成 Medium 能力/实际参数/共享配置测试及启用。
- 保持 3 工具轮 / 8 模型回合、16k 未知 context 池；未运行旧付费实验、新 Judge 或 37 题，未改 Holdout/GT/语义索引。脱敏报告位于 evaluation/experiments/runtime-budget-reliability-20261022/report.md，私有重放/结果/完整投影/账本/检查输出位于 ignored data/evaluation/runtime-budget-20261022/。
- Git 收尾：工作提交与状态提交均已完成；普通 git push 被本机 GitHub DNS 解析阻断，ssh.github.com 无法解析，github.com HTTPS 探测也在 10 秒后解析超时。挂起推送已停止，尚未推送；待解析恢复后普通推送，不改 DNS/SSH 全局配置、不 force push。原有两个未跟踪文件未暂存。

## 2026-10-22 · 修复 OAuth iat 时钟偏差并完成 Medium 协议验收

- 网页授权成功但终端失败的根因：官方 Date 比本机快约 3.462 秒，而 JWT 校验未设时钟容差。本地签名固定时刻的完整登录/模型目录回归先复现 2 failed / 3 passed；chatgpt.py 仅增加十秒标准 leeway 后通过，超界 iat/nbf/exp 仍拒绝且不落盘。未关闭签名/身份/时间校验，未读取/复制/输出真实凭证正文。生产既有 OAuth 会话及原 CLI models 命令已复验成功。
- 当前账号目录明确列出 gpt-6.1-sol / medium；model_capabilities.py 精确扩展 Medium，Settings 与 Runtime/Router/Planner 的实际 HTTP 参数 Mock 测试覆盖 medium/high，无静默改档。未根据目录顺带扩大 context 或 Tool Result 池。
- 真实推理先发送前持久化并 fsync，严格 4/4：极小 JSON 探针 1 请求内容校验失败（该条 Usage 未保存、未知），不重复；独立合成预算协议 3 请求全部 response.completed，seed→不可裁剪结构→无工具综合，两个工具为 ok/error、两工具轮，投影 424/198 Token，1 Citation binding 通过。三成功响应已知输入15,647/输出342/总15,989；不冒充四请求完整用量或答案质量收益。两次目录网络预检失败发生在推理前，另存工件，推理计数不增加。
- 本地 ignored .env 切换 Plan / gpt-6.1-sol / medium，并关闭既有 TRIVIAE_ROUTER_JEV_ENABLED（避免 OpenRouter shadow）；新启 Web 127.0.0.1:8710，readiness 确认 Plan/目标模型/ready。此前没有 Web/Chat 进程，不宣称重启了不存在的旧进程。无后续模型调用。
- 验证：完整 pytest 1,224 passed / 1 skipped / 0 failed（27.52s），相关定向127 passed，ruff src/tests/scripts 与 mypy（129文件）通过，diff --check 通过。报告补充在原 runtime-budget-reliability-20261022/report.md，私有记录均 ignored；保持3轮/8turns，不新增Judge、Holdout、GT或索引重建。本轮4次请求已用满。
- Git：有限时 SSH 推送在25秒后超时，GitHub HTTPS 也在8秒后 DNS 解析超时；本轮工作已本地提交，尚未推送。未改变全局网络/SSH配置、未强制推送，网络恢复后执行普通 git push。
