# Prompt Policy 删减审计与本轮决定

沿用 `10-05-prompt-policy-audit/research/prompt-policy-audit.md` 的 P01–P92，不建立第二套分类。当前生产原文来自 `prompt.py`，20450 字符。下列均是离线职责判断，不能等同 GPT High 语义通过。

| 类别 / Policy ID | 原文或关键内容 | 当前实际承担者 | 原问题与可能退化 | 对应 Development | 决定 |
|---|---|---|---|---|---|
| 低风险 P64 | `get_schema, send no arguments. ` | `GetSchemaSDKToolAdapter`：description、无参数对象、真实 SDK 拒绝额外参数 | 非法工具参数；删除后模型选择仍可能变化，不能由 schema 保证最终质量 | exact / schema / structured | 仅 B 草稿删除这 31 字符；未执行、未接受、未发布 |
| 低风险 P55/P56/P57 | keyword 单字符串、正整数 limit、非负 context | SDK strict/minLength/minimum、typed input、trusted maximum；旧 C17–C23 契约测试 | Schema 能拒绝非法值，不能保证模型选择正确范围/limit；历史 DeepSeek P01 曾丢 requested time_range | exact、inventory、discussion | 本轮不累计删除，等待首组通过 |
| 低风险 P60/P61/P63 | context 恰一 identity、总量、SQL 单语句/只读 | SDK callable、Capability、SQLite driver/authorizer；并非全由 JSON Schema 承担 | 将执行合法性误当作参数语义正确；scope、schema 未知与 stop 仍需模型指导 | discussion、structured、identity | 保留 |
| 去重 P48–P51 | 提及≠推荐、打算≠使用、他人输出≠本人使用、命中数≠去重实体数的重复文字 | 前半句是模型语义；Finalizer 不理解任意正文 | 作者归属、推荐关系、计数合成错误 | discussion、inventory | 保留；将来仅逐项去重复 |
| 策略 P13/P14/P16 | lexical/semantic 选用与 first retrieval 顺序、弱证据再补查 | 模型；工具 description 也包含 lexical/concept 提示 | 固定顺序删除后能否自主选择未知；不能把工具 description 的残留指导称为完全自治 | exact、paraphrase、weak result | C 计划候选，B 未通过所以未构造 C |
| 策略 P07/P18/P19/P20/P23/P25 | github.com-first、lexical max、0/0 context、独立类别补查 | 模型；lexical/recent description 仍复述部分策略 | 资源召回缩小、时间范围丢失；只改 SYSTEM_PROMPT 不等于真正消除全部 URL-first 指导 | inventory、non-URL learning、multi-category | 保留，不能同时删除多组策略或改工具描述引入新变量 |
| 高风险 P06/P29–P36 | 讨论锚点、后续展开、reply 关系、窗口边界 | 模型 + Host 只保证 context 数据和范围 | 历史推荐漏召回、局部窗口错误强否定、相邻消息错归属 | frozen-reply、UI / mattpocock context | 保留；Host 没有完整语义承接 |
| 高风险 P24/P44/P45/P85/P91/P92 | 时间范围、真实 UTC、跨日时序 | Host 给可信时间；正文概括仍由模型负责 | 历史 inventory 正文时间矛盾，不能用更完整链接抵销 | temporal、inventory、author/time | 保留 |
| 高风险 P26–P28/P46/P47 | canonical identity、说话人/推荐者/评价者分开 | Host 身份字段 + 模型语义 | 找到正确消息仍可能写错作者/推荐关系 | identity、discussion、citation | 保留 |
| 高风险 P34/P52/P54/P76–P78 | 零结果、partial/truncated、真实错误和强否定 | Host coverage / no_result proof + 模型措辞 | Finalizer valid 不证明“没有其他建议”；partial 不证明全量空 | empty、partial、discussion | 保留 |
| 高风险 P68–P75/P79–P90 | provenance、citation、结构化输出、finding 完整度 | Finalizer 校验引用/形状，模型负责事实选择与解释 | 合法引用可能不支持正文结论；不能把 Host 校验当事实正确性 | 所有 case | 保留 |

没有任何规则完成生产删除。不能根据一次协议失败推断任何 Policy 必须永久保留；也不能根据机械契约测试宣称可安全删除。

旧 DeepSeek P16/P08/P04/P02/P01 的真实失败仅用于风险排序，未作为本轮对照；既有 Holdout 未查看或重跑。本轮无人工语义答案评审，因为没有有效答案。
