# Trivae 开发状态

> 整理时间：2026-10-23。此页是跨 Agent 接手的快速入口；当前事实请以代码、测试和 Git 为准，不能仅凭较旧的记录推断。

## 项目目标

Trivae 是使用 Python 分析高噪声群聊技术信息并产生可追溯原始消息的证据型回答的系统。完整背景参见 README.md 和 .trellis/spec/project/overview.md。

## 已记录的最近进度

- 2026-10-23反问答案后续质量审计（0新增生成请求）：同群含“反问”的61条原文全部进入既有lexical结果；实际投影31,117/125,000，余额93,883，当前无需扩大总池。但发现已读跨场复盘/模拟复练与面后联系建议未展开（均机器人来源）；另1103字面经的岗位/全栈定位及前端强需求问题位于1040偏移之后，600字预览与1000字record仍挡住该尾部。主要类别可用，不等于全部有用信息已检索并输出；下一步优先长消息分段读取与已读信息覆盖，不改历史答案或宣称全量语义召回。详见interview-answer-20261023/report.md后续审计。

- 2026-10-23最新反问技巧Trace覆盖修复：旧479字回答正常stop，原语义13,839 Token挤占16k证据池，词法61命中仅9条送达、52条hit裁掉。官方账号/models明确context_window=500000，004bd20登记当前Plan/Sol容量，既有动态公式得到125k证据池；显式锚点补读恢复原1000字record范围，Prompt保留具体问法/适用条件与真人/bot区分。只改Prompt/补读的16k控制2HTTP仍预算失败，保留；最终同题3HTTP/2轮completed、1471字/8段、26来源原文时间范围核对通过，实际投影31,117、四类真人清单实际可见4/4。不是全历史穷尽或一般稳定收益；超过1000字record/未展开转发仍有限制。完整pytest1,263 passed/1 skipped（31.08s）、Ruff/mypy129文件通过。Web已重启加载004bd20，数据库/语义827,614及Plan ready；未重算索引。完整答案interview-docs/面试反问技巧-群聊证据整理.md，诊断evaluation/experiments/interview-answer-20261023/report.md；新增5真实请求，含2个失败请求，均独立保留。

- 2026-10-23用户要求进一步清理后，将已结束真实运行的重复语料数据库合并：删除55份数据库及3个别名，六份历史代表数据库9.82GiB无损压缩为1.91GiB，完整解压流与原文件逐块比较通过。独立答案/Trace/失败/账本保留；2,770个原有非目标文件在更新存储收据前大小/修改时间保持，61份说明已更新。可用空间实测2.47→15.88GiB（约16GiB），本轮增加13.41GiB，测评目录约2.9GiB。当前共享快照改为gzip归档，旧脚本重跑前须解压并准备独立副本；版本位置见data/evaluation/storage-cleanup-20261023/shared-snapshots.json，完整操作见round2-manifest.json。在线readiness仍数据库/语义827,614、Plan/Sol ready；未改线上库/原始导出，0新增模型请求。

- 2026-10-23用户授权清理重复测评数据库：14组零推理准备与12组离线重放/索引对照共删除57份数据库，逻辑90.28GiB；APFS共享块下实测可用约0.74→2.48GiB，实际增加约1.75GiB。2,805个原有非目标文件大小/修改时间保持，真实推理结果、失败及运行快照保留；历史语料与当前索引共享副本保留，后者811,892条身份/readiness只读核对通过。26份新存储收据及4份旧共享路径修正已落盘；旧离线脚本需按原协议重新准备已删除数据库。报告evaluation/experiments/storage-cleanup-20261023/report.md，本地完整清单data/evaluation/storage-cleanup-20261023/manifest.json。剩余空间仍紧张，不把逻辑体积当作实际释放量。

- 2026-10-23当前修复清单已完成已复现范围的验证：20ce741冻结的最终系列，原空日/密集两天/两周分别2/3/3真实HTTP首次completed，Finalizer全部valid、无工具参数/预算错误，逐条来源复核通过。两天94条/14,969Token引用10-18/19/20，两周98条/15,007Token引用10-06/10/14/18/20，均诚实partial，未声称全量热度；总输入105,632/输出3,106，Usage全已知。完整产品回归1,261 passed/1 skipped（27.34s）、Ruff/mypy通过。报告evaluation/experiments/quality-repair-20261022/report.md，清单docs/REPAIR_PLAN.md。
- 此次续推三系列共19真实HTTP，volume旧空日一次最终格式失败仍保留，最新8请求全部有效；不同实现/题目不混成稳定成功率。Web已加载bef1dc8产品代码；aa9deb0仅验证准备显式复用索引，空间不足已处理。所有真实运行快照/Trace/账本保留，仅清理0推理失败/未运行重复准备副本。后续源码修改应基于新的具体Failure Case或用户目标。

- ca01b86的密集两天真实自主3HTTP完成：先20+四段，投影20/18/19/19/18、14,986Token，四段全部有正文、finalization valid，主题原文复核通过；输入44,345/输出1,380。随后完整空日控制出现非网络失败，系列按设计退出：模型先误传absolute时间对象，纠正后完整0条，但旧错误历史使no_result unavailable，模型仍选择该格式被拒。三请求24,819输入/328输出，失败保留，14天尚未执行。定位到SDK把time_range公开成任意dict，仅文字要求relative；bef1dc8已从已有RelativeTimeRange生成字段Schema，JSON仍走原Capability解析，不放宽Finalizer或更改错误历史。完整1,261 passed/1 skipped（27.34s）、Ruff/mypy通过；补充验证非法absolute仍显式INVALID_ARGUMENT、后续合法relative正常。准备原temporal-schema-series时重复重建索引实际耗尽磁盘（0推理）；aa9deb0显式复用冻结索引、校对身份/readiness，准备smoke通过。仅清理失败/未运行重复副本，真实运行快照保留，剩余空间523MiB→2.5GiB。20ce741冻结的temporal-schema-v2-series已通过复用准备并启动，顺序验证原空日、密集两天、14天；运行中不改源码或HEAD。

- 0ff6bc0冻结生产系列已完整执行，14天3HTTP/2工具轮：先20条+四窗，投影20/20/20/18/18、14,949Token，全部无预算错误；四窗总数86,287，最终引用10-09/13/16/20且valid，主题原文复核通过。两天2HTTP也valid但仍取5,000/14,619、投影146条/15,767Token集中短时段。新证据证明“短窗直接max”用天数代替消息量，276a56d已去掉此分支，统一先小页按实际量决定分页/分段；完整1,260 passed/1 skipped（27.78s）、Ruff/mypy通过。ca01b86冻结temporal-volume-series已启动，顺序验证密集两天、完整空日、14天，运行中不改HEAD/源码；不把上一轮两天的诚实披露误报为覆盖修复完成。

- 2026-10-23 持续推进：9c9e134已将长窗20条探路、少量不重叠子窗、保留partial边界的指导落到生产；完整pytest1,260 passed/1 skipped（30.58s）、Ruff及mypy129文件通过。份额修复后的两次自主运行四窗均有正文，最终HTTP分别ReadTimeout/RemoteProtocolError，均保留；固定原两轮历史的独立最终综合1HTTP完成，引用及主题来源支持通过，但不冒充完整自主成功。
- 新增验证层连续执行器：独立冻结快照与每次账本，总推理次数只累加；仅已观察到的网络错误继续，其他错误明确退出并保存异常链。模拟断流→成功保留两次/累计4请求、非网络契约错误仅执行一次并显式退出，Ruff通过。用户授权睡眠期间持续推进，当前聊天已设置15分钟自动续接；下一步冻结最新生产版本执行14天与2天完整自主验收，期间不修改HEAD/源码。

- 同轮时间窗份额已修40b8997：新长窗真实指导先20条，再发四个65条窗口，旧贪心分配让后两窗预算错误。真实SQLite/SDK最小回归先failed；Host仅对同轮全部get_recent_messages的多调用均分扣除控制结果后的数据额度，16k不扩大，具名/语义/上下文及单次调用不改变。固定真实原参数后四窗全部送达18–19条，总15,029；前3个Host结果身份/顺序不变。36定向、完整pytest1,260 passed/1 skipped（27.54s）、Ruff/mypy通过；真实自主复核继续，Web已重启加载至0ff6bc0；readiness数据库ready、语义827,614/827,614、Plan/Sol ready。
- 2026-10-22 后续生产自主验收：Archify 3HTTP完成，首轮11,782、两次补查2,029/1,720成功，第三次仍预算错误198，总15,729<16k；答案保留正负反馈及补查引用。advice首个unit连接失败保留，新独立control 3HTTP完成并通过源证据复核；zero预检失败保留后2HTTP完成。三条有效结果合计41检查通过/4不适用，单次观察不作稳定成功率；原配对失败不能补成完整A/B。
- 中文单字已修233dc23：真实“荐”0/7和转发“程”漏召回先失败；独立Han主索引只服务完整单字keyword，保持原bigram/BM25。原64题中4单字覆盖20/44,703→44,703/44,703，60非单字全深度顺序不变；生产克隆64题count+top10 parity通过。单字FTS增加142.61MiB，原库重建27.05秒；多词夹单字/ASCII词内前后缀仍旧契约，不声称解决所有CJK边界。60定向、完整pytest1,259 passed/1 skipped（28.66s）、Ruff/mypy129文件通过。
- 本地Web已重启加载全部已落地修复；在线827,614 canonical +14,720转发重建32.62秒，canonical不变，6个非单字控制前十保持，荐/习/模/码各2,526/17,182/16,300/9,679命中。readiness数据库ready、semantic completed且827,614/827,614、Plan/Sol ready；没有重算语义向量。
- 长窗新探针默认可信5,000下自主取5,000/86,287，投影15,768Token，随后连接失败。零模型重放只保留同一天约7分21秒的146条；不能把Host5000等于模型已读5000。既有工具的小页20+5子窗×15计划，在完整SDK中95条/5日期、15,528Token、计数和86,287，仍partial；固定答案只证明预算可行。此为历史基线；后续分段指导已于9c9e134落地，完整自主验收继续。
- 2026-10-22 持续迭代中（用户明确要求不要在阶段结果处停止）：新增当前Plan owner/advice/zero各一次，全部完成；owner已收到但遗漏机器人导师/技术兜底建议，5句通用观点覆盖候选在新owner回答中恢复并区分来源。候选advice第二HTTP为TLS连接失败，zero认证预检失败（0推理），均保留，尚不能声称完整质量A/B通过。
- 同轮复现并修复Semantic远直接回复遗漏：真实SQLite/vec0/Capability/投影最小回归先1 failed；ContextExpander范围上下文在原容量内复用批量回复关系，保留ANN命中身份/顺序、非hit回复身份、0/0不扩展及时间边界。33项定向通过，完整pytest1,254 passed/1 skipped（28.48s），Ruff、mypy129文件通过，工作f683bf0。
- 投影精简已落地d52ffdf：显式公共默认字段、省略模型词法打分细节；原三题逐消息事实全部保持，Archify15,257→11,761Token、100条不变，Matt各95→100条且约13.8k。完整SDK固定原工具决策两次补查由预算错误恢复为各15条，总15,440<16k，原固定答案/引用保持。完整pytest1,255 passed/1 skipped（27.61s），Ruff/mypy通过。此为工程验收，真实自主配对仍因认证刷新/TLS连接失败待完成；旧失败保留，HTTP2/TLS1.2未证明可修复，未加产品重试。
- SQL计算无期限已修复（6a63937）：1000消息/十亿交叉计数隔离复现max_rows=1仍持续计算；SQLite VM进度回调覆盖scope准备/execute/fetch的5秒期限，超时显式SQL_EXECUTION_TIMEOUT，后续正常查询可用。确定性回归先failed后通过，真实万亿交叉计数在5.000秒中断；十亿计数可在5秒内完成，不误报为应超时。8项定向、完整pytest1,255 passed/1 skipped（30.15s），Ruff、mypy129文件通过。不宣称同步SQL已变成异步线程执行。
- 2026-10-22 修复清单已沉淀至docs/REPAIR_PLAN.md，并完成首批5条Plan源证据复核及三题首轮预算配对。8k候选虽恢复补查空间，却减少首轮来源，Matt遗漏基线已有的teach负面意见；不采用为默认。6Query/16HTTP，15完成、1TLS连接失败；已知Usage输入215,947/输出4,324，另一次未知，失败保留。报告evaluation/experiments/first-round-budget-20261022/report.md。
- 同轮最小修复Runtime格式资格信息：每次工具返回后复用Finalizer的原判定，把当前no_result是否可用传给模型；不改校验、检索或生产预算。完整pytest1,251 passed/1 skipped，Ruff及mypy129文件通过，后增回放接口回归定向5 passed。原错误答案仍被拒绝；固定原工具历史的一次真实Plan最终综合改用claims，空日事实与3条统计引用通过，输入10,674/输出214。不是自主检索验收或全库收益。工作6ba2596、回放修正4a9dde8；初次回放namespace错误及真实HTTP400均保留，真实综合共2次发送尝试、1次有效完成。报告evaluation/experiments/final-response-contract-20261022/report.md。
- 2026-10-22 核验外部问题评估：历史 Miner 失败发生在检索/工具选择层（目标未进入 Host），此前 Prompt 充分性候选已被否决。另核对已有 Plan/Sol/medium 同题工件，模型通过 semantic→lexical 找到 ResumeSkills 的用途匹配替代资源，名称、用途及链接均有保存的 ToolResult 原文支持，3 HTTP/2工具轮、投影11,866、余额4,134；单次观察不能声明稳定修复，也不能仅凭旧target遗漏判业务失败。没有新增模型请求或修改产品；空结果契约测试15 passed。下一步先复核现有当前模型答案质量，再决定具名资源修复；首轮预算分配仍有当前直接证据。
- 2026-10-22 搜索回复送达修复并完成真实验收：Lexical 在原容量内先批量恢复所有已返回 hit 的明确直接回复，再填普通邻居；投影仅省略必要普通 context，保留 hit/回复关系。新增会话/回复目标访问索引，未扩大 100 条/16k 池、不改 Prompt/GT/语义向量。原参数零模型重放三题直接 hit 身份/顺序不变，目标模型覆盖均从 1/2 到 2/2；完整 pytest 1,246 passed / 1 skipped，Ruff、mypy（129 文件）通过。工作提交 `366f290`。
- 同轮真实 Plan / gpt-6.1-sol / medium 原三题各一次、7 HTTP 全部 response.completed，三条原遗漏回复全部进入首轮输入并被最终答案引用（Sources 9/7/6）；Archify 最终固定目标 Evidence 1/2，Matt 两题 2/2，均 finalization valid，42 passed/3不适用。Usage 输入110,808/输出3,397/总114,205。Archify 仍有两个明确预算错误，未声称一般预算策略已解决或全库质量提升。离线引用核验提交 `7a7bdde`，报告 `evaluation/experiments/reply-repair-20261022/report.md`。
- 同轮定位终端直连 DNS 超时；使用 macOS 已有 127.0.0.1:7892 代理完成认证/推理及 GitHub SSH443 连接，未改全局网络。Web 从31153重启为40113加载修复，当前827,614条本地库及Plan/Sol均ready，回复索引已创建；实验仍是独立811,892条旧快照。普通推送成功，远端 main 从9539aec更新至a4e7fbb，包含此前因DNS阻塞未推送的提交。
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

- docs/REPAIR_PLAN.md本轮已复现范围已收口；当前owner/advice/zero及最终空日/两天/两周有有效来源核验。原精简配对受网络失败不能判胜负，重复稳定性/fresh Holdout未验证，不作为新的已知产品Bug或全库收益。
- 具名资源问题须区分历史 DeepSeek 失败与已有 Plan/Sol 用途匹配替代答案，先做当前模型/来源的质量核验，不能直接重复已否决的 Prompt 方案。10-20 zero-empty-2 曾取得完整空时间窗，但额外日期分组行使 no_result 不合契约；Semantic远回复及SQL计算无期限已复现并修复；CJK单字已独立修复；长窗分段自主验收完成但始终为partial，不宣称完整或代表性。
- 原三题的关键回复送达/最终引用已在真实模型下恢复；原Archify补查在SDK固定决策中恢复；当前自主运行两次补查成功、第三仍失败，未证明一般预算策略或全库稳定收益。没有 Holdout、重复采样或全库质量 A/B，不能外推稳定收益。
- GitHub DNS/SSH 直连问题可通过现有系统代理解决，本轮普通 push 已成功；后续终端网络操作仍需使用相同进程代理，不改变全局网络或强推。
- 旧Session 75人工质量审核尚未确认；本轮Assistant源证据复核不替代人类审核。
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
