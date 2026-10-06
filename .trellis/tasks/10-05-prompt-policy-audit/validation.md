# 审计与实施验证

> **当前门禁结论：候选已实现，真实等价回归未通过；运行源码与测试已恢复原版。任务保持 in_progress，不归档或报告完成。候选见 [prompt-candidate.py](research/prompt-candidate.py)，配套文案断言见 [candidate-tests.patch](research/candidate-tests.patch)。**

> 以下第一节保留 2026-10-05 的审计阶段事实；当前交付状态、产品验证和真实配对见后续实施章节。

# 历史：审计与规划验证（2026-10-05）

## 本轮交付与状态

- 基线 `460259d`，初始 main 工作区干净。
- 完成 P01–P92 逐条审计、PRD、design、implement 与后续 context manifests。
- 审计是 planning 阶段产物；尚未修改产品源码、测试、SDK Schema、Provider 请求或 Finalizer。任务保留 planning，等待最终规划评审，不提前 start/归档。
- 下一批建议仅 Markdown 分层、策略去重和已有承接说明压缩；JSON mode 生成契约保留。迁移标签不是实施完成标志。

## 真实执行的检查

### Prompt / SDK 实物核验

`uv run --all-extras python` 导入当前 SYSTEM_PROMPT，实测 `len(SYSTEM_PROMPT)=20450`。直接构造六个生产 SDK adapter 的 FunctionTool，传 trusted_max_results=5000 并读取 params_json_schema/strict_json_schema。无 Provider 请求、无 Capability invocation。

实际结果：六工具均 strict=false；lexical/recent max=5000、semantic max=20、member/SQL max=100；context 默认 8/8，身份均 optional 且无 oneOf；字符串无 minLength、context/dense_top_k 无 minimum、time_range/cursor 为自由 object。Host 真实校验通过对应源码定位，没有假定这些规则已经下沉到 Provider Schema。

### Provider-free 契约 baseline

```bash
# 实际执行成功的命令；覆盖 SDK、Runtime、来源/时序、预算、Finalizer、时间窗/零结果和 SQL。
uv run --all-extras pytest -q tests/test_agent_tool_surface.py tests/test_agent_runtime.py tests/test_context_source_contract.py tests/test_temporal_relation_regression.py tests/test_retrieval_budget.py tests/test_evidence.py tests/test_temporal_overview_coverage.py tests/test_temporal_zero_result_integration.py tests/test_recent_messages.py tests/test_sqlite_read.py
```

结果：**145 passed in 2.00s，exit code 0**。这证明当前契约 baseline 可运行，不证明重构后的模型行为等价；本轮无候选产品实现、无新真实 Provider 配对、未执行全量 pytest/Ruff/mypy。

首条命令误引用不存在的 `test_temporal_overview.py`，pytest exit code 4、no tests ran。通过 `rg --files tests` 定位实际文件后改用 `test_temporal_overview_coverage.py`，并纳入 recent/zero-result/SQL 相关文件重跑。是命令路径错误，不是实现或 assertion 失败；未改测试。

### 文档与范围检查

实际 Python 检查结果：P01–P92 ID 连续、每条有合法标签、交叉引用的 Policy ID 存在、覆盖字符串 L7–230 全部 **224 行**，**27 个**本地文件链接全部可解析，PRD 无 TBD、JSONL context 引用均存在，task 状态为 planning。`git diff --check` 和产品范围 `git diff --quiet HEAD -- src tests evaluation` 均 exit code 0。

`task.py validate .trellis/tasks/10-05-prompt-policy-audit` exit code 0，两个 context manifest 各 5 条有效记录。脚本提示既有 agent-runtime-guidelines.md 为 64,762 bytes，超过自动注入单文件 32,768 bytes；后续子代理必须按需要读取原文件相应完整章节，不能只依赖被裁剪的注入。该提示不改变本轮审计结果，也不通过改注入预算解决。

## Spec 沉淀判断

参考 `trellis-update-spec` 检查了新知识归属。现有 runtime/temporal/quality spec 已定义 Host 时间、source identity、软 Plan、Finalizer 和评测边界；本轮无新的已实施或已确认契约，因此**不修改正式 spec**。Schema 缺口、JSON mode 与语义反例记录在 research/design，避免把待评审迁移写成既成规范。

## 完成边界

本轮只能声称“审计与规划已提交”。不能声称 Prompt 已压缩、token/latency 改善、模型质量提高、Schema 迁移完成或整个重构任务完成。推送状态以 git push 实际退出码为准。


# 第一批实施验证（2026-10-06）

## Problem / Motivation 与设计取舍

原 Prompt 实测 20,450 字符，混合检索决策、参数、Host 校验、证据、JSON 格式，存在重复策略与四个单行字面重复。选择 Markdown 分层和同义去重；仅加标题不能减少维护重复，一次性将字段移到 Structured Outputs 又依赖当前不存在的 Provider 契约。第一批只改 `prompt.py` 与五处文案断言，完整映射见 [refactor-mapping.md](research/refactor-mapping.md)。

最终候选主 Prompt 为 **13,479 字符**，减少 6,971（34.1%）。工具 description/Schema、typed input、Capability、检索、Plan、默认窗口/limit、三轮预算、Provider、Finalizer 与公共输出字段不变。必要参数提示和 claims/no_result 形状仍保留；没有新 fallback/retry/guard 或依赖。

## 工程验证与测试失败定位

- 首个候选两项纯措辞断言失败：换行拆开 `use get_message_context` 与 `canonical internal message ID`。调整 Prompt 排版后原断言通过；没有放宽执行测试。五项主动文案更新的旧/新语义与 Policy ID 已记录在映射中。
- 相关十个文件：**145 passed in 2.07s**。
- 全量首候选：**662 passed in 16.56s**；最终修订：**662 passed in 17.33s**。
- `uv run --all-extras ruff check src tests` 及两份实验脚本：通过。
- `uv run --all-extras mypy src`：115 个源文件通过。
- `git diff --check`：通过。以上静态检查不证明模型语义等价。

## 实测协议与 Observability

从生产数据库做一次 SQLite backup，Canonical 约 1.4GB、semantic 约 304MB。Baseline 冻结为 `460259d` 产品源码；候选源码各修订分别冻结。使用正式 Application、Runtime、Capability、Finalizer、Conversation/Trace/Evaluation，每 cell 独立进程与输出库，显式强制两侧 standard 路由，无 Planner 注入。实际 Provider/model 为 DeepSeek/deepseek-flash，现有配置与预算不变。

13 个场景包含原讨论、教程回复、GitHub、精确事实、精确空结果，四条已暴露 Development Case（Archify、概念查找、最近两天、空时间窗），以及 SQL、人物、双类别和课程/视频/文档清单。Development 使用原 query/scope；其他场景同一固定群、上界和 trusted max_results=5000，保留历史背景访问。全部是已暴露的定向样本，无 fresh Holdout、人工盲审或机械质量总分。主会话直接复核实际工具投影、完整答案和对应作者/UTC；不把关键词命中当成生产规则或通用评分。

同 Case 内 AB/BA 顺序交错，两对实验可同时运行。每 cell 先 preload 再启动 Query 计时，warmup 单列。保留首次 SDK instructions、工具描述/Schema/settings，以及完整实际 HTTP request、response usage、Trace、工具参数、输出/citation。实际工具正文为 Python literal 字典，分析器用 ast.literal_eval 读取；没有改生产序列化。既有 20k Debug capture 不代表完整模型输入，完整 HTTP body 是本轮对照事实。

首次 SDK 预检（无网络）：instructions 20,643→13,672 字符；六工具描述与 Schema 序列化均 16,129 字符，非策略契约完全一致。真实每对首个 HTTP body 只允许 system 策略不同；工具规划及后续输入是模型行为的结果，不能要求其相同。脚本从仓库根目录执行：

```bash
uv run --all-extras python .trellis/tasks/10-05-prompt-policy-audit/real_pair.py --variant baseline --case reply --repeat 0 --preflight-only
uv run --all-extras python .trellis/tasks/10-05-prompt-policy-audit/real_pair.py --variant candidate --case reply --repeat -1 --preflight-only
uv run --all-extras python .trellis/tasks/10-05-prompt-policy-audit/analyze_pair.py
uv run --all-extras python .trellis/tasks/10-05-prompt-policy-audit/analyze_pair.py --schedule schedule-final.json --output review-final.json
```

`real_pair.py` 拒绝覆盖已有 cell，原始失败不以重跑覆盖。`experiment/` 的数据库、消息、完整请求、schedule 与 review packet 仅本地保留并明确忽略，不提交私人聊天数据。归档后将上述脚本路径前缀换为归档任务路径；工作目录仍为仓库根目录。

## 首候选 v1：32 次 / 16 对（不是最终候选分母）

13 场景各一对，讨论/回复/GitHub 各再一对。两侧首个 HTTP 非策略 body **16/16 完全一致**。Baseline 15 completed、1 completed_degraded；候选 16 completed。唯一结构降级为 `baseline-github-2`：局部 citation 的 MISSING_EVIDENCE，strict_validation_failed/citation_dropped，丢弃 1 项、验证 17 项，既有 Finalizer 可见诊断。不能用这些状态代表语义准确率。

| v1 侧 | Query 数 | Provider total tokens | Query mean latency |
| --- | ---: | ---: | ---: |
| Baseline | 16 | 1,390,991 | 20,893 ms |
| Candidate v1 | 16 | 989,582 | 20,657 ms |

缓存、Provider 波动及工具选择均影响这些值；不据此宣称通用节费或提速，实际货币 cost 未测。

### 真实 Failure Case 与当前处理

| 场景 | 观测与定位 | 最小修订 / 边界 |
| --- | --- | --- |
| 宽讨论两次 | 两侧均未送达后训练书籍推荐；v1 虽读相关 context，但 after=14/18 等局部窗不足。检查完整 HTTP 工具投影，不能以 Finalizer valid 当召回完整 | 恢复原版 20/40 选窗示例及“不是新默认”；仍由讨论线索决定，不固定窗口，不新增自动补查 |
| 精确书名 | v1 在同轮向 lexical 发出标点/空格近似变体，Baseline 一次即可 | 恢复原版明确第二次近似调用禁令；不建 Runtime 去重 ledger |
| 课程/视频/文档清单 | v1 先精确词再 semantic，未检查 URL lexical；Baseline 也先精确词，后面才查 URL，均不遵守原意图策略 | 明确讨论/清单意图先于通用查找默认；不加针对“全栈”的特殊词规则 |
| GitHub 时间 | v1 回答范围约写到 8/14 12:56，实际选源含 12:59:10，Host 上界更晚 | UTC 指导保留；Finalizer 无自然语言时序校验，本轮不新增解析器 |
| 近似双 semantic、强否定、内部细节 | 原版/候选均有重复语义查询，局部/全窗边界混用或内部范围细节出现在正文 | 记录既有语义限制；不因一次检索空结果声称全窗无消息，不把合法来源当自然语言正确 |

Archify 两侧保留 7/23 与 8/6 区分。对“安装了以后咋用”复查实际作者为 W，未误记为候选作者错误。SQL 两侧经 schema→SQL 得到 UTC 8/14 的 297 条；人物两侧均 find_members→canonical sender filter；空窗两侧均 complete-empty→no_result；双类别两侧 URL 首查并另查 Skills，均为本批已核对契约。

## Boundary / Ownership、Why not 与 Evolution

Prompt 拥有模型选择策略与证据表达；上游为用户 query、trusted scope 与软 guidance，下游为 SDK 工具和语义候选。Host 拥有确定性参数、权限、时间和游标；Finalizer 拥有结构/来源与现有 empty-proof；Evaluation 拥有实际模型语义检查。没有把这些职责并到新的组件。

Structured Outputs、必要 Schema bounds/互斥、日期解析、no_result 的关键词空结果与全窗无消息措辞纠正目前为 waiting for contract/failure evidence，非永久否定；触发应是明确 Provider 支持、真实参数错误或新的语义修复需求，并独立冻结变量与真实配对。全局 ledger、新预算或重试目前不需要。

事实索引：为什么分层/为何暂不完整下沉见 design 和本节；真实失败及定位见上述表；字符变化和执行状态为 measured facts，质量泛化与规模扩大收益未测；作者/时间/覆盖结论要回查真实消息。没有创建标准面试答案。


## 最终修订：14 次 / 7 对

最终候选从 v1 恢复明确近似查询禁令、意图优先级与非固定的 20/40 示例。冻结后执行 discussion/reply/github/fact/concept/materials 各一对（repeat=3），再按反序执行一对 discussion（repeat=4）。这是修订后的新实验，不能把前面 32 次都算到最终候选。

**14/14 completed，7/7 首次 HTTP 非策略 body 完全一致**；无 Provider exception、无新 retry、无本地 citation 降级。所有查询累计 46 次，45 completed、1 Baseline completed_degraded。

| 最终侧 | Query 数 | Provider total tokens | Query mean latency |
| --- | ---: | ---: | ---: |
| Baseline | 7 | 934,584 | 31,621 ms |
| Candidate final | 7 | 799,612 | 26,916 ms |

小样本、两对并行、先 preload、缓存未人为固定、后续工具选择不同；一次 Baseline 宽讨论达 93,265ms、589,026 tokens，不能用这些均值推断稳定性能或货币收益。

### 逐场景核对与剩余失败

- **教程回复**：两侧均取得 Build a LLM from Scratch 与“这本书很详细”，准确归于在串中，保留 Red Herring 提问与 joye 非教程回应；候选以 source_id context after=55 送达推荐。候选仍同轮查了“后训练”与“Agent 教程”，检索必要性并不因成功而自动合理。
- **GitHub 清单**：两侧均 URL lexical-first、limit=5000、0/0 context，不加 recent/SQL 重数；候选列出实际链接与来源。日期仍有约写，不能以 JSON 有效证明 UTC 表达严格遵从。
- **精确书名**：候选首先精确词，又查泛词“AI Agent”并额外读 context；书名、朗易思听与 8/14 15:01:47 UTC 命中正确。但答案称到 8/15 01:23 是“约26小时”，实际不足11小时，并额外写北京时间。是实测语义错误；现有 Finalizer 无时序 entailment，保留失败，不加日期解析或样例补丁。直接禁令并不能保证模型每次停止。
- **概念查找**：候选 semantic-first，随后 lexical 与两个 context，恢复手敲、项目+视频等学习建议；未复现 v1 同轮近似双 semantic。
- **课程/视频/文档清单**：候选恢复 github.com-first 最大 limit 和 semantic 非 URL 路径，再补“全栈”；后一次 lexical limit=200 仍不遵守库存最大值要求。具体课程/文档/仓库覆盖改变，有 RBAC、飞书教程与视频学习方式。不能说每条材料完全相同或策略百分百遵从。
- **宽讨论 repeat=3**：Baseline 从关键提问读 after=25 取到两条推荐投影，候选命中同一提问但只读 after=18，未送达书名，答案进而误称未给教程。这一对是明确的答案退步，不能藏在总体完成率中；定位为 context 范围与强否定生成，工具/Host 没有丢失请求范围。
- **宽讨论 repeat=4**：两侧均未送达书名；候选没有展开关键问题并重复近似 semantic，还首轮给了 2025 年下界；Baseline 也漏该提问并将检索最新消息当截止。最终两对候选均漏书名，Baseline 一对恢复、一对遗漏；若计入 v1，两版本候选分别为0/2，Baseline四次只有1次恢复。该事实不证明稳定优劣，也不能称宽讨论已达到语义等价。

完整生产调用不是答案正确性的判据。当前实测确认策略与机械契约承接及若干路径正常；**全面语义等价未证实，宽讨论召回、停止、强否定与自然语言时序仍有失败**。这批候选实现了职责分层与去重，但明确答案退步未通过交付门禁，尚未替换运行中的 Prompt；不能描述成等价重构完成、讨论质量修复完成、通用性能提升或新 schema migration。新的语义修复需独立处理真实 Failure Case，并验证原版与候选中的失败，不能继续给本次结构重构附加随机补丁。

## 收尾检查

主会话应用 trellis-check 直接核对 PRD/design/implement 与 backend/runtime/quality spec，不使用子代理。实现只改策略字符串，工具和跨层执行无变更；所有 P01–P92 承接映射保留，五处测试更新限于文案。正式 spec 新增第19节，记录现有 JSON mode/Host/Finalizer 责任与实验分母边界，不把待下沉契约写成已实现。Trellis context validate 通过；runtime spec 的既有注入超长警告仍存在，已从原文件读取所需章节，不扩大预算。


## Gate decision / 待用户评审

最终两次宽综述均漏推荐，且 repeat=3 原版成功、候选失败，当前不能认定候选已通过关键回归。静态 Policy 全覆盖不能排除措辞、顺序与去重导致的模型执行退步；仅凭这两对也无法分离稳定策略退步与模型方差。已经尝试恢复直接禁令、意图优先级与窗口示例，实际仍失败，因此停止继续随机润色或追加付费重跑。

运行 `prompt.py` 与五项测试断言均恢复 HEAD 原版，仅保存完整候选及配套 patch，原始实测不覆盖。任务保持 in_progress，未触发“验证通过后的任务归档与完成收尾”。推荐下一轮缩小去重范围，讨论调查、时间、负面结论与停止等关键段保留原文，优先删除字面/跨段重复；另一选项是先人工审阅完整候选与失败，再确定需要保留的措辞。两者都必须新冻结变量并验证，不能直接把本轮完成率作为质量 gate。


## 阶段性提交授权（2026-10-06）

用户明确要求先提交并推送当前部分。此次提交保存审计/实施文档、完整候选与测试 patch、配对脚本及失败报告；运行源码和测试仍为原版，任务仍为 in_progress，不归档。私人消息、实际完整请求与数据库快照继续只留在 ignored experiment 目录中。推送是否成功以实际 Git 命令结果为准。

# 低成本持续优化阶段（2026-10-06，接续9256550）

## 本轮结论

完成A00责任矩阵、H01低成本筛选入口、F01 synthetic fixture、P01单一limit契约迁移候选、H02历史生产Baseline零API导入、H03重复边界收口。每项独立commit，历史失败candidate/patch/配对结果完全保留。

**Production SYSTEM_PROMPT仍原版20,450字符，逐字未改。** P01开发候选仅删104字符机械limit片段，20,346字符；L0通过，未做真实semantic gate，不发布。产品SDK唯一改动是lexical/legacy limit严格正整数校验，合法默认与范围边界不变；原SDK把true/2.0转换成整数的真实失败由字段约束修复。不能说所有工具参数已迁移：context/dense/query/互斥/游标/get_schema仍有矩阵所列缺口。

责任分布：92条完整Base位置映射，A79、C10、D8、E16、F4、G60（重叠），B另列5项动态事实。保持Discussion/Negative/Temporal/Stop/Retrieval routing原文顺序；清单选择最大limit仍是模型语义策略，maximum不能代替它。ChatLab实际builder和semantic-search-guidance已检查，职责分层可借鉴，但归档时间/handle/claims等Trivae契约不复制改写。

## 实际验证与费用

- 初始相关baseline：31 passed（agent surface/context/evaluation/SQL）。
- H01：26 passed（含7项新增screening）；F01：8 passed；P01 static CLI：77 passed；H02新增拒绝旧candidate；H03新增mapping/重复边界。
- 最终全量：`uv run --all-extras pytest -q` → **697 passed in18.11s**。
- `uv run --all-extras ruff check src tests scripts/run_prompt_screening.py scripts/freeze_recorded_prompt_baseline.py` → passed。
- `uv run --all-extras mypy src` → **116 source files passed**。
- `git diff --check`与`task.py validate` → passed。既有runtime spec超过32KiB自动注入上限的提示保留；主会话从原文件读取所需章节，不扩大注入预算。
- Production Prompt相对9256550：无diff。候选全文=原文.replace(唯一目标片段,"",1)；92条原文mapping覆盖224/224行测试通过。
- 真实DeepSeek调用：**0**；新input/output/total tokens：**0/0/0**；新增API费用：**0**。未执行real candidate、full gate、fresh baseline、semantic embedding preload、Judge API或Provider probe。
- 六个历史baseline本地冻结及6/6生产SDK/schema/model_settings/settings/scope/snapshot原文reuse预检通过；历史token不算本轮费用。完整私有Trace/请求/答案在ignored data/evaluation/prompt-frozen-20261006，不提交。

## Evidence / Semantic边界

ScriptedModel首轮双工具选择全部记录，零Host工具调用，只有一个model turn；实验FirstToolProbeStop终态不作完整答案成功。freeze→candidate-only的正式Runner/Application集成只新增一次candidate run，比较状态pending_review。所有真实Provider实验都必须显式budget，HTTP hook逐attempt在发送前拒绝超额；明确工程失败停止后续case。

Synthetic经过importer/Canonical/SDK projection/Finalizer：after8不见M12推荐，after20见M12/M13，after40见M33补充；作者、精确书名、资源URL、跨日关系、空查询有明确GT。有消息却提交no_result时被拒绝；合法claims里的强负面仍依赖模型语义判断/真实review。fixture不保证模型会选更大窗，不替代第二层真实snapshot。

## Failure / Root cause记录

P01修改前四个true/2.0拒绝断言实际失败，因为SDK先coerce而typed input已经看不到原类型；补Field(strict=True, ge=1)后非法类型/正值17个契约断言全部通过。越限由既有Capability拒绝，真实error code为INVALID_ARGUMENT，首测试误写码已修正，拒绝/零retrieval断言保持。

开发脚本首个artifact serializer符号不存在，改用dataclass原结构与既有ReviewPacket；probe测试的事件名错误按collector的model.turn/started修正；candidate生成误用系统Python无法导入src布局，改uv后产物存在、原整串断言通过。这些属于明确工程错误与命令环境错误，没有fallback/retry/测试放宽或伪造通过。

## Accepted / 下一步

接受工程能力和P01确定性迁移的L0开发候选；**不接受为生产semantic-equivalent replacement**。下轮最小范围是context_before/context_after非负的真实SDK+Host承接，不改20/40展开选择策略；仍默认0 real API。只有廉价漏斗通过、准备发布一批候选时才fresh paired gate。

本轮工作已完成并提交；持续优化parent task保持in_progress，历史大改失败不转成完成，不归档其他任务。实际commit/push状态以本轮git输出为准。

最终文档收口后再次执行static CLI：**80 passed in2.05s**，Ruff/mypy通过，provider ledger为0/0/0；较P01的77多H02/H03三项测试。以上是有新增边界后的定向回归，不是重复付费或追加real cases。

## 连续小步 P02（0真实调用）

真实SDK复现18项失败后补齐lexical/legacy窗口的strict int/minimum=0。相关52项测试通过；含discussion/negative fixture，未调用LLM。候选仅删除60字符非负参数约束，production原文不动。旧frozen合同不可静默沿用新schema。

P02最终static：99 passed in1.90s；Ruff通过；mypy116文件通过；git diff --check通过。

P03：实际SDK复现7失败/5通过→修复后static111 passed in1.88s；Ruff/mypy116通过；0Provider/0tokens/0cost。dense默认40不变，候选只删43字符。
