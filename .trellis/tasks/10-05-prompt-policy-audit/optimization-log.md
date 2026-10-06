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
