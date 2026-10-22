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

## 2026-10-22 · 扩展 Plan Medium 实验并修复 Trace 限制传递

- 用户允许追加并放宽实验次数；旧 4/4 账本保留，新账本先冻结 12 次/每 Case 4 次，再保留已有9次调整为24次/每Case8次。实际新用12次、四条既有Development Case各一次、0次门禁阻断，所有HTTP发送前校验Medium并持久化预扣，失败也计入、不自动重试。原Snapshot/索引身份一致，不重绑GT、不重建索引，不触碰Holdout/Judge/旧付费脚本。
- Matt/Miner/Written 均completed、每条3 HTTP/2工具轮；投影分别15,768/11,866/15,754，余额232/4,134/246。三条均暴露 limitation_preservation 诊断失败：canonical ToolResult 有 coverage:partial / unexpanded_forward_content，但 Collector 的 runtime.tool.completed 遗漏 limitations。最终 Artifact 已保留限制，未修改 Evaluation 检查掩盖故障。
- collector.py 仅补一次emit的canonical限制字段，两个确定性测试覆盖普通/预算错误结果。保留原三份真实失败Evaluation；Matt原SDK输出和快照零HTTP重放后限制检查通过，规范Evidence（排除新运行身份）/答案/Citation绑定一致。首次离线强字节相等断言失败已保留，查明latency_ms及派生预算导致两次投影±1 Token、asdict tuple和JSON list比较差异，随后对保存JSON稳定事实逐项核对，未为实验断言更改产品。
- 修复提交d4cf513后用新Archify验证：3 HTTP/2轮/4 Tool Call，投影14,628+738+198+198=15,762，余额238；两工具返回TOOL_RESULT_BUDGET_EXHAUSTED，SDK四个结果齐全，Query completed，4组Citation绑定、18个有效引用、0丢弃，14检查通过/1不适用/0失败。实际Capability3次，仍有一次返回后才发现数据投影放不下，最后一次检索被跳过，未宣称消除全部无用检索。
- 追加12个响应均response.completed，Usage输入190,897/输出3,345/总194,242，逐响应、终态、Trace和Evaluation一致；四条真实流均正常结束，坏JSON中断统计只由前轮确定性测试覆盖。仍维持16k产品池、3工具轮/8turns；四条不构成质量A/B，不支持统一五轮。结束因为本轮可靠性问题已验证并归档，非请求预算耗尽。
- 完整pytest 1,229 passed / 1 skipped / 0 failed（30.38s），定向34 passed，ruff src/tests/scripts与mypy src（129文件）通过，diff --check通过。新增实验脚本与3个零费用账本门禁测试。Web旧进程29549已重启为31153，8710 readiness确认Plan/Sol/ready，ignored配置Medium/Jev关闭，健康检查0推理。
- 脱敏报告在evaluation/experiments/runtime-budget-followup-20261022/report.md；完整Trace/正文/冻结副本/账本及授权调整/失败与重放/安全汇总保留ignored目录。工作代码已提交，前置普通git push仍在25秒后网络超时；收尾提交后继续普通推送并按实际结果交付。两个原有未跟踪文件未暂存。

## 2026-10-22 · 关键回复恢复与关系投影审计修复

- 先经真实导入/SDK/Capability/投影复现 2 failed：143 条中间消息使明确回复落在局部窗口之外，单独取得回复后又丢失 reply 字段。修复前复现命令为 `uv run pytest -q tests/test_reply_context.py`。
- 在既有 get_message_context 增加显式 include_replies，SQL 同 session/time 查直接回复；转发另限同直接 parent/container，不递归或扩大消息容量。anchor/回复优先，哨兵披露 has_more_replies；无平台 ID 显式失败。普通默认窗口保持原意，不做检索失败切换。
- evidence.py 对真实回复保留原始关系，目标在当前结果内唯一且可见时关联短 source handle；预算裁剪优先保留请求的 anchor/回复，删除目标时撤掉悬空关系 handle。普通消息不重复搬运平台 ID。SDK schema、Prompt 参数说明、Trace 请求/结果和 Evidence 快照同步；ContextExpander 修复前20来源上限遗漏的 truncated 事实。
- 新增 audit_reply_context.py，只读 10-20 快照与三个明确 Development 目标，固定 anchor 配对 2/2 窗口有无 include_replies；Archify、Matt-1 的模型可见目标从1/2到2/2，Matt-2维持2/2；目标回复关系及真实 Host Citation 绑定通过。另有3/5窗口与只取直接回复对照，原快照大小/mtime不变；没有模型请求、Holdout、GT修改或索引重建。最终工件在 ignored `data/evaluation/reply-context-20261022/paired/`。
- 新增12项回归；完整pytest **1,241 passed / 1 skipped / 0 failed（29.42s）**，Ruff src/tests/scripts、mypy src（129文件）和diff --check通过。生产SDK loop 的搜索handle→补查→最终Citation/Trace贯通，但模型由ScriptedModel提供，不能声称真实模型自主选择或答案改善。未在本轮调整首轮预算、工具轮次、Semantic或历史压缩。
- 报告在 `evaluation/experiments/reply-context-20261022/report.md`，工作提交 `25e7438`；收尾后按既有授权普通推送，网络结果以随后交付/记录为准。下一步是单独验证真实Agent在原预算下能否自主选中有价值锚点、开启补查，并满足必要事实。
- Git 收尾：工作与开发记录均已提交后执行普通 `git push`，25 秒超时退出；随后 bounded SSH 检查明确返回 `Could not resolve hostname ssh.github.com`。尚未推送，不更改全局 SSH/网络配置，不 force push。保留既有 DNS 阻塞，待网络恢复后普通推送。

## 2026-10-22 · 回复调查真实模型终端补验

- 用户要求补真实模型验收，复用此前授权的Plan / gpt-6.1-sol / medium；目录预检成功。原Archify/Matt-1/Matt-2各运行一次，保持原10-20问题、scope、GT和811,892条快照/现有语义索引；克隆到独立ignored目录。强制Standard，七种生产工具，3轮/8turns/16k不变，不注入目标或补查提示、不调用独立Jev/Router/Planner模型。
- 三题共9HTTP，全部completed、每题2工具轮，模型分别声明3/1/3次include_replies。Host→模型→Evidence固定GT覆盖为Archify 1/2→1/2→0/2、Matt-1 1/2→1/2→1/2、Matt-2 2/2→1/2→0/2；三题旧required reply均未送达。Archify首轮14,699Token并有两次预算错误；Matt-1选另一anchor且未耗尽；Matt-2有一次预算错误及context投影省略。42项确定性检查通过/3项不适用/0失败，不计为答案质量收益；回答包含其他来源，不能机械由旧GT遗漏判整题错误。
- 为确认真实模型消费到实际回复，另冻结一条合成控制，共用原24/每Case8账本，不覆盖三题协议。145消息、143条间隔噪声、唯一体验不含项目词。真实模型自行lexical→context(include_replies=true,after40)，通过关系找回窗口外reply，最终正确表达正负反馈并引用；3HTTP/2工具轮。合成控制不是群聊质量A/B。
- 合计12真实响应全部response.completed、0门禁阻断、无重试或补跑/Judge。完整Usage输入167,113/输出3,377/总170,490；不混淆累计模型输入与16k工具池。目录GET不计推理。原HTTP账本、完整正文/Trace、模型输出、冻结执行脚本和快照均保留ignored `data/evaluation/reply-context-live-20261022/`，最终汇总 `final-summary.json`。
- 初次按脚本文件启动因scripts包导入失败，推理前改用python -m，未补跑已发送Case。合成控制的实验渲染首次漏传source summaries，已修正实验脚本；由同一持久化Artifact零HTTP补渲染，确认anchor/reply两来源，原终端输出保留。未修改产品渲染器、模型答案或检查阈值。
- 只新增三个实验/分析脚本和报告，未改产品。定向回复/账本15passed（1.30s），Ruff src/tests/scripts、mypy src（129文件）、diff --check通过；不重复完整产品回归，沿用上轮1,241passed/1skipped的已记录边界。报告：`evaluation/experiments/reply-context-live-20261022/report.md`，工作提交 `a224fc8`。后续优先验证首轮预算分配与anchor选择，而不是宣称回复功能已带来稳定质量收益。
- 本轮SSH复核仍明确返回 `Could not resolve hostname ssh.github.com`；GitHub DNS阻塞未解除。工作与开发记录提交后仍按约定尝试普通推送，不更改全局网络或SSH配置。

## 2026-10-22 · 真实回复遗漏的分层因果诊断

- 用户追问原因后，新增 diagnose_reply_misses.py，只读重放已存三题原参数、实际投影额度与独立快照；三题首轮canonical消息身份/顺序均与原记录完全一致。模型请求0次，不改产品、GT、索引或旧工件。
- `--case matt2 --require-delivery` 明确复现预期AssertionError：required reply missing from model projection；工具已取得目标但模型不可见。该命令用于捕获现有缺陷，未将预期失败计作回归通过。
- 目标原消息排名43/14/6，模型可见handle为m1-43/m1-14/m1-6，均未被补查选中。Archify只自动扩前20锚点；Matt-1局部窗口够不到远距离回复。实际所选其他anchor直接回复为0，不等于项目没有其他回复；模型内部选择原因仍不能仅由Trace断言。
- Matt-2原目标已在首轮完整Host结果，但作为非hit context随72条邻居一起删除。投影当前先整批删context、再缩hit正文；留下28hit，仅用8,449/15,801，仍有7,352额度。回复优先仅覆盖显式context，不覆盖搜索附带context，是上一轮修复边界。
- 只换正确anchor、保持原窗口/单次额度，Matt-1在7,352、Matt-2在6,954即可恢复目标；Archify在704仍失败，改0/0仅关系也仍省略回复。Archify原16k池首轮14,699后剩1,301，同轮三个控制结果预留597，首个补查数据额度704。相同正确anchor的离线16k投影对照可恢复，未伪造实际剩余额度或据此修改生产池。
- 报告在 `evaluation/experiments/reply-context-live-20261022/miss-diagnosis.md`，私有事实含原文/定位，保存ignored `data/evaluation/reply-miss-diagnosis-20261022/diagnosis.json`。脚本Ruff、compileall、diff --check通过；实际三题重放/反事实对照已执行，未改产品，不重复完整pytest。工作提交 `7176aae`；下一步应优先验证搜索context裁剪，再隔离候选关系线索与首轮预算分配，不声称质量已改善。

## 2026-10-22 · 搜索回复送达主链路修复及真实答案验收

- 用户要求自行诊断、持续修到真实可用。搜索投影两个最小失败与自动回复扩展两个最小失败先复现，修复 evidence.py 的整批 context 删除：仅二分省略必要普通邻居，保留关联到 hit 的非 hit 回复，再沿原正文缩短/尾部 hit 省略流程；删 hit 时移除其附属回复、更新计数与可见 provenance/handle。
- Lexical 自动 context 在同一 limit 内优先批量补齐全部返回 hit 的明确直接回复，再填前20锚点的普通邻居。SQLite 普通消息一次目标集合连接，转发每root只解析一次，严格同session/time及直接parent/container；不递归，不改0/0或Semantic range。新增会话/回复目标索引，不改canonical revision、不重建FTS/语义向量。metadata保留回复扩展计数及容量截断事实。
- 新增5项回归，完整pytest **1,246 passed / 1 skipped / 0 failed（30.49s）**；Ruff src/tests/scripts、mypy src（129文件）、diff --check通过。既有Semantic投影测试改为验证新契约“保留可容纳的普通context”，不是维持旧的整批删除数量；其他身份/过滤/时间断言保留。工作代码及冻结入口提交 `366f290`。
- 新独立快照/协议/账本在ignored reply-repair-20261022，旧失败和原诊断不覆盖。verify_reply_repair固定旧实际工具参数/15,801额度：直接hit身份/顺序均不变，三题模型可见目标1/2→2/2且关系正确；Archify100条/15,262Token，Matt各95条/15,762和15,727，仅删5普通context，不增加100/16k容量。
- 首次OAuth刷新因直连DNS超时失败，0推理，保留preflight-direct-network-failure.json。查得macOS已有127.0.0.1:7892系统代理；仅进程设置代理后，认证刷新/目录预检通过，再执行三原题各一次。Plan/Sol/medium，原问题/scope/GT/Prompt，Standard七工具，3轮/8turns/16k不变，无GT提示、Jev、Judge、Holdout或推理重试。
- 实际 **7 HTTP、7 response.completed、0门禁阻断**：Archify3请求/2工具轮，Matt两题各2请求/1轮。三条原遗漏回复全部首轮送达并被最终答案引用；Host→模型均2/2→2/2，最终Evidence为1/2、2/2、2/2，Archify未最终引用固定anchor但引用其正确reply。Citation binding 5/4/5，全部valid，42检查通过/3不适用/0失败。Usage输入110,808/输出3,397/总114,205，全部完整。
- 实际答案加入了原遗漏的“好用”反馈，也保留/区分具体负面体验、短评局限和机器人安装介绍。verify_reply_answers从同次持久化Artifact恢复，经生产CLI Evidence/Sources组件零HTTP生成terminal.txt；目标reply的Sources编号9/7/6、结论binding与真实source均核对。脚本提交 `7a7bdde`。这是三题局部事实恢复，不宣称全库质量A/B或稳定收益。
- Archify后续两次补查仍有明确TOOL_RESULT_BUDGET_EXHAUSTED并进入最终限制，Matt首轮接近池上限后无工具综合；一般首轮预算策略未在本次解决。没有用更大池、fallback或掩盖错误的规则通过验收。
- Web从31153重启为40113加载修复，经现有代理运行，数据库与Plan/Sol readiness=ready；当前827,614条本地库的回复访问索引已创建，与独立811,892条实验旧快照区分。健康检查0推理。经同一代理GitHub SSH443远端读成功，定位此前普通推送失败的网络原因；收尾提交后普通推送，不改全局SSH或强推。
- 报告 `evaluation/experiments/reply-repair-20261022/report.md`；完整原文/Trace、账本、repair-replay.json、analysis.json、answer-verification.json与网络/Web工件保留ignored独立目录。更新当前状态及回复/存储契约，最后改动仅验收脚本/文档，已验收产品代码保持不变。
- Git收尾：经现有系统代理执行普通git push成功，origin/main从9539aec更新至a4e7fbb，包含本轮及此前DNS阻塞的本地提交；当时main与origin/main对齐、工作区干净。该事实补记后继续普通推送，无amend/force或全局网络改动。

## 2026-10-22 · 核验质量问题评估与当前模型证据

- 用户要求核验粘贴评估并给出优先级/实施建议。本地起点为8346804，与评估引用提交一致；检查当前代码、10-20质量/独立验证、10-21轮次实验及10-22可靠性/回复修复工件，未新增联网推理、Judge、Holdout或产品修改。
- Miner历史四目标未进入Host结果，首个偏离在检索/工具选择，不能说成“找到后没选对”。具名充分性Prompt候选已有负结果并恢复基线，不建议直接重复；现有named-resource-sufficiency-v1.json是诊断/候选否决记录，不是已上线修复。
- 进一步读取ignored runtime-budget-followup-20261022/miner/result.json：Plan/Sol/medium原题通过semantic_search→lexical_search(ResumeSkills)交付用途匹配替代答案；保存的两条forward ToolResult原文分别支持resume-bullet-writer用途及仓库链接，保留机器人分享/未实测边界。3HTTP、2工具轮、投影11,866/16,000、余额4,134、finalization valid。该既有运行仍有旧Collector limitation_preservation失败，保留原记录；本轮源证据复核不是人工审核或稳定收益证明。
- zero-empty-2独立验证取得过目标日complete/0，失败还涉及不合辅助聚合条件的日期分组行，不能只归因缺少空证明。当前Finalizer仍区分纯数值辅助聚合与普通结构化行；本轮uv run pytest -q tests/test_no_result_finalization.py：15 passed（0.63s）。
- Archify修复后首轮15,256Token、后续两次预算错误是当前直接证据，但不自动证明答案质量下降。Semantic仍走expand_ranges、SQL仍在async工具内同步执行且无查询计算时限；本轮仅确认静态路径，未把潜在风险升级为已复现故障。长窗300/28,028只证明覆盖不足，不能单独裁定总结事实错误。
- 建议先复核现有当前模型答案及必要事实/引用支持，再决定具名资源改动；若做工程实验，先固定16k总池隔离首轮分配，记录必要证据覆盖与完整回答，避免同时改Prompt/排序/轮次。长窗、CJK、Semantic及SQL各按真实需求或最小复现独立推进。文档之外无改动，无需重跑完整产品回归。
