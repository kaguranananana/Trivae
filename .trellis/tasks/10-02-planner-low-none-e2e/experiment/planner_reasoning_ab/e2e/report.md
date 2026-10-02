# Planner low vs none：targeted production E2E 实验报告

本轮第一阶段已完整执行并停止在 **Gate A**：在 8 个 exposed Development Case 的配对观察中，`none` 臂有 **2 条实质最终质量回退**（Archify star 叙述矛盾、30 天总结的昵称/消息内容与来源错配），同时有 3 条质量改善、3 条相同。不存在普遍单向优势。**这些是真实 E2E 输出差异，不是 Plan 文本评分；单次配对仍不足以证明它们由 Planner semantic difference 稳定、因果性地产生。** 本轮没有改生产配置、没有追加第二阶段或全量 Development。

后续独立的 [4 次冻结 Plan 重放](../../../../10-02-archify-frozen-plan-replay/experiment/report.md) 已完成，未重现 Archify 原 none 的两处错误，观察到同 guidance 下的下游方差；不更改本报告的原始分母、盲审或 Gate A。后续 HTTP 原始参数核验也补充了归因：下文“canonical calls”指 normalized Trace 参数；模型实际恢复时传入 source_id，由既有 SDK resolver 映射为 canonical message_id，并非模型自行生成该 ID。

## 1. Experiment identity

| 项 | 事实 |
| --- | --- |
| Execution commit | `e75b34711daf4c8c1825dedfa219a501a8cf154b` |
| 工作树 | 起点 clean；执行时 dirty，仅本轮新 runner/tests/task 工件。未提交 runner 逐字保存在 `frozen/`；commit 本身不包含它，不能冒充 clean committed execution。 |
| Snapshot | `snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 473236}` |
| Semantic identity | Qwen/Qwen3-Embedding-0.6B，1024-d，last_token，normalized；completed，473236 indexed messages、54267 chunks |
| Provider/model | 官方 DeepSeek，`deepseek-flash` |
| 时间 | 2026-10-02，Asia/Shanghai；manifest 15:27:37 +08:00，逐 run 起止 UTC timestamp 原样保存 |
| Cases | 固定 8 个暴露 Development Case；未读/生成/运行真实 Holdout，未加入 Calibration |
| Treatments | Planner `low` / `none`；Runtime 两侧均保持生产 registry `low` |
| 运行规模 | 16 logical E2E runs；每 case/treatment 一次；63 actual Provider HTTP requests = 16 Planner + 47 downstream |
| 重试/timeout | 自动 Provider retry 0；timeout 0；没有失败替换或补跑 |
| 顺序 | seed=20261002；按 Case 配对、交替 AB/BA，实际顺序在 `run_order.json` |
| 生产入口 | EvaluationRunner → TrivaeApplication.query → 现有 forced planned override → 生产 SoftPlanner / 同一 Runtime / Tool / Retrieval / Finalizer |

当前生产源码在本轮前已经默认使用官方 DeepSeek Flash Planner `none`。本轮重建 low/none 对照，没有实施新的“生产切换”。因此最终结论是对这一配置的 E2E 证据审查，不能误写成此次完成了一次配置发布。

## 2. Isolation verification

`preflight.json` 在任何真实请求前通过实际 SDK serializer 的 provider-free 检查，明确记录：

> treatment request 的唯一预期语义差异是 reasoning_effort

两侧一致的字段包括：每 case 的 P1 canonical prompt 全文、messages、capability metadata、case payload、allowlist、实际 SDK tool schemas、Provider/model、Planner timeout=20s、max_tokens=2048、temperature=0、JSON response format、生产源码、Snapshot、Evaluation contract、Runtime max_turns=8 / max_tool_rounds=3 / max_output_tokens=16384、debug capture profile 和 forced planned route。

本轮继承当前 EvaluationRunner 的 snapshot metadata 输入，动态段与此前 Planner-only compact snapshot 不同；P1 builder/template 未变，两侧全文一致。本轮不把两种实验的动态输入冒充逐字相同。历史 Planner-only prompt 相同的事实也已独立复核。

执行后 `analysis.json.isolation` 对 **8 组实际 Planner HTTP bodies** 再次逐字段比较：唯一差异都是 reasoning_effort；每组首个 downstream request 的非 messages 参数/schema 完全相同。后续 Plan guidance、Tool history、工具预算耗尽状态是生产执行结果的中介变量，不能误判为预设 treatment contamination。request/run/conversation IDs 每次独立生成，模型输入不含 low/none 标签。

没有观察到代码、canonical Snapshot、Case 或预设参数污染。全部源文件/runner/bundles/manifest/lock 的冻结副本已在运行前后逐字核对。独立 conversation/trace/evaluation DB 保留 16 runs、16 results、16 terminal traces、700 events；HTTP ledger 保留 63 requests 和 63 responses，Trace model-turn=47 与 downstream 请求数一致。

Cache 边界：每 run 新 conversation，没有检索结果 cache；本地 embedding 在首个正式请求前使用既有 preload 预热（50.37s，不计入任何 treatment latency）。Provider prefix cache 保留生产语义并记录实际 hit/miss，无法宣称关闭/完全隔离。AB/BA counterbalance 只能减小顺序偏差，小样本 latency 仍包含此限制。

## 3. E2E success

| treatment | successful E2E | failed E2E | valid Planner | Planner length | 含工具失败的 runs（calls） | answer/finalizer failure |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low | 8/8 | 0 | 6/8 | 2 | 1（2） | 0 |
| none | 8/8 | 0 | 8/8 | 0 | 2（3） | 0 |

Finalizer contract/provenance validation 全部通过；这只证明结构、scope 和 current-run 引用可解析，不证明所有引用在语义上支持陈述。**16/16 completion 不能掩盖下述事实/引用回退。** low 的两个 Planner failures 都原样留在分母，生产按现有契约跳过 guidance 后继续 Runtime。

## 4. Final quality comparison：先盲审、后揭盲

独立 reviewer 只读取 `blind/packet.json`，未获得 treatment、reasoning effort、latency、usage 或运行顺序。8 组判断完整写入 `judgments.json` 后才读取 mapping；原始判断字节复制到 `judgments.frozen.json`，揭盲后保持相等。`reveal.json` 记录完成与揭盲时间。

Reviewer source 是 **独立 AI assistant，不是 human adjudication**。按仓库路由显式请求 GPT-5.6 Luna / max；collaboration 返回创建成功但未提供 resolved model 身份，因此仅记录 requested routing，不声称已验证实际子代理模型。

| Case | Blind result | Reveal | correctness / Evidence / Citation | none meaningful regression? |
| --- | --- | --- | --- | --- |
| pu-dependent-mattpocock | A better | none | 双侧标注 Evidence 1/2、required context 0/1；none 更准确区分第一人称“离不开”自述与缺少可核查案例，且补充受支持的反馈细节 | 否，none 更好；共同标注 miss 保留 |
| dev-context-archify | B better | none | none Evidence 2/2、context 1/1；low 1/2、0/1，漏掉“好用”回复并错误概括没有实际反馈 | 否，none 更好 |
| pu-aggregate-utc-types | same | same | 两侧 text=814、reply=17；expected facts 2/2，完整分组与 UTC 边界一致 | 否 |
| dev-zero-empty-3 | same | same | 两侧 complete 空窗、verified zero 1/1；没有把 error/partial 当零 | 否 |
| dev-temporal-30d | A better | low | 时间窗/partial/truncated 两侧正确，但 none 把作者昵称当消息并归错群；额外 narrative citation 覆盖不足 | **是：Answer/Evidence support 回退** |
| dev-lexical-forge | B better | none | 目标实体和 fact 两侧正确；none 标注 Evidence 3/3、low 2/3；none 明确排除 Minecraft Forge 同名噪声 | 否，none 更好 |
| dev-cite-archify | A better | low | 两侧标注 Evidence 3/3、fact 1/1；none 同时报告7k/9.5k又称9.5k是唯一数值 star 提及，自相矛盾，并把无回复关系的前置消息写成反应 | **是：factual scope / citation entailment 回退** |
| pu-rank-utc-session | same | same | 两侧返回 qq:677019167=224、完整6会话排序，expected facts 2/2；固定最高值没有并列 | 否；真实最高值 tie 情形未验证 |

总计：none better=3、low better=2、same=3、unjudgeable=0。不将胜负次数压成总分；两条实质回退足以触发本轮停止条件 A，即使其它 Case 有改善。

现有自动指标能记录 expected fact alias coverage、标注 Evidence recall、required context、coverage/truncation、verified/false zero 等。没有新增假冒 corpus-exhaustive correctness 或 numeric citation precision。partial GT 的 dependent/context Case 只能报告标注目标的 coverage；temporal Case 没有完整主题 GT，不能宣称主题 recall 被证明。

### Reviewer assertion 的独立核验

盲审称 temporal 的“北京”没有支持。完整 ToolResult 中实际存在 `qq:383550736:7674313223535742517`，作者楚玉衡、消息正文“北京”；该条未进入对应选中 Evidence/Citation。故这里是 **citation completeness miss，不是捏造城市**。原始 judgment 不改，核验在 `failure-attribution.json` 单列。

另一个错误确实存在：`qq:750807478:7674452358376375863` 是识海群的图片消息，正文不是“天天只会调 api”；这段文字来自 sender_name。none 把它写成就业群里的消息与焦虑陈述，属于字段与来源错配，不是 Provider transient 或 GT 误报。

## 5. Tool / Retrieval behavior

| treatment | tool calls | retrieval calls（含 structured SQL） | failed calls | partial calls | semantic calls | model projection truncation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low | 18 | 16 | 2 | 2 | 0 | 0 |
| none | 21 | 18 | 3 | 1 | 0 | 0 |

### pu-dependent-mattpocock

low：lexical mattpocock → lexical skills → 两个 canonical context anchors；none：lexical mattpocock → 两次错误 m1-* anchor → 两次 canonical context。两侧实际有效 context 都是两次，**没有复现 low 重复 context 的假设**。low 的额外 skills 检索新增96条消息、与最终 Evidence 有2条交集；不能只凭多调用就判 redundant。none 的两次 alias error 是真实失败，后续 canonical calls 是 Agent 明确恢复，不是 client retry。

low 检索165条、选12个 unique Evidence message；none 检索85条、选15个；两侧共同遗漏标注 context `qq:677019167:7664449865363143925`。更多检索不等于更多有效证据。none Plan hint 中出现 semantic，但 Runtime 实际没有调用。

### dev-context-archify

两侧 Plan 目标相近，真实分歧出现在 Runtime context anchor：none 扩展原始分享 `qq:1039179741:7665652181386089161`，取得“好用”；low 恢复 alias 错误后扩展了较晚的9.5k/插件公告，漏掉该反馈。由此出现 Evidence 2/2 vs1/2 和 Answer 的有正面反馈 vs无实际反馈。能定位 **run-level cause 为 anchor selection**，但一次配对不能证明由 Plan 某句话稳定驱动。

### dev-lexical-forge

none 实际 Plan 已以 forge lexical 为主；low 本次 Planner length，未获得可比较的有效 Plan。两侧都只做一次 lexical，没有 semantic/context 调用。none lexical 查询 `forge` 取得17条，low 精确 `AnHuoZhe/forge` 取得5条；none 区分同名 Minecraft 命中并覆盖3个标注分享。**本次不是有效 low/none Plan 对 conditional retrieval 的直接比较，不能把低侧 skip 后的行为误写成 low Plan 被执行。** 没有观察到机械 semantic fallback、错误 Forge disambiguation 或 harmful semantic Evidence。

### dev-cite-archify

low Plan 将项目发展/star查询/上下文拆成3步，none 合为2步且 hint lexical+semantic。但实际都只做 lexical+context，semantic 均未调用；low 也没有把 Plan 的第二次 lexical 当工作流执行。

low 两次 Tool calls，context 6+6；none 三次 calls（包含 m1-1 alias failure），恢复后的 context 6+10。none 比 low 多取4条消息，但所有3个 GT目标两侧都已命中；两侧9个 unique Evidence messages 中8个相同，none 选择了较早“真的假的”替代 low 的另一个后续消息。该“真的假的”比9.5k通告早596秒、无 reply relation，不能仅由邻近证明其为项目反应。

额外 context 会增加覆盖，但不能自动判 harmful；本次可证明的 harmful 结果是 **最终引用关系与唯一数值提及的错误陈述**，不应归为多一次 semantic 调用，因为真实 Trace 根本没有 semantic。

### Control / ranking / zero / temporal

- 聚合 SQL 两侧同 `[1786752000000,1786838400000)` GROUP BY message_type；none 多 ORDER BY n DESC，只有 row order 差异，事实/coverage 未变。无实质 control contamination 信号。
- Ranking 两侧同 UTC 窗口、降序 GROUP BY session_id；none LIMIT10、low无显式LIMIT，但只有6个会话，返回全集一致。Plan none 没写 tie，最终没有漏本 Case 第一名；**没有真实并列最高值，不能证明 tie completeness**。
- Zero 两侧同 `[1756166400000,1756252800000)`，同一次 recent Tool，complete、eligible=0、无 error；不用 SQL count 假冒零证明。
- Temporal 两侧 recent 参数完全相同：30d、archive_latest、limit100；resolved `[1784255688000,1786847688001)`，实际 message ID 集合完全相同（100/73863）。none 后续 schema+两次全窗口 SQL 带来会话与每日计数，是新增有效结构化信息，**不是重复检索**；内容 coverage 仍partial，未完成全窗主题阅读。回退出现在 Evidence selection / Answer synthesis，而非时间解析或 missing retrieved messages。

自动分析只输出 exact duplicate arguments / no-new-message **候选**：本轮没有 exact duplicate arguments；有效消息调用均取得新增消息。没有基于调用次数给出未经依据的 redundant/unnecessary semantic/lexical 判定。

## 6. Performance / Cost proxy

| treatment | mean E2E | median E2E | input | output（包含reasoning） | total reasoning | cached input | total tokens | Provider requests |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| low | 16.837s | 16.728s | 263832 | 23114 | 15165 | 170496 | 286946 | 30 |
| none | 11.011s | 9.351s | 287500 | 12701 | **unknown** | 175360 | 300201 | 33 |

| treatment/stage | mean Planner | median Planner | Planner input/output | Planner reasoning | downstream input/output/total |
| --- | ---: | ---: | --- | --- | --- |
| low | 8.217s | 8.125s | 10516 / 12890 | 11363 | 253316 / 10224 / 263540 |
| none | 1.342s | 1.363s | 10316 / 1376 | **unknown（8/8未返回）** | 277184 / 11325 / 288509 |

none 平均 E2E 下降约34.6%，Planner平均下降约83.7%，Planner completion tokens 下降约89.3%。但 E2E input 增加约9.0%，overall total 增加 **4.6%**，Provider requests 多3次；因此 **不保持整体 token效率优势**。E2E completion 两侧8/8，没有观察到 E2E reliability优势；优势只在 Planner validity 8/8 vs6/8。

none downstream 的 reasoning 实际观察到4155，Planner全部缺失，所以整体仍unknown，不能把4155写成完整total，也不能把缺失写0。reasoning 已包含于 Provider completion tokens，cached input 是 input 的子集，均不再重复相加。每次 usage 原文、最后一次 Answer-generation HTTP latency、Planner/tool/E2E latency 均在 raw/analysis 中保存。

**Monetary cost unavailable**。没有金额估算，没有从 token count 伪造人民币成本。

### Input usage 差200 tokens 的调查

历史与本轮都为每 pair low 比 none 多25 input tokens，总计200；本轮8次 Planner每侧cached input均384，共3072（历史各1024）。实际 serialized request 的 messages/content 相同，只有 effort不同，SDK没有加第二套显式prompt/responseformat。因此不能归为application prompt或cache hit数量差异。

当前只能记录 **unresolved provider usage accounting difference**。thinking模式的隐式server模板或usage accounting是可能解释，SDK与raw response没有给出可确定的内部机制；不猜测、不阻塞E2E。

## 7. Failure attribution

| 失败/限制 | 数量或 Case | 归因 | 影响 |
| --- | --- | --- | --- |
| Planner provider_length | low temporal、forge（2） | Provider reasoning消耗2048 completion预算；temporal reasoning=2048、forge=1884 | 两次Plan无效，显式skip；E2E仍完成 |
| Planner parse/router/provider transient/timeout | 0 | 未观察到 | 不制造算法失败 |
| Tool execution failure | low context2；none dependent2/cite1 | m1-* alias当canonical ID，MESSAGE_NOT_FOUND | 真实失败calls和额外模型回合；不是自动retry；双侧都有，不能定为none独有缺陷 |
| none Answer/citation quality | cite、temporal（2 Cases） | 叙述内部矛盾、metadata/content与来源错配；语义支持验证不足 | 自动结构/provenance检查仍通过；主质量回退 |
| low Answer quality | context-archify | context anchor选择遗漏“好用” | 错误无反馈结论；none较好 |
| shared marked-context miss | dependent双方 | 标注目标没有进入检索/最终Evidence | target recall1/2，GT partial；不推断全部答案错误 |
| Coverage incomplete | temporal双方 | 生产bounded最近100条，不是全窗内容阅读 | 如实partial/truncated；不误写成完整coverage |
| Evaluation harness error during formal runs | 0 | 16 runs/results/traces/ledgers完整对齐 | 无丢失attempt |
| 首次启动环境失败 | 首个正式attempt之前 | 缺少已有semantic extra，按不变lock补齐 | 0 logical attempts、0 Provider requests，单独保留原启动目录 |

未修复或调参以上生产失败，未把修复后的成功混进实验。Raw、Trace、选中Evidence、最终Answer与指标都可按run/traceID重建 `Query → Planner → Tools → Evidence → Answer → Evaluation`。

## 8. Final judgment 与最小下一步

**两条 none 臂差异已经进入生产最终质量：不是总体漏检索，而是最终事实范围、Evidence selection 与Citation支持出现错误。** 这足以触发A gate，不能直接依据本轮支持配置切换/质量等价。它也不意味着none普遍更差：context、dependent、Forge有改善，另外三个control一致。

1. **none的Planner差异有没有真正影响E2E质量？** 观察到2条none臂最终质量回退，3条改善；完整链路表明结果差异进入Tools/Evidence/Answer。但“Planner具体语义差异稳定导致回退”仍未证明；temporal低侧甚至没有有效Plan。
2. **哪些只是看起来不同？** 聚合SQL ORDER BY、ranking Plan没写tie但实际全集正确、zero Plan不同但同一完整空窗；cite/其它Plan含semantic hint但Runtime不执行。Forge low Plan失败，不能作有效Plan间的conditional比较。
3. **哪些真的传导？** context anchor变化改变“好用”Evidence与反馈结论；Forge lexical范围改变标注Evidence与消歧；temporal额外SQL改变结构化Evidence和Answer内容但不扩大正文coverage；cite context范围/引用选择不同并产生叙述错误。Tool alias failures与额外Provider turns也真实记录。
4. **效率优势是否保持？** Planner和E2E latency保持，Planner validity保持；E2E completion打平；整体tokens和request数量没有优势，反而增加。
5. **是否足以支持生产切换？** 不足。本轮前生产已经默认none，此次未修改；本轮不能作为该配置的质量背书，也不自动切回low。配置决策需要单独处理这些证据。
6. **缺的最小实验？** 后续单独任务先做 **dev-cite-archify的4次冻结Plan生产Runtime replay**：用本轮已保存的有效low/none Plan作为两个guidance treatment，每侧2次新conversation、相同snapshot/参数、counterbalanced；不重新调用Planner、不改prompt或retrieval。这能区分“分步/合并guidance稳定改变引用选择”与“同guidance下Answerer随机错配”，直接检验最明确的star矛盾/前置反应问题。它只回答局部因果性；若以后需要恢复广泛质量背书，再按独立Gate做exposed Development确认。当前任务不执行这个后续实验，不自动跑37×2，也不靠补跑刷成功率。

## 9. Reproduction / Artifact map

- `manifest.json` / `preflight.json` / `run_order.json` / `variants.json`：冻结身份、单变量machine diff和顺序。
- `attempts.jsonl` / `runs.jsonl`：全部16条logical attempts/results，无替换。
- `raw/provider_requests.jsonl` / `provider_responses.jsonl`：全部63条HTTP请求/公开响应、usage、finish；隐藏reasoning正文不归档。
- `raw/{case}-{treatment}-a1.json`：逐run完整公开Planner、Runtime ToolResult、Answer和自动评测。
- `traces/` / `trace.sqlite3`：canonical700events、16terminaltraces；debug既有capture bounds保持。
- `answers/` / `evaluation/` / `evaluation.sqlite3`：原始AnswerArtifact、逐case自动指标、16runs/results。
- `blind/packet.json` / `judgments.json` / `judgments.frozen.json` / `mapping.sealed.json` / `reveal.json`：盲包→全部原始判断→揭盲。
- `analysis.json` / `interpretation.json` / `failure-attribution.json`：分层指标、人工解释、失败聚类与reviewer核验。
- `frozen/` / `execution.diff`：执行时源码/runner/case/lock逐字副本；execution.diff为空是因为新增runner当时untracked，不能只靠该diff复现。
- 同级 `startup-environment-failure/`：依赖检查失败，0Provider请求；原始工件不删除。

Provider-free重算：先运行 task 的 `analyze_e2e.py <e2e-dir>`，再运行 `finalize_analysis.py <e2e-dir>`；后者只合并冻结盲审与明确标注的人工interpretation，不修改judgments。重新真实实验必须使用全新output路径，显式单次命令；当前报告不授权补跑。

## 10. Validation / engineering evidence

运行前：相关Evaluation/Query/Evidence/Application回归通过；新增runner tests通过；Ruff、mypy、diffcheck通过。最终运行后：**pytest641passed**、`ruff check src tests`及新增runner/analyzer通过，`mypy src`通过（115files），`git diff --check`通过。源码/数据冻结相等、actualHTTP与normalizedmodelturn计数匹配、全部judgments揭盲前完成且揭盲后未修改。

工程动机是把 Planner 语义疑点验证到真实业务层。设计复用既有 EvaluationRunner 和生产 injection；新增 HTTP 观测是因为 model-turn 不能单独证明真实 transport attempt 数。没有另建 Agent 或混合总分。两次 length、五次 alias errors、两条 none 语义回退均可定位到 raw/Trace。规模仅 16 runs、63 requests，不外推金额、全量质量或 tie 场景。实验代码负责注入和观测，生产负责 Tool/Finalizer 契约；本轮未当场修复生产 bug。下一步是冻结 Plan 的局部 replay，以区分因果与方差。

可核验的技术事实是：“Planner 更快不意味着 E2E 更省 tokens”“provenance 校验通过不等于语义支持正确”“昵称和消息正文混淆能绕过结构检查”“先独立盲审、后揭盲，并核对 reviewer 的具体断言”。这些 Development 观察不能包装成普遍质量保证。
