# Runtime Prompt Policy Audit

审计日期：2026-10-05。基线：`460259d`。范围：Runtime Prompt 与其实际承接层；不修改运行行为。本报告中的迁移标签表示建议的职责归属，不表示迁移已实现。

## 结论

`SYSTEM_PROMPT` 实测 **20,450 字符**，与用户材料一致。问题确实是职责混合和重复；不能据此推导字符数与答案质量的因果关系。建议先按稳定策略分层并合并重复，随后单独验证机械契约的下沉。

有五个不能直接套用用户材料中的理想方案的现状：

1. 当前只有 JSON mode，未向 Provider 提供最终 claims/no_result Schema。不能删掉输出结构后假定 API 会强制字段和 enum。
2. SDK 工具使用 `strict_mode=False`；limit 等部分约束存在于 Schema，但非空字符串、非负 context、身份互斥等主要在 Host。参数类型正确也不代表身份或工具选择正确。
3. “limit 不超过最大值”是契约；“清单用最大值”是召回策略。Schema 的 maximum 无法强制模型选择最大值。
4. Finalizer 校验 handle、scope、provenance 和结构；没有对任意正文做作者归属、时间关系、推荐/使用语义或穷尽负面结论判定。这些策略不能整段下沉。
5. 重复工具/游标调用的停止规则主要依靠模型指导；现有 Runtime 预算不等于跨回合的语义去重机制。不能把拟议中的去重 guard 写成既有保障。

## 来源索引

以下链接使用仓库相对路径，行号对应本次基线。后续改行后以符号和基线 commit 重建，不能将本报告的行号当成永久契约。

| 编号 | 来源 | 本次核对的职责 |
| --- | --- | --- |
| P | [prompt.py](../../../../src/trivae/query/runtime/prompt.py) | L7–230 为被审计字符串；L1–6 注释、L231 结束符不属于 Policy |
| T | [openai_tools.py](../../../../src/trivae/query/runtime/openai_tools.py) | 各 SDK adapter 的 description、真实 params_json_schema、source 解析；context L552 起、limit L285/L444/L984/L1152 附近 |
| C | [contracts.py](../../../../src/trivae/capabilities/contracts.py) | typed input 的非空、非负、time_range 互斥、cursor/filter 一致性与 context 总量约束 |
| S | [scope.py](../../../../src/trivae/capabilities/scope.py) | trusted filter 和 archive_latest 相对时间解析 |
| R | [recent_messages.py](../../../../src/trivae/capabilities/recent_messages.py) | Host 时间事实、默认范围、cursor 的时间事实重建 |
| X | [get_message_context.py](../../../../src/trivae/capabilities/get_message_context.py) | canonical anchor 与同会话、trusted scope 的邻居读取 |
| Q | [sqlite_read.py](../../../../src/trivae/data/storage/sqlite_read.py) | SQLite read-only、authorizer、scope、单语句执行和 max_rows |
| E | [evidence.py](../../../../src/trivae/query/evidence.py) | ModelAnswerClaim、parse_model_answer_candidate、has_verified_zero_result_evidence、finalize_answer、finalize_answer_gracefully |
| A | [openai_adapter.py](../../../../src/trivae/query/runtime/openai_adapter.py) | L71 JSON mode；L1510 起 SYSTEM_PROMPT + 动态 budget + soft Plan；L1545 请求格式 |
| B | [budget.py](../../../../src/trivae/query/runtime/budget.py) | 工具结果投影和累计预算；不判断用户问题的语义是否已充分回答 |
| V | [validation.md](../../10-05-discussion-answer-quality/validation.md) | 上轮讨论调查真实配对、四类回归和仍然存在的反例 |
| F | [archify-temporal-relation.json](../../../../evaluation/regressions/archify-temporal-relation.json) | 真实日期关系错误；引用有效不能证明“同日”正确 |

## 标签与阅读方式

- `KEEP_IN_PROMPT`：模型仍需判断的跨工具策略或证据语义。
- `MOVE_TO_TOOL_SCHEMA`：机械参数契约；Schema 缺口补齐并验证前保留必要说明，Host 始终负责真实校验。
- `MOVE_TO_RUNTIME`：由既有 Host/Capability/Adapter 确定的事实或 enforcement。这里的 Runtime 是 Host 执行边界总称，**不建议把 Capability/SQL ownership 搬进 Agent Runtime**。
- `MOVE_TO_FINALIZER`：结构、来源与零结果证明的确定性校验；仍要告诉模型该如何提交合法候选。
- `DEDUP`：合并进表中指定的首条策略；不是删除行为。
- `EVAL_ONLY`：具体样例/错误措辞保留在测试或实验，不作为生产规则本体。

一行可以含多个标签：同一句经常同时包含策略、参数和例子。所有删除都受“已有承接”或“先补契约”条件约束。

## 逐条分类

| ID | P 行号 | 分类 | 规则、去向与删除前提 |
| --- | --- | --- | --- |
| P01 | 7 | KEEP_IN_PROMPT | 从可用 Trivae 消息回答用户实际问题；保留 Role。 |
| P02 | 8 | KEEP_IN_PROMPT | 按证据需求选工具；保留 Retrieval 总原则。 |
| P03 | 9–15 | KEEP_IN_PROMPT / EVAL_ONLY | 时间定义候选集的 overview 用 recent first，较大 limit；清单例外保留。具体中文问题转 Evaluation，策略不移走。 |
| P04 | 16 | KEEP_IN_PROMPT | 同时问有无发言和讨论内容仍按时间窗调查；合并 P03，避免误用统计替代内容。 |
| P05 | 17–18 | MOVE_TO_FINALIZER / KEEP_IN_PROMPT | E 的 has_verified_zero_result_evidence 不接受 SQL COUNT 单独证明空检索；保留“需要完整空检索”，压缩内部判定说明。 |
| P06 | 19–25 | KEEP_IN_PROMPT | discussion 与 inventory 意图区分；含链接不自动变成清单。保留讨论主锚点。 |
| P07 | 26–29 | KEEP_IN_PROMPT | 当前显式资源清单以 github.com lexical first，传请求时间；并非看到 github.com 就切换工具。保留既有顺序，不在等价重构中扩大/收窄范围。 |
| P08 | 30–31 | KEEP_IN_PROMPT | 非空资源结果不再 recent/SQL 重数同一资源；属于停止决策，Q/Schema 不会替模型决定。 |
| P09 | 32–34 | KEEP_IN_PROMPT | 非 URL 资料可补不同的 semantic 证据需求，不用宽泛 recent 替代。 |
| P10 | 35–38 | KEEP_IN_PROMPT / MOVE_TO_RUNTIME | 人物 recent 用 canonical user_id；主题 overview 无 sender filter。scope enforcement 已由 S/C 承接，filter 选用语义必须保留。 |
| P11 | 39–42 | KEEP_IN_PROMPT | overview 不猜主题；不重复相同 recent；零结果如实报告范围。Runtime 无查询语义去重，不可全删。 |
| P12 | 43–45 | KEEP_IN_PROMPT | complete/zero recent 可结束该窗调查，Plan 不强迫再 SQL/schema。属于何时停止。 |
| P13 | 46–47 | KEEP_IN_PROMPT / EVAL_ONLY | 精确目标用 lexical；名称、URL、标识符、错误、昵称属决策知识。单条 matt skill 问句可只留评测。 |
| P14 | 48–49 | KEEP_IN_PROMPT / EVAL_ONLY | 概念/改写用 semantic；具体上下文压缩示例留评测。 |
| P15 | 50–51 | KEEP_IN_PROMPT | 结构化统计、排名、GROUP BY 与比较用 SQL。 |
| P16 | 52–55 | KEEP_IN_PROMPT | lexical/semantic first 与另一工具仅补弱/空/歧义/不足结果；不无目的双查。 |
| P17 | 56–58 | DEDUP / MOVE_TO_RUNTIME | 两检索路径独立合并 P16；不虚报工具合并 P43；legacy surface 由 A/T 注册边界承接，不需要生产主 Prompt 展开旧名称。 |
| P18 | 59–62 | DEDUP | github.com-first 合并 P07；讨论推荐例外合并 P06；保留 URL 是用户所求证据。 |
| P19 | 63–64 | KEEP_IN_PROMPT / DEDUP / EVAL_ONLY | 清单用当前 lexical 最大 limit 是策略，合并一次；20/30 小 limit 反例放测试。T 的 maximum 仅禁止越界，不能强制选满。 |
| P20 | 65–67 | KEEP_IN_PROMPT | 清单默认 0/0 context、必要才展开单命中；选择原则保留，不能通过改工具默认值代替。 |
| P21 | 68–70 | DEDUP | 清单与特定讨论边界合并 P06/P07；不得把所有资料问题都当 broad inventory。 |
| P22 | 71–74 | DEDUP / MOVE_TO_TOOL_SCHEMA / EVAL_ONLY | 清单 lexical 最大值合并 P19；semantic 独立小上限已由 T 固定到 20，转工具信息；不照搬 lexical 容量的决策保留，20/30 反例转测试。 |
| P23 | 75–77 | KEEP_IN_PROMPT | 独立 Skill/resource 需求可另查；求链接不能只靠 semantic 未检查 URL path。 |
| P24 | 77–81 | KEEP_IN_PROMPT / MOVE_TO_RUNTIME / EVAL_ONLY | 相对范围表达、archive_latest、使用 Host UTC 保留简短指导；S/R 负责解析与半开窗。30 天 JSON 是示例，实际字段说明放 T/Schema；禁止模型算日期仍保留。 |
| P25 | 82–84 | KEEP_IN_PROMPT / EVAL_ONLY | 多个实质不同类别未覆盖可分别 lexical；一个零 semantic 不代表完成所有类别。具体 GitHub+Skill 例子转评测。 |
| P26 | 85–87 | KEEP_IN_PROMPT | 人物身份不明确先 find_members，多个候选显式歧义，不静默择一。类型 Schema 无法判断用户指谁。 |
| P27 | 87–90 | KEEP_IN_PROMPT | canonical user_id 与平台号/昵称不同；历史唯一候选可复用，否则再 resolve。合并 P10 的身份说明。 |
| P28 | 90–92 | KEEP_IN_PROMPT | SQL sender_user_id 与 platform_uin 分工需由 T/get_schema 字段知识解释；保留“用已解析 canonical identity”，不要误称 Schema 已校验任意 SQL 的 ID 语义。 |
| P29 | 92–94 | MOVE_TO_RUNTIME / KEEP_IN_PROMPT / EVAL_ONLY | 当前 source_id handle 与 canonical message_id 分别走 T 的解析路径；保留“复制返回 source_id”简短用法；m1-1 例子进工具字段 description/测试。 |
| P30 | 95–96 | KEEP_IN_PROMPT / MOVE_TO_RUNTIME | 不逐个展开合并 context 策略；同会话/scope bound 已由 X/S 执行，可删重复 enforcement 展开。 |
| P31 | 97–99 | KEEP_IN_PROMPT | 问题/请求相关命中是回复调查锚，局部不足先 context，再重复 broad retrieval；与 P06 合并为稳定 discussion policy。 |
| P32 | 100 | KEEP_IN_PROMPT | 已知独立锚点可同轮并行；只是策略许可，不引入自动批量展开。 |
| P33 | 101–103 | KEEP_IN_PROMPT / EVAL_ONLY | 按讨论线索/密度选 later window；单位是消息条数移到已有 T 字段说明；20/40 只是例子移评测，默认仍为 8/8。 |
| P34 | 103–106 | KEEP_IN_PROMPT | 小窗不能证明无人回复、部分要说边界；相邻不证明 reply/归属。Finalizer 不检查任意负面措辞。 |
| P35 | 107–111 | KEEP_IN_PROMPT | Plan 是软建议；保留有区分度的实体或返回别名，不能用泛类别代替。与 P06 同层，不能因有 Plan 删除。 |
| P36 | 111–114 | DEDUP / KEEP_IN_PROMPT | 相关 discussion source 合并 P31；仅清单或独立未覆盖需求加类别查询，合并 P25。 |
| P37 | 115–116 | DEDUP / KEEP_IN_PROMPT | SQL 结构统计合并 P15；不扫文本自己计数的原则保留。 |
| P38 | 117–119 | DEDUP / KEEP_IN_PROMPT | 资源重数合并 P08；独立 SQL 事实且未知 Schema 时先 get_schema 保留。 |
| P39 | 120–123 | MOVE_TO_RUNTIME / KEEP_IN_PROMPT | Q authorizer/read-only/scope/max_rows 承接硬限制，细项不必反复写；保留只读 SQL、未知 Schema 先查和尊重 truncated。 |
| P40 | 123–125 | KEEP_IN_PROMPT | SQL error 不悄悄换工具或重发近似语句，说明限制；现有预算不是 error-loop 判定，不删停止指导。 |
| P41 | 126–129 | KEEP_IN_PROMPT / EVAL_ONLY | 不重复近似检索、不做同工具多次 query 扩展；翻译/同义/标点例子留回归，原则一次说明。 |
| P42 | 129–130 | DEDUP | 足够即停止、另一路径须有实质不同证据合并 P16。 |
| P43 | 131 | KEEP_IN_PROMPT | 不声称工具返回了实际未返回结果；归入 Core/Evidence。 |
| P44 | 132–134 | KEEP_IN_PROMPT | text/finding/criterion 的时序关系必须由返回时间支持，不能倒序或假称同日。F 证明有效 citation 不代表时序成立。 |
| P45 | 134–135 | DEDUP | 相邻不证明反应与引用不证明臆造时序合并 P34/P44。 |
| P46 | 136 | KEEP_IN_PROMPT | display name 不是发言正文。E 投影已分 author/content，但不会校验正文每一句归属。 |
| P47 | 137–139 | KEEP_IN_PROMPT / DEDUP | author 为消息说话人；提问/回复/推荐/synthesis 分开；邻近归属重复并入 P34。 |
| P48 | 140 | KEEP_IN_PROMPT / DEDUP | 提及/分享不证明推荐或价值；同一行后半句字面重复删除。 |
| P49 | 141 | KEEP_IN_PROMPT / DEDUP | 打算试不证明已使用；后半句字面重复删除。 |
| P50 | 142 | KEEP_IN_PROMPT / DEDUP | 审阅他人输出不证明个人安装/使用；后半句重复删除。 |
| P51 | 143 | KEEP_IN_PROMPT / DEDUP | 命中数不等于实体去重数；后半句重复删除。 |
| P52 | 144–146 | KEEP_IN_PROMPT | partial/truncated 不支持穷尽或强否定；E 提供 coverage 元数据，但不判断任意正文结论。 |
| P53 | 147 | KEEP_IN_PROMPT | 用户可读正文不泄漏内部 scope/SQL/Trace；V 的零结果仍有遵从反例，不能误称后处理已保证。 |
| P54 | 148–149 | DEDUP / KEEP_IN_PROMPT | 弱/空/error 如实说明，禁止静默换数据源；与 P16 的允许补另一独立检索路径区别开，不能改成禁止所有跨工具补查。 |
| P55 | 150–151 | MOVE_TO_TOOL_SCHEMA | keyword string 类型已在 T；非空、unused filter omit/null、空数组约束不完整。C 已校验，先补 Schema/工具说明，再缩主 Prompt。legacy 详解无需重复。 |
| P56 | 151–152 | MOVE_TO_TOOL_SCHEMA | limit 正整数与 trusted max 已由 T/C/Capability 承接；可移出主 Prompt 的参数段，保留 P19 的 max 选择策略。 |
| P57 | 152 | MOVE_TO_TOOL_SCHEMA | context 非负仅在 C 校验，T 目前只给 int/default；补 minimum 前不称 provider 已保证。 |
| P58 | 152–153 | MOVE_TO_TOOL_SCHEMA | semantic query 非空/dense_top_k 正值在 C；T 无 minLength/minimum，需补契约且空白字符串仍由 Host 校验。 |
| P59 | 154 | DEDUP / KEEP_IN_PROMPT | 从返回投影复制 source_id 合并 P29；身份语义不能只靠 string Schema。 |
| P60 | 155 | MOVE_TO_TOOL_SCHEMA / MOVE_TO_RUNTIME | source_id/message_id 恰一项：T 函数体执行；Schema 目前均 optional，无 oneOf。字段解释已在 T，不能声称互斥已迁移到 Schema。 |
| P61 | 155–156 | MOVE_TO_TOOL_SCHEMA | context 非负和总量 bounded 由 C；补 Schema 时避免新增未有依据的单侧上限，Host 保持总量校验。 |
| P62 | 156–157 | MOVE_TO_TOOL_SCHEMA | find_members 非空 query/filter 在 C；T 无 minLength/minItems，工具说明已部分承接。 |
| P63 | 157–158 | MOVE_TO_TOOL_SCHEMA / MOVE_TO_RUNTIME / KEEP_IN_PROMPT | SQL string/max_rows 类型上限在 T；单语句/只读在 Q；不用隐藏 Schema 归 P38。不是让 JSON Schema 分析 SQL 文本。 |
| P64 | 158 | MOVE_TO_TOOL_SCHEMA | get_schema 无参数已经由工具签名提供；可删除主 Prompt 重述。 |
| P65 | 158–159 | MOVE_TO_RUNTIME | recent 无时间参数默认 archive_latest 两天已由 R/limits 承接、T 公开描述；不把例示默认变更为新行为。 |
| P66 | 159–161 | MOVE_TO_TOOL_SCHEMA / MOVE_TO_RUNTIME | recent time_range 与 start/end 互斥在 C；Schema 用自由 dict，关系不完整。limit bounds 已在 T；filters 空数组规则同 P55。 |
| P67 | 161–163 | MOVE_TO_RUNTIME / KEEP_IN_PROMPT | cursor window/filter/UTC 一致性由 C/R；模型仍需“仅原样续传 next_cursor，不重复”。未见跨回合 cursor 去重 ledger，不承诺拒绝所有重复调用。 |
| P68 | 164–166 | KEEP_IN_PROMPT / MOVE_TO_FINALIZER | 简短要求引用当前返回 source handle；E 负责合法性、run/scope/provenance，细列内部 ID 类型不必重复。 |
| P69 | 166–167 | KEEP_IN_PROMPT | structured row/member/schema 使用返回 structured source_id；可合并成所有证据共用的引用规则。 |
| P70 | 167–168 | MOVE_TO_FINALIZER | value_snapshot 来自 E trusted hydrate，模型不生成；合并“只提交语义字段/handle”。 |
| P71 | 168–171 | MOVE_TO_FINALIZER / KEEP_IN_PROMPT | E graceful 仅有界处理既有局部缺损，fatal provenance/scope 显式失败；不新增 recovery。保留不伪造来源与标明未知，不需要模型背恢复算法。 |
| P72 | 172–174 | KEEP_IN_PROMPT | 当前 JSON mode 仍需明确 final JSON、无 fence/额外正文；不是 Structured Outputs，不能只留“用 required schema”。 |
| P73 | 175–185 | KEEP_IN_PROMPT / MOVE_TO_FINALIZER | claims 字段、sufficiency enum、sources/limitations 生成契约暂保留一次；E parse/ModelAnswerClaim 已硬校验。Provider Schema 迁移是后续独立能力验证，尚未实现。 |
| P74 | 186–187 | MOVE_TO_FINALIZER / DEDUP | Host 确定 block/evidence/binding/provenance；模型只产语义候选，合并 P70 的一句所有权说明。 |
| P75 | 188–190 | KEEP_IN_PROMPT / MOVE_TO_FINALIZER | tool-backed factual claim 要来源；E 校验与 graceful 状态按现有契约保留。生成策略仍需简短说明，不把“可 degraded”当许可无证据作答。 |
| P76 | 191–193 | KEEP_IN_PROMPT / MOVE_TO_FINALIZER | no_result 的另一 JSON 形状暂保留；E 的 parse_model_no_result_candidate/zero proof 负责放行，不能仅说“没有消息”而不检查成功/complete。 |
| P77 | 194–195 | KEEP_IN_PROMPT | summary 仅讲检索缺失与 metadata，不写正向主题；不能将“keyword 零命中”泛化为“整个范围无消息”。当前正文说明有这个张力，等价重构沿用规则，语义改动另评审。 |
| P78 | 195–197 | MOVE_TO_FINALIZER / DEDUP | E 判定完整空窗与数值 SQL 聚合共存，普通 row/消息需正常 claims；硬判定移 E，短生成条件合并 P05/P76。 |
| P79 | 198–200 | KEEP_IN_PROMPT / MOVE_TO_FINALIZER | bookkeeping bounded 与 answer prose 完整分开；硬容量在 E/B，claim.text 是用户正文的语义必须保留。 |
| P80 | 200–204 | KEEP_IN_PROMPT | 根据问题给细节，宽 overview/comparison/timeline/inventory 覆盖独立 finding 与具体证据。不是固定字数/rubric。 |
| P81 | 204–206 | KEEP_IN_PROMPT | 事实/synthesis/limitations 分开；不为省 claim 合并无关结果、不加无支持背景、不倾倒聊天。 |
| P82 | 207–209 | KEEP_IN_PROMPT / DEDUP | 独立 finding 可各一 claim，相关事实可分组；重复 source 禁令按上下文解释：单 claim 重复禁止，独立 claims 可合理共用，不扩大 E 的约束。 |
| P83 | 209–211 | KEEP_IN_PROMPT / DEDUP | 资源保留已返回 URL，提及与独立验证价值区分；价值边界合并 P48。 |
| P84 | 211–212 | KEEP_IN_PROMPT | 有 URL 项优先，name-only 明确仅在已检索证据中未找到链接，不能声称链接不存在。 |
| P85 | 213 | DEDUP | 相关时说明 effective range，合并 P24。 |
| P86 | 214–216 | KEEP_IN_PROMPT | 清单按类别与多样性选代表，不逐条罗列命中；partial 报剩余量并保留边界。总量以 Tool metadata 为准。 |
| P87 | 217–219 | MOVE_TO_FINALIZER / KEEP_IN_PROMPT | E 每 claim/source 上限 20 已校验，但 JSON mode 不给模型 Schema；目前保留一次上限提示和“来源支持实际列项”。 |
| P88 | 219–220 | KEEP_IN_PROMPT / DEDUP | finding/criterion/limitations 简短不限制 claim.text，合并 P79。 |
| P89 | 220–221 | DEDUP / MOVE_TO_FINALIZER | mandatory claims/closing braces 合并 P72/P73；模型 output budget 由 A 配置，不增加预算或 repair。 |
| P90 | 222–224 | KEEP_IN_PROMPT / DEDUP | semantic expansion 与 direct range-core 区分，选择能支撑 finding 的 core handles；独立 claim 可共享 source，避免改成全局禁止重复。metadata/prose 分工合并 P79。 |
| P91 | 225–227 | DEDUP / KEEP_IN_PROMPT | recent 使用返回 resolved_time_range UTC、禁止从历史/毫秒算日期合并 P24/P44；metadata 简短合并 P88。 |
| P92 | 228–230 | KEEP_IN_PROMPT / DEDUP | 单消息日期复制 timestamp_utc，缺失保持未知；Host 投影 E 负责提供，模型措辞仍需规则。合并 P24/P44 时间段。 |

## 重复簇及最小合并方式

| 重复簇 | 来源 | 保留一次的内容 |
| --- | --- | --- |
| resource inventory | P07–09、P18–23、P25、P38、P83–87 | 意图边界、URL lexical first、lexical max/0 context、独立非 URL/category 缺口、停止重数、答案呈现 |
| discussion investigation | P06、P29–36 | 相关实体/提问锚、局部不足先 context、按线索选窗口、部分负面结论、相邻不证明回复 |
| 工具选择/停止 | P03/P11/P12、P13–17、P37–43、P54 | 三种候选集、按缺口补另一检索路径、充分即停、禁止无意义重复/error-loop |
| 时间事实 | P24、P44/P45、P85、P91/P92 | archive_latest 意图交 Host、UTC 原样、范围与消息时间区分、正文与 metadata 时序一致 |
| citation/output | P29、P59/P60、P68–76、P87/P89 | source_id 用法在工具字段，生成只提交语义候选与 handle；JSON mode 下格式保留一次，校验归 E |
| Evidence bookkeeping vs prose | P79–82、P88–91 | metadata 简短，用户正文按实际需求完整，不为压缩漏独立 finding |
| 单行字面重复 | P48–51 | 每条删除分号后重复表达；前半句保留，不移除 evidence strength 策略 |

T 的 description 也复制了不少跨工具策略。不能只缩 P 后把相同的 20k 内容搬进 description。后续评测应观察**完整实际 instructions、所有工具 description/Schema、动态 Plan 和结果投影**，分别记录体积；主 Prompt 变短不等于请求 token 一定下降。

## 实际承接程度

SDK 实物检查使用 `trusted_max_results=5000`，不调用 Provider 或 Capability；传入的 registry 仅用于构造闭包，未执行检索。

| 契约 | 实际 Schema/Host | 迁移判断 |
| --- | --- | --- |
| lexical/recent limit | integer、minimum=1、maximum=5000、default=1000 | 已有 Schema/Host；清单选择最大值仍是 Policy |
| semantic limit | integer、minimum=1、maximum=20、default=10 | 已有独立容量，不能跟随 lexical 放大 |
| member limit / SQL max_rows | max=100；SQL 可 null | 已有 bound，保持 trusted scope 的更小上限 |
| keyword/query | string，无 minLength | C 拒绝空/空白；Schema 迁移未完成 |
| context/dense_top_k | integer/default；无 minimum | C 拒绝负数/dense=0；context 总量另有 C 约束 |
| context identity | source_id/message_id 都 optional；无 oneOf | T 函数体恰一项校验，且 source handle 必须当前结果解析 |
| time_range/cursor | 可 null 的自由 object；关系未用 Schema 编码 | C/R 校验真实字段、互斥与一致性；仍需工具局部使用说明 |
| 空 filter 数组 | array|null，无 minItems | C 的归一化/拒绝负责，非 provider 强制 |
| 重复近似 query/cursor | 未发现 Runtime 跨回合语义去重 ledger | 保留模型停止指导，不为迁移新增自动去重系统 |
| 输出 claims/no_result | A 仅 json_object；E 独立 parser/validator | 保留最小生成格式；Structured Outputs 不作为本次前提 |
| author/UTC/coverage | E 的 model projection 提供可信字段 | 不能保证生成语句正确；保留语义策略和真实评测 |

## 已有测试、真实评测与缺口

| 行为 | 可复用材料 | 能证明什么 / 不能证明什么 |
| --- | --- | --- |
| 工具可见性、实体/讨论/清单选择指导 | [test_agent_tool_surface.py](../../../../tests/test_agent_tool_surface.py)、[test_agent_runtime.py](../../../../tests/test_agent_runtime.py) | 包含大量逐字 Prompt 断言；只能证明文本/接口存在，不能证明模型遵从 |
| source handle 与 canonical ID | [test_context_source_contract.py](../../../../tests/test_context_source_contract.py) | 真 SDK schema、错误参数、Host 解析与 Trace；文本去重后应保留行为测试 |
| 时间关系 | [test_temporal_relation_regression.py](../../../../tests/test_temporal_relation_regression.py)、F | 保存真实错误与 canonical 反证、Judge 输入；mock verdict 不是真实模型质量 |
| capacity/projection/budget | [test_retrieval_budget.py](../../../../tests/test_retrieval_budget.py)、[test_evidence.py](../../../../tests/test_evidence.py) | 上限、截断、证据投影；不证明主题覆盖/推荐归属正确 |
| recent/zero-result/SQL | [test_recent_messages.py](../../../../tests/test_recent_messages.py)、[test_temporal_overview_coverage.py](../../../../tests/test_temporal_overview_coverage.py)、[test_temporal_zero_result_integration.py](../../../../tests/test_temporal_zero_result_integration.py)、[test_sqlite_read.py](../../../../tests/test_sqlite_read.py) | Host 的时间窗、cursor、空证明、只读与 scope enforcement |
| 新讨论 Failure Case | V、[real_pair.py](../../10-05-discussion-answer-quality/real_pair.py) | 两次候选恢复并使用推荐；原顺序 AABB、非盲、baseline 冷加载，不能推导普遍成本优势 |
| benchmark Development | [evaluation README](../../../../evaluation/README.md)、[Development suite](../../../../evaluation/suites/resume-benchmark-dev-v1.json) | 37 个已暴露 Development Cases 可作 wider regression；历史五 Variant baseline 不能冒充当前 460259d baseline |

后续同条件配对至少覆盖讨论推荐/真实使用、纯资源清单、一般非 URL 学习资料、多类别、recent overview、人名过滤、精确/语义检索、统计 SQL、完整/部分空结果、作者与日期关系。使用已暴露 Development 和上轮真实案例；禁止重跑 sealed v1 Holdout 来包装为新 generalization。

现有逐字断言在**本轮不修改**。后续仅在确实表达同一策略的新措辞获评审后替换文案断言，并说明映射的 Policy ID；不得移除参数、引用、零结果、来源/时间或执行路径行为测试来迎合错误实现。

## 待定语义与实施边界

- P07 的现有范围较广：泛资源清单也指导 github.com first。第一批保持；若未来要改成只有 GitHub 清单才 first，必须单独确认，并用非 GitHub 清单 Failure Case 验证。
- P77 的零结果 summary 示例把“无检索命中”写成“范围无消息”。精确 keyword 空结果不能证明全窗无消息；记录这个张力，第一批不借去重改变 no_result 判定或用户语义。
- P82/P90 的“source 不重复”应按现有 parser 的单 claim 去重、独立 findings 可复用解释；不能新增全局去重约束。
- V 的绝对下界与相对窗不一致、强否定和日期倒序是保留反例；本轮不添加日期解析器、关键词 guard 或自动补查。

本轮完成的是审计与规划，不是运行策略改善；没有新的答案质量、token/latency 改善或 Structured Outputs 能力结论。
