# Prompt Optimization Log

当前唯一 baseline：production `9256550`（Prompt 与 `460259d` 相同）。旧失败候选留在 research，不覆盖。开发冻结结果使用完整 Prompt 原文 + commit / snapshot identity，不新增摘要算法。

## A00：当前责任与评估审计

- Commit：本节所属 `docs(prompt): map current responsibilities and low-cost validation gaps`。
- Changed rules / Responsibility moved：无；只读覆盖 P01–P92，动态事实 B01–B05。
- Static：位置覆盖 224/224、92 个 ID；已有 SDK/get_schema 实物核验。
- Synthetic / Real cases：无；Provider calls=0，tokens=0，cost=0。
- 当前 EvaluationRunner repetitions 默认 1，可冻结 snapshot；suite_tags 可复用但无 policy 命令；compare_evaluation_runs 可比较已存结果但没有完整 Prompt/snapshot/参数相等检查；没有 first-tool。
- 明确缺口：get_schema 多余参数未在 Schema 拒绝；非严格 int 会转换类型；cursor 重复未有跨轮 guard。
- Accepted：审计产物；不修改生产行为，不证明旧候选等价。

后续 H01/F01/P01 每轮单独补充；semantic diff 在提交前记录 Removed / Moved / Reworded / Added / Unchanged high-risk policy。

## H01：低成本 Evaluation 入口

- Commit：本节所属 `feat(eval): add budgeted prompt screening and frozen baseline reuse`。
- Changed rules：无。责任：实验编排归 Evaluation，首调用拦截只在显式 ScreeningRuntime 子类；继续走 Application.query/生产 SDK builder。
- Removed / Moved / Reworded：无 Prompt 文案变化。Added：static、first-tool、targeted、candidate-only、freeze-baseline、full-gate CLI；policy 复用 suite_tags；默认 repeat=1，额外 repeat 只允许单 case + 明确 borderline review/reason；明确 regression 0 调用返回 rejected。
- Static：26 tests passed（含7个新增 screening tests）；Ruff 通过；mypy 116 source files 通过；CLI help 通过。首调用 SDK 双选择均记录，0 Capability invocation、1 model turn；freeze→candidate-only 集成验证只新增1 candidate run，paired comparison 状态 pending_review。
- Synthetic：ScriptedModel，无真实语义评测；Real cases：0；Provider calls=0，tokens=0，cost=0。
- API 上限由 HTTP request hook 逐 attempt 强制；不得以 Query 次数代替 API 请求数。冻结条件包括完整 Base 原文、commit、query/scope/snapshot/provider/model/settings/budget/tool contract、Trace、answer/evidence/review packet/usage。
- Observed behavior：probe 有意产生 FirstToolProbeStop 的实验终态，结构状态不计完整答案成功；同轮多个选择都拦截。首个测试误用 model_input/turn_started 事件名，经 collector 实物确认改为 model.turn + started；未弱化1轮/0工具断言。CLI import 首次引用了不存在的 serializer，改用 dataclass 原结构和既有 review packet。
- Accepted：工程筛选能力；真实 Provider 端尚未运行，不宣称 semantic equivalence。full-gate 只生成 fresh pairs 与人工 review packet，不自动放行，也不自动修改 production。
- Unchanged high-risk policy：生产 SYSTEM_PROMPT 全字节未改。

## F01：小型 discussion / negative fixture

- Commit：本节所属 `test(prompt): add small discussion and negative evidence fixtures`。
- Changed rules / Responsibility moved：无；Added：41条人工可读消息 + 7种GT场景，8个真实SDK/Canonical/Finalizer测试。
- Static / Synthetic：8 passed；after=8不见推荐，after=20见M12/M13，after=40见M33；source_id到实际projection路径经过正式SDK；作者A/B区分。精确事实、URL清单、跨日顺序、空查询均由同一小snapshot验证。
- Real cases：0；Provider calls=0，tokens=0，cost=0。
- Observed behavior：有提问消息时，即使小窗没见推荐，no_result被Finalizer拒绝；合法claims中的强负面语义仍不能由Finalizer证明。fixture不会声称模型必然选20/40，更不更改默认8/8。
- Removed / Moved / Reworded：无；Unchanged high-risk policy：生产Prompt全字节不变。
- Accepted：廉价证据回归层；不替代真实frozen snapshot或release paired gate。

## P01：lexical limit 的确定性约束迁移候选

- Commit：本节所属 `refactor(prompt): move lexical limit validation into the tool contract`。
- Changed rules：仅P56的limit正整数/当前上限片段，104字符；候选20,346字符，production仍20,450。
- Responsibility moved：Base候选 → 已有Tool description/Schema与Host；先补SDK严格类型/正值。其余参数/全部高风险策略不动，全文相等测试防止无关改写。
- Static：static CLI 77 passed、Ruff通过、mypy116 source files通过；新增17项limit tests覆盖两adapter非法类型、非正值、Host上限、合法边界及整串候选diff。
- Reproduction：修改前true/2.0均进入retrieval，证明typed input之前发生SDK类型转换。修复只在原SDK参数字段加strict/ge；无临时分支。越限envelope现有代码是INVALID_ARGUMENT，最初测试误写错误码已按真实contract修正；未放宽拒绝/零retrieval断言。
- Candidate生成首命令用系统Python无法导入src布局，未产生candidate；测试显式FileNotFound。改用仓库uv环境生成后原断言全部通过，没有fallback。
- Synthetic：F01 8项一起通过；Real cases=0；Provider calls=0、tokens=0、cost=0。
- Observed behavior difference：原本非法JSON limit的隐式整数转换变为显式SDK错误；合法输入检索不变。production Base文字无变化。未测真实模型tool choice/answer差异。
- Accepted：确定性contract修复与L0候选；未通过release semantic gate，不直接替换production。全文Removed/Moved/Reworded/Added详见prompt-p01-semantic-diff.md。
- 下一轮：只验证context_before/context_after非负的真实SDK承接，不修改展开窗口选择或其他discussion prose；先补minimum/strict与必要契约，再独立候选。

## H02：导入既有Frozen Baseline，不重付API

- Commit：本节所属 `feat(eval): freeze recorded production prompt baselines without API calls`。
- Changed rules / Removed / Moved / Reworded：无；Added：显式历史baseline导入器，case与artifact复用现有contract，不建第二套Agent。
- Static：8 screening tests passed、Ruff通过；拒绝旧candidate测试通过。实际本地6/6 baseline snapshot/当前SDK工具描述与schema/model_settings/settings/原文条件一致预检通过，生产SDK只使用ScriptedModel构造、不执行query。
- Synthetic：H01集成freeze→candidate-only继续通过；Real cases executed=0。
- Frozen历史case：discussion/reply/github/fact/empty/recent。完整私有产物在ignored data/evaluation/prompt-frozen-20261006，历史请求/token只作为既有事实，不算本轮花费。首次明确导入snapshot、完整scope、路由、budget、provider/model、请求、Trace、evidence、answer与existing Evaluation snapshot。
- Provider calls=0、new tokens=0、new cost=0。
- Accepted：Development reuse；历史GT没有完整标注的case明确保持空reference，不能变成Holdout或release gate。
- Unchanged high-risk policy：全部生产Prompt文本不变。

## H03：评估入口收口

- Commit：本节所属 `fix(eval): restrict extra repeats to reviewed single candidates`。
- Policy scope：重复编排边界；Prompt lines affected=无；Risk=低；Deterministic owner=Evaluation；Expected/Maximum Provider calls=0/0。
- Removed / Moved / Reworded：无Prompt变化。Added：显式禁止full-gate/probe借candidate-extra重跑baseline；prior必须candidate_screen；baseline/candidate Prompt身份明确区分。
- Tests：新增CLI边界测试证明明确regression在构造Provider前0调用返回rejected；新增静态92规则/224行原文覆盖测试。完整工程回归697 passed in18.11s、Ruff通过、mypy116source files通过、Trellis context与diff检查通过。
- Observed behavior difference：防止误将追加candidate repeat应用到fresh baseline；不改变正式Agent执行。低成本CLI仍默认repeat=1/预算0。
- Synthetic/Real：全量测试均provider-free；没有追加真实case。Provider calls=0/tokens=0/cost=0。Accepted=是（工程边界）；无semantic release结论。
- Unchanged high-risk policy：全部原生产文本保留。

## 最终记录索引

| Iteration | Commit | 状态 |
| --- | --- | --- |
| A00 | 68311b5 | 当前责任审计接受 |
| H01 | 4f82408 | 低成本入口工程接受 |
| F01 | 1fbb87e | 小fixture接受 |
| P01 | e625b50 | strict limit contract接受；Prompt只接受L0候选 |
| H02 | 2521295 | 6个历史baseline开发复用接受 |
| H03 | 949c690 | 单候选追加repeat边界接受 |

最后一次static CLI为80 passed in2.05s，0Provider/0tokens/0cost（H03增加3项测试后分母由77更新）；全量工程回归仍为697 passed。Production Prompt未变化。真实语义接受/发布仍未执行，不沿用历史completed/finalizer统计。

## P02：lexical / legacy context非负契约

- Commit：本节所属`refactor(prompt): move lexical context bounds into the tool contract`。
- Scope：P57参数片段；Risk=低；Prompt lines=原L152；Owner=SDK严格解析/typed input；Expected/Maximum Provider calls=0/0。
- Removed：60字符；Moved：Base候选→Tool description/SDK/Host；Reworded=无；Added=两个strict/ge字段与候选逐步manifest测试。
- Reproduction：18项预期失败明确定位SDK转换与Schema minimum缺失；不放宽非法输入断言。环境没有python命令，改用python3；一次测试引用不存在的test_context_source.py未收集，改为实际test_context_source_contract.py。
- Static/Synthetic：52项相关测试通过，包含19项参数/候选检查及8项真实projection fixture；Ruff通过。最终static与mypy结果记validation。
- Real cases executed=0；Provider calls=0；new input/output/total tokens=0；cost=0。
- Observed difference：非法bool/string/float不再转整数；负数提前在SDK拒绝。合法0/20及默认2不变，20/40讨论政策逐字保留。
- Accepted：contract修复与L0候选接受；production正文不变，未通过semantic release gate。已有frozen tool schema变更后不能冒充同条件baseline。
- 下一轮自动进入P03：仅semantic dense_top_k正整数；其余semantic参数不顺手改。

## P03：semantic dense_top_k正整数

- Commit：本节所属`refactor(prompt): move dense candidate count into the tool contract`。
- Scope=P58:dense_top_k；Risk=低；Owner=SDK/typed input；Expected/Maximum calls=0/0。
- Removed=43字符；Moved=Base候选→严格字段/description/原Host校验；Reworded=无；Added=一个Field与12项契约测试。
- Reproduction=7 failed/5 passed，证明Host已有规则却无法看到SDK转换前类型；修改实现而非弱化测试。
- Static=111 passed in1.88s，Ruff/mypy116通过；Synthetic=既有8项fixture通过；Real cases=0。
- Provider=0；new input/output/total tokens=0；cost=0。非法类型/非正值提前拒绝；默认40及合法1不变。
- Accepted=contract与L0候选；production原文不变；高风险全部逐字保持。候选20,243字符。
- 下一轮自动进入P04：仅find_members.query非空字符串，不碰消歧、person routing或canonical identity策略。

## P04：find_members.query非空字符串

- Commit：本节所属`refactor(prompt): move member query validation into the tool contract`。
- Scope=P61:query；Risk=低；Owner=SDK/FindMembersInput；Expected/Maximum calls=0/0。
- Removed=36字符；Moved=Base候选→query Schema/Host；Reworded=无；Added=单字段minLength/description与6测试。
- Reproduction=2 failed/4 passed；原非法非字符串已拒绝，空白串原Host已拒绝。只补缺失的Schema/SDK空串检查，不新增正则。
- Static=117 passed in1.95s；Ruff/mypy116通过；Synthetic既有8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Observed difference：空串更早在SDK失败；合法用户名称规范化不变。消歧与canonical ID仍为原策略。
- Accepted=contract/L0候选；production正文不改；累计20,207字符。
- 下一轮自动进入P05：只迁移semantic_search.query非空字符串；不改semantic routing。

## P05：semantic query非空字符串

- Commit：本节所属`refactor(prompt): move semantic query validation into the tool contract`。
- Scope=P58:query；Risk=低；Owner=SDK/typed input；Expected/Maximum calls=0/0。
- Removed=57字符；Moved=Base候选→字段Schema/description/Host；Reworded=无；Added=单字段与6测试。
- Reproduction=2 failed/4 passed；缺失minLength，原Host空白检查保留。没有修改query文本、routing或其他参数。
- Static=123 passed in2.05s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Observed difference：空串提前显式SDK失败；合法query规范化不变。Accepted=contract/L0；生产Prompt保持原文，候选20,150字符。
- 下一轮自动进入P06：只处理get_schema额外参数被SDK忽略的实证缺口，不改SQL策略。

## P06：get_schema无参数真实执行

- Commit：本节所属`refactor(prompt): enforce the schema inspection no-argument contract`。
- Scope=P64；Risk=低；Owner=SDK Schema/入口；Expected/Maximum calls=0/0。
- Removed=35字符；Moved=Base候选→description/Schema/入口；Reworded=无；Added=空对象执行拒绝及4项测试。
- Reproduction=3 failed；额外table字段本来被忽略并执行，Schema缺additionalProperties。修改前{}和空串实测均ok。本轮只落实原无参数契约，不改SQL。
- Static初次mypy发现callback类型不符，修正为真实ToolContext后static127 passed in2.05s；Ruff/mypy116通过；Synthetic8项通过。
- Real=0；Provider=0；new input/output/total tokens=0；cost=0。未知参数现在显式失败，合法SDK wire forms保留。
- Accepted=contract/L0候选；生产原文不动；候选20,115字符。全部高风险策略字节及顺序不改。
- 下一轮自动进入P07：审计并迁移已经实际承接的lexical keyword单字符串约束，优先不改运行时代码。

## A01：修正责任矩阵错位，不修改Prompt或Runtime

- Commit：本节所属`docs(prompt): align responsibility rules with their actual clauses`。
- Scope=旧审计行范围与当前语义片段对应；Risk=低；Owner=matrix/static定位测试；Expected/Maximum calls=0/0。
- Root cause：P41–P71沿用旧审计行范围，总行覆盖虽通过却不能证明owner说明匹配实际语句。重定位真实锚点，保持P01–P92身份语义；历史commit不改写。P04正确Rule=P62:query（此前log/P04 commentary误标P61）；manifest更正。
- Reproduction：新删除片段定位检查对旧矩阵P01–P06全部MISMATCH。修正位置后发现P05依赖P03先删dense片段，测试必须按精确原片段顺序重建该句；曾strip导致保留空格，改为逐字replace，未更改任何candidate或非法参数断言。
- Removed/Moved/Reworded/Added：无Prompt变更；matrix更正实际Current wording/行范围/owner分类。撤回四处F，它们不是完整相同句子，不以literal dedup名义删除。SQL安全混合停止、作者和负面句加G保护。
- Static=127 passed；Ruff/mypy116通过；Synthetic既有8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Accepted=审计与检查修正。参数契约修复及候选精确文本不受影响；生产原文全字节保留。下一轮继续P07只验证keyword已承接的单字符串规则。

## P07：迁移已经实际承接的keyword单字符串

- Commit：本节所属`refactor(prompt): remove verified single-keyword parameter guidance`。
- Scope=P55:keyword；Risk=极低；Owner=已有SDK/typed input/Tool description；Expected/Maximum calls=0/0。
- Removed=36字符；Moved=Base候选→已有工具契约；Reworded=无；Added=14项契约测试；Runtime实现变化=无。
- Static=修改前14/14已经通过；最终static141 passed in2.14s；Ruff/mypy116通过；Synthetic8项通过。
- 非字符串原始值SDK拒绝且registry零调用，直接typed input也拒绝；合法anchor参数未变。无需增加未有依据的minLength或其他检索规则。
- Real=0；Provider=0；new input/output/total tokens=0；cost=0。Accepted=L0候选；production原文不动，候选20,079字符。
- 下一轮自动进入P08：只补lexical/legacy三个optional filter的非空数组契约，不改filter选择语义或scope。

## P08：lexical/legacy optional filter非空数组

- Commit：本节所属`refactor(prompt): move lexical filter array bounds into the tool contract`。
- Scope=P55:filters；Risk=低；Owner=SDK/typed input；Expected/Maximum calls=0/0。
- Removed=25字符；Moved=Base候选→三个filter minItems/已有description/Host；Reworded=无；Added=三个同类字段约束与29测试。
- Reproduction=8 failed/21 passed；SDK缺minItems，原typed input已拒绝空数组。首次编辑脚本class锚点遗漏继承声明，未修改源码；更正定位后修复主链路。
- Static=170 passed in1.87s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、new tokens=0、cost=0。
- Observed difference：空数组SDK更早失败；18种省略/null/合法数组传参保持相同。scope授权、canonical选择、query/time/limit不改。
- Accepted=contract/L0候选；production不改；候选20,054字符。
- 下一轮自动进入P09：仅find_members.session_ids非空数组契约，不修改身份消歧。

## P09：member session_ids非空数组

- Commit：本节所属`refactor(prompt): move member filter array bounds into the tool contract`。
- Scope=P62:session_ids；Risk=低；Owner=SDK/FindMembersInput；Expected/Maximum calls=0/0。
- Removed=29字符；Moved=Base候选→单字段minItems/description/Host；Reworded=无；Added=单字段与6测试。
- Reproduction：先修漏导入测试构造问题，再2 failed/4 passed；Schema缺minItems，Host原检查保持。不放宽非法输入断言。
- Static=176 passed；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、new tokens=0、cost=0。
- Observed difference：空数组在SDK更早失败；省略/null/合法数组保持，identity消歧、scope和query不变。
- Accepted=contract/L0候选；生产原文不动，候选20,025字符。
- 后续最小范围：独立审计recent.limit严格正整数，不改time_range/默认日期/cursor或recent选择策略；预算仍先定0。真实Prompt发布仍须fresh paired gate，不跳级。

## 本会话提交索引与收口

| Iteration | Commit | 结果 |
| --- | --- | --- |
| P02 | 03d928c | lexical context contract / L0候选接受 |
| P03 | 57ace57 | dense候选数 contract / L0接受 |
| P04 | 23f7648 | member query contract / L0接受；Rule修正P62 |
| P05 | 43047f2 | semantic query contract / L0接受 |
| P06 | ea35180 | get_schema无参数入口 / L0接受 |
| A01 | 936d7dc | 责任定位/分类根因修正接受 |
| P07 | 1ea1b8a | keyword现有承接验证 / L0接受；无Runtime改动 |
| P08 | 7a64694 | lexical filter空数组 / L0接受 |
| P09 | 40acc6a | member filter空数组 / L0接受 |

本会话8轮Prompt参数候选 + A01审计修正各自提交；完整工程793 passed in17.81s、static176、Ruff/mypy116/diff检查通过。Provider=0、input/output/total tokens=0、cost=0。六个历史baseline因新SDK合同按预期拒绝，未改历史证据、未付费重跑。生产SYSTEM_PROMPT全字节不变；L0接受不等于语义发布接受。当前任务保持进行中，后续recent.limit可独立零成本审计，仍不动时间语义与cursor。

## P10：recent.limit严格正整数

- Commit：本节所属`refactor(prompt): move recent limit validation into the tool contract`。
- Scope=P66:limit；Risk=低；Owner=SDK/Capability；Expected/Maximum Provider calls=0/0。
- Removed=62字符；Moved=Base候选→原description/Schema/Host及新增strict解析；Reworded=无；Added=单字段strict/ge与14 tests。
- Reproduction=5 failed/9 passed；非严格SDK转换原始类型，Host正整数/上界既有拒绝未改。
- Static=190 passed in1.84s，Ruff/mypy116通过；Synthetic既有8项通过；Real=0；Provider=0、new tokens=0、cost=0。
- Observed difference：非法原类型更早失败；合法limit/省略值保持，default archive_latest两天、时间互斥/cursor未改。
- Accepted=contract/L0候选；生产Prompt原文不变，累计19,963字符。下一轮自动进入P11，只审计显式context工具的窗口合法性，不改选窗策略。

## P11：显式context窗口的参数合法性

- Commit：本节所属`refactor(prompt): move explicit context bounds into the tool contract`。
- Scope=P61；Risk=低；Owner=SDK/GetMessageContextInput；Expected/Maximum calls=0/0。
- Removed=60字符；Moved=Base候选→SDK非负整数+Host共享总量上界；Reworded=无；Added=两个strict/ge字段、14 tests。
- Reproduction=11 failed/3 passed；原SDK转换输入、Schema缺minimum，Host总量正确。合法默认8/8、0/20、0/40及transport边界保持，不新增单侧max。
- Static=204 passed in1.90s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Accepted=contract/L0；生产原文保留，候选19,903字符。选窗description和所有discussion/negative/time/stop/routing字节不改。
- 下一轮自动P12：只验证身份恰一参数的既有Host执行和可见字段description；不改变canonical ID/锚点选择。

## P12：验证已承接的身份恰一参数

- Commit：本节所属`refactor(prompt): remove host-enforced context identity cardinality guidance`。
- Scope=P60:cardinality；Risk=低；Owner=现有SDK函数体Host guard；Expected/Maximum calls=0/0。
- Removed=40字符；Moved=Base候选→既有Host guard/Tool字段description；Reworded=无；Added=5 tests；Runtime/Schema结构未改。
- Formal Schema无oneOf的事实保留；不以两个optional字段推定互斥。实际Host明确拒绝零/双身份且registry零调用，工具及字段description仍提供同一可见要求。
- 首次真实projection测试call ID未更新导致source handle重复；修测试调用元信息，保持原resolver断言，没有产品兼容补丁。四种合法单身份/null形式成功。
- Static=209 passed in2.37s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Accepted=已有Host承接验证/L0候选；生产原文不动，累计19,863字符。下一轮自动P13，只审计SQL参数形状与max_rows类型，不碰SQL routing/error stopping。

## P13：SQL参数形状及optional max_rows

- Commit：本节所属`refactor(prompt): move SQL parameter validation into the tool contract`。
- Scope=P63:parameters；Risk=低；Owner=SDK/ExecuteSQLInput/Capability；Expected/Maximum calls=0/0。
- Removed=45字符；Moved=Base候选→单字符串既有SDK及max_rows strict/ge；Reworded=无；Added=18 tests，static包含原SQL主链路7 tests。
- Reproduction=9 failed/9 passed；SDK转换原始值，nullable整数分支缺minimum。补单字段strict/ge，不改变sql/Scope/read-only解析。
- Static=234 passed in2.80s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- Accepted=contract/L0候选；生产原文不动，累计19,818字符；null/省略/合法cap保留，真实超界零repository调用。
- 下一轮自动P14：只验证已有SQLite单语句执行拒绝，不改SQL路由、schema调查或error stopping。

## P14：SQL单语句既有driver承接

- Commit：本节所属`refactor(prompt): remove driver-enforced single-statement guidance`。
- Scope=P63:single_statement；Risk=低；Owner=SQLite driver/既有SQL错误映射；Expected/Maximum calls=0/0。
- Removed=26字符；Moved=Base候选→既有driver/Tool description；Reworded=无；Added=3 tests；Runtime变化=无。
- Static=237 passed in2.14s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- 两条语句真实SDK返回SQL_MALFORMED且数据不变；合法分号原生解析保留。不删hidden schema，不加分号特殊规则。
- Accepted=已有确定性承接/L0候选；生产原文不动，累计19,792字符。自动继续审计SQL写入/DDL的实际拒绝，不触及其余安全/语义策略。

## P15：SQL写入与DDL的既有确定性承接

- Commit：本节所属`refactor(prompt): remove host-enforced SQL write restrictions`。
- Scope=P39:write_ddl（commentary旧P44误标已纠正）；Risk=低机械片段；Owner=原SQLite authorizer/read-only connection；Expected/Maximum calls=0/0。
- Removed=16字符；Moved=Base候选→已有Host/Tool description；Reworded=无；Added=2 tests；Runtime变化=无。
- Static=239 passed in2.08s；Ruff/mypy116通过；Synthetic8项通过；Real=0；Provider=0、tokens=0、cost=0。
- DELETE/CREATE实际SDK拒绝；fixture count与实际sqlite_master证明未写入/建表，不以public schema可见性替代物理状态检查。
- Accepted=已有确定性承接/L0候选；production不动，累计19,776字符；不更改其余安全/Scope/LIMIT/停止指导。
- 自动继续责任矩阵承接状态更新及低成本Harness审查；不存在literal duplicate可顺便去重，不强行生成语义候选。

## A02：承接状态同步

- Scope=矩阵P39/P60/P61/P63/P66与紧凑契约摘要；Risk=文档低；Prompt变化=无；Provider预计/最多=0/0。
- 同步P10–P15实际SDK/Host owner与L0状态，保留Current wording、Rule ID、行范围、其余高风险政策，不把局部承接写成整条可删。
- 正式Schema无oneOf、默认8/8与20/40、unknown schema/时间/停止依然模型负责；旧frozen工具合同不可沿用事实保留。
- Accepted=审计状态更新；0Provider/0tokens/0cost。

## A03：矩阵列完整性根因修复

- Scope=A02 P39更新脚本丢失行尾分隔符；Risk=文档低；Provider预计/最多=0/0。
- 新10列断言复现1 failed，修复唯一行尾；不放宽引用/owner/预算断言。原测试只核对非空字段，未发现Provider预算列被解析器丢弃。
- Prompt/Runtime变化=无；修复后责任定位与全列通过。Accepted=文档/检查修复；Provider/tokens/cost=0。

## H04：冻结条件漂移诊断

- Commit：本节所属`fix(evaluation): identify drifted frozen baseline conditions`。
- Scope=verify_frozen_baseline失败信息；Risk=低离线；Prompt变化=无；Owner=screening条件比较；Expected/Maximum calls=0/0。
- 复现1 failed：既有拒绝只能报drifted，无法定位本批实际tool_contract漂移。现在列出变化的顶层字段，如tool_budget/tool_contract；条件精确相等要求不变，不打印完整条件值、不重绑历史合同。
- Static240 passed in2.46s；Ruff/mypy116通过；新增实证诊断断言，原完全相等合法路径保持。
- Accepted=诊断改进；Real=0；Provider=0、tokens=0、cost=0。旧frozen仍不可冒充当前SDK baseline。

## H05：first-tool实证usage丢失的最小修复

- Commit：本节所属`fix(evaluation): retain SDK usage before decision probe stops`。
- Scope=probe telemetry；Risk=低离线实验；Prompt/production Runtime变化=无；Owner=SDK ToolContext.usage/原数字投影；Expected/Maximum新calls=0/0。
- Failure Case=V01 baseline首轮确实1 HTTP请求/2 tool选择/0 Host，但Runner终止后EvaluationRun/Trace无usage；模型hook待发事件未排空。未知不能记0，也不付费重跑补数。
- 拦截时保存SDK已更新usage，按原adapter投影；两个同轮call保存同一aggregate而不相加，新run清空。artifact新增probe_usage/source，原canonical Trace/Run失败终态不变，公开工具选择仍由probe_calls保留。
- ScriptedModel明确100 input/20 output/120 total/17 cached，先复现缺字段失败；SDK默认cached=0与新版InputTokensDetails必填cache_write_tokens按真实结构显式构造fixture，没有放宽token断言或产品补丁。
- Static240 passed in2.29s；Ruff/mypy116通过；本修复新Provider=0，fixture数字不计真实tokens。Accepted=成本观测修复；V01已发生1请求的usage仍unknown。
