# Trivae 开发状态

> 整理时间：2026-10-27。此页是跨 Agent 接手的快速入口；当前事实请以代码、测试和 Git 为准，不能仅凭较旧的记录推断。

## 项目目标

Trivae 是使用 Python 分析高噪声群聊技术信息并产生可追溯原始消息的证据型回答的系统。完整背景参见 README.md 和 .trellis/spec/project/overview.md。

## 已记录的最近进度

- 2026-10-27用户自行登录后明确授权继续，约束为“不要尝试自己启动QQ”。只重新加载原com.trivae.import-once与独立邮件worker，10:00/22:00日历保留，QQ自启动仍禁用且配置/代码不存在。现有QCE接口可达，15:30这轮8群导出849条、游标一致至15:15:24，无在途任务；正式入库及双索引15:37:35完成，198文件completed、文件/索引待办均0，Canonical861549/revision95769，LaunchAgent最后exit0。当天自然晚间dispatch仍未发生，不能以白天入库成功保证收件。
- 同轮正式补发续跑复用原8批，再完成第9、10批，第11批在HTTP响应前TLS EOF中断，尚未发送。已用SQLite backup API冻结revision95116并逐字段核对原21101片段，原20261027-121632-ad094bc3/10-26日期可继续显式resume；下次须使用data/evaluation/digest-resume-20261027/canonical.sqlite3及原data/trivae.digest.sqlite3，不能混入新Canonical。当前代理的httpx和系统curl均复现api.openai.com TLS握手失败（代理CONNECT200后无HTTP响应），绕开进程HTTP代理诊断也超时；用户确认未改代理，未更改网络、凭据或模型。修复resume遗漏补发日期、错误停留上次额度失败及已发送仍进入生成的问题；回归先红，最终48 passed/1 skipped、Ruff、mypy137、diff通过。当前阻塞为模型连接，不应误报仍是额度不足；Trace及网络/服务/快照证据data/evaluation/digest-resume-20261027/。
- 2026-10-27晚报筛选改为具体项目资料、可复用实操及招聘面试经验，取消普通讨论凑数，正文泛称、折叠来源群内短标记，Canonical作者原文保留。真实旧材料重筛61→23项，103个来源片段/111条摘录核对，样稿SMTP接受；不冒充新提示下全部重读。漏发查到10-25空报告在SMTP连接阶段DNS失败后被旧pending状态永久阻挡；新增发送前失败分类及下次触发复用正文，DATA阶段不明确错误仍需核查。正式补发最初因subscription_sharing_usage_limit_exceeded失败，后续最新状态见上述续跑记录，成功水位仍未推进。
- **2026-10-27 QQ账号事件，后续接手先读：**排查时错误地新增com.trivae.qce-runtime登录自启动及失败300秒重启，日志确认13:38、13:43、13:48快捷登录失败（身份/登录态失效）；用户随后报告QQ冻结并自行验证恢复。不能从本机日志确认腾讯冻结原因，也不能排除该操作触发或加重风控。已禁用并移除新增启动配置/代码，当时同步暂停既有导出调度，原数据及配置保留。用户后来只授权恢复已经运行QCE的采集/推送，仍明确禁止自行启动QQ；不要恢复QQ/NapCat启动、重启、快捷登录或登录自启动。当前采集恢复及邮件阻塞见最新进度。本机事件证据data/evaluation/qq-login-incident-20261027/。

- 2026-10-26 QCE 时间水位导出已接入（工作提交 a973c8f）：用户脚本移至 scripts/qce-incremental，ignored 配置取原 8 个群；同一 com.trivae.import-once 每天 10:00/22:00 先导出、静置、入库及双索引，再沿原晚间入口 dispatch。登录/唤醒补偿、非零约五分钟补跑、每群成功游标及在途 taskId 恢复；首次复查从 10-16 00:00 开始。锁外读游标与条数不匹配回归先 2 failed；真实空窗口 JSON 成功。联调另复现 Canonical/semantic 长事务 spill 锁住 Web，两个实际存储回归先 failed，再启用 WAL，已打开旧 DELETE 连接迁移回归通过；未延长超时或吞错。全量 1327 passed/1 skipped（42.97秒）、Ruff、mypy137通过。首轮 71964 条导出全部完成，首次旧进程静置 deferred 两文件后实际退出75，launchd 自动第二轮按原水位补偿并等待59.5秒；最终 Canonical/语义均854818（新增12661），revision89038对齐，174文件全部completed、0文件/索引待办，任务最后exit0。生产本轮语义事务期间 Web readiness HTTP200/1.772秒，明确 stale，两个库均 WAL；原500日志保留。QCE原WebUI8个定时已通过API实际停用并保留配置/本机旧快照；新消息正式词法按群及精确时间命中，Web最终readiness HTTP200/semantic completed。原历史版本冲突875+237次仍保留来源，不视为错误或已自动统一；物理休眠/重启和自然晚间联动仍待使用中观察。本机证据 data/evaluation/qce-incremental-20261026/，配置和水位不提交。

- 2026-10-24邮件晚报详细版已落地并发出改版样稿：先按群名分组，各话题前置相关资源链接，多段还原对象用途、起因、具体回应、方案、分歧与进展；移除5至8分钟及固定主题数目标，材料充足时通常400至800字，按真实信息量展开。综合补送候选所引用的完整原文，引用仍按编号绑定；同项跨群来源明确报错。HTML原始发言默认折叠，589px浏览器展开/收起已验证，用户已在QQ邮箱实际收件中明确确认“能正常展开”，客户端原文折叠验收完成。裸网址紧接中文被当成域名的问题新增回归先failed，修后通过。最终全量pytest1309 passed/1 skipped（31.21秒）、Ruff和mypy137文件通过。同快照复用16批75个旧候选，送达466个完整来源片段；1次真实新版综合stop（655秒），产出6群61话题、正文19370字符，464处来源身份/作者/时间/偏移/正文及478条摘录回读Canonical通过，27个链接均来自已选摘录。人工抽看12个话题，未声称全部语义或外部事实核实；未冒充新提示下全量重读。新版样稿SMTP已接受，本地preview-expanded-20261024-214822保留完整Trace/验证/邮件回执。定时入口和正式交付水位未改。

- 2026-10-24群聊邮件晚报已实现并启用：四方向筛选、Canonical修订增量、迟到/转发补齐、回复前情、全部文字分批阅读、主程序绑定引用、HTML/纯文本邮件及独立交付水位。全量pytest1307 passed/1 skipped（30.82秒）、Ruff与mypy137文件通过，最终编辑提示调整后22项日报回归通过。10-23真实6536根消息/6590文字片段、16批75候选，最终12主题；76处来源切片和80处摘录回读Canonical通过，5处未展开转发明确披露。样稿已由真实QQ SMTP接受，用户随后明确确认已收到；此前IMAP未定位该封的检查保留原记录，收件依据为用户确认；样稿不推进正式水位。独立worker与晚间导入dispatch均已注册，原10:30/22:30日历不变，安装后导入补查exit0；首个自然晚间触发尚未发生。HTTP520、ReadTimeout与旧54项综合删字错误均保留，显式续跑只重用同快照成功阅读批次；综合改选引用编号，未放宽原文匹配或新增产品自动重试。说明docs/daily-digest.md，本地样稿及验证data/digests/preview-20261024-180736-212743/。既有Web未重启。

- 2026-10-23剩余Failure修复已落地（f9fc1dc）：转发树保留旧事实的单调补齐及旧raw溯源/enriched计数，原revision驱动双索引发布；SQL计算让出事件循环、Trace留原线程，ASGI慢SQL期间readiness/Stop通过；混合单汉字AND复用既有两索引求交；partial空检索新增正式insufficient_evidence且不放宽no_result；流式坏JSON保存有界偏移/正文/状态诊断，仍显式失败。原两个红探针现均exit0，5秒SQL期间20ms回调约21ms执行，补齐正文可检索。完整pytest1280 passed/1 skipped（31.26秒）、Ruff/mypy129、前端80项/typecheck/lint/build通过。冻结834636条/revision68856，同一配置7次自主查询、21HTTP全部completed/valid；笔试两次找到直接经历，Nanobot/Matt/Archify/owner及空结果逐段复核，82处引用Canonical核对通过，无Host投影省略/工具错误。小样本不证明稳定成功率、全量语义召回或额外轮数收益；源245个未展开转发仍需完整导出，旧解析坏正文不可追溯。Web已正常重启，库/语义834636及revision68856对齐、Plan ready。完整报告docs/FAILURE_REPAIR_20261023.md，原审计保持历史事实。

- 2026-10-23剩余Failure审计完成（a6fdee4，0新增生成）：1,574条唯一Evaluation/200分组及近期独立工件复核，2个封存库排除。新增确定性复现：空转发后补齐正文仍被判equal duplicate且incoming raw不保存，重建FTS仍0命中，完整版本先导入控制为1；真实SDK同步SQL使20ms回调延迟约4.98秒，快查询控制正常。当前“github.com 荐”0命中但主表字面19条；部分覆盖空检索的no_result仍失败，空来源claims仅degraded。旧Plan笔试题110条材料漏目标，当前原词排名41、聚焦词排名8；当前完整配置未重跑，不能报为最新模型必现。全量pytest1269 passed/1 skipped（33.53秒）、前端80项、Ruff/mypy通过；两项独立审计门禁预期红，未修产品。具体优先级、根因、实验及边界见docs/FAILURE_AUDIT_20261023.md，探针scripts/audit_failure_boundaries.py。

- 2026-10-23前端七项清单已落地：正式段落引用+来源侧面板/窄屏抽屉、原文主动重读及ordinal复用、接收确认后清草稿、按会话保存阅读位置、前进后退/范围URL/侧栏偏好、交错详情归属、范围内全历史正文搜索与分页、中文限制及44px触摸区。新增三项旧实现失败回归后修复；前端80项/typecheck/lint/build、完整后端1269 passed/1 skipped、Ruff/mypy通过。1280×720/390×844浏览器确认来源展开不改正文位置、引用定位返回、正文词搜索与后退184→184。Web已重启，库/语义829397、Plan ready，0新增推理；实体软键盘/读屏未验收，整页刷新不保存滚动。详见docs/FRONTEND_REVIEW_20261023.md修复段。

- 2026-10-23前端只读审查完成：窄屏604×732已有长回答展开25条Sources时自动滚到末尾，根因为全内容ResizeObserver复用生成跟随；另代码确认首次创建失败丢草稿、原文错误缓存阻止重新读取、历史搜索仅最近100条标题/摘要等。完整前端71项测试、typecheck/lint/build通过，0新增模型请求、未改产品。已复现/静态发现/建议及边界见docs/FRONTEND_REVIEW_20261023.md；下一步优先最小修复前三项。

- 2026-10-23仓库默认轮数已与本机统一为6（bfa3118）：limits.py提供唯一默认值，环境加载/ModelSettings/注入Runtime及.env.example同步；显式较小轮数仍优先，8turn/证据公式不变。新增真实SDK循环回归先在旧默认3下failed，修后允许六轮工具、第七回合无工具综合completed；两处旧Prompt测试显式固定原3轮，保留原断言。完整pytest1267 passed/1 skipped（27.31秒）、Ruff/mypy通过。0新增真实模型请求，Web原本已显式6轮，本轮无需重启。此次统一是用户偏好的产品配置选择；前一轮同题两组均只用2轮，尚无第4至6轮独立质量收益证据。

- 2026-10-23全部范围综合已调整（575460a）：主题建议/技巧/经验/观点先按Schema最大词法召回、初始0/0邻居，再补长文/回复及具体概念缺口；默认展开问法、用途、条件和注意事项，不需每题声明详细。本机显式证据池125k→200k、工具轮3→6，8turn/128k单次及通用默认公式保留。全范围同题旧首取100/167、846字/6段，新首取8群167/167、1899字/8段；各3HTTP/2工具轮completed/valid，投影23,852→50,559，新余149,441，0预算省略/0工具错误，22/28来源Canonical核对通过。不把改善单归因大预算，未声称语义穷尽/零遗漏；缺失转发仍partial。完整pytest1266 passed/1 skipped、Ruff/mypy通过，Web已重启加载工作提交及本机新预算，库/语义829,397、Plan ready。报告evaluation/experiments/broad-advice-20261023/report.md，完整新回答在本地data/evaluation/broad-advice-20261023/expanded/answer.md。

- 2026-10-23长消息读取已修复（8d74aa8）：get_message_context按原文content_offset/content_limit分页，默认/最大8000字符，公开真实总长与实际投影续读位置；搜索600字预览不变，Host正文页与1000字引用摘录分离，尾页引用位置随codec/Web保存。98dd02b接通来源面板“查看完整原消息”，只读本地Canonical。真实1103字尾段599起504字零生成重放通过；同题自主3HTTP/2轮completed、1555字/8段、30来源切片/时间/范围核对通过，前端/全栈定位、强需求和跨场复盘实际进入答案；证据32,270/125k、余额92,730。后端1266 passed/1 skipped、Ruff/mypy通过，前端71 passed/typecheck/lint/build通过，真实浏览器原文展开可见。Web重启前后当前库/语义均829,397、Plan ready，任务期间库已更新，非冻结语料A/B；不报一般稳定收益或有用信息零遗漏。报告evaluation/experiments/long-message-read-20261023/report.md；最终正文20k/20条Evidence、3轮等未触顶，缺失转发正文/图片/OCR和综合选择仍有边界，总预算不扩大。

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

- 最新审计确认转发正文补齐被丢弃、SQL阻塞事件循环两项当前缺陷尚未修复；组合单字检索及部分覆盖空结果交付仍有边界。当前244个转发缺口涉及143条根消息，但未确认多少具有可恢复的更完整导出，不能将244直接作为归并缺陷的丢失数量。下一步修复和验证入口见docs/FAILURE_AUDIT_20261023.md。
- 笔试经历检索、结论与所绑来源不匹配、旧流式AnswerDeltaParseError根因仍需闭合。先补当前配置的原题/来源复核；语义改写、六轮独立质量收益和Planner一般收益属于实验缺口，不冒充已证实当前Bug。实体手机软键盘/读屏仍未验收。
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
