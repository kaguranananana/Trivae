# GPT High 候选删文只读复核

范围：`resume-candidates-v2` 的 B01、B02、C01、C02；原 P01–P92 审计、历史真实失败、现行 `openai_tools.py` / Capability / typed input 与回归。仅新增本报告，未修改生产 Prompt、候选、Case/GT、预算或索引，未向 Trivae 被测 Provider 额外发送 Judge 或实验请求；Codex Agent 自身复核属于模型审查。

## 逐组结论

| 候选 | 实际删文范围 | 已有承担者与保留语义 | 审查结论 |
| --- | --- | --- | --- |
| B01 | P64 无参数句及其独立 `For` 引导，共 35 字符；20450→20415 | `GetSchemaSDKToolAdapter` description 明示无参数；空对象 Schema / additionalProperties=false；`on_invoke_tool` 在 SDK 忽略多余字段前显式拒绝，合法调用继续原 registry。主 Prompt 中 SQL schema 未知先 get_schema 的指导仍保留 | 没有发现丢失独立业务语义；可进入真实筛选，不能仅凭静态合同接受发布 |
| B02 | 在 B01 上再删 P56 正整数/上限与 P57 非负 context，共 164 字符；20415→20251 | lexical/legacy descriptions 和字段说明保留原约束；limit/context 使用 strict integer、ge=1/ge=0；typed input 再校验，Capability 拒绝超 trusted maximum。清单必须选 lexical 最大值、清单 0/0、semantic 独立容量、按需要展开与请求 time_range 均仍在 | 属同一 lexical 参数合法性责任组；不能将配对差异细分归因为 P56 或 P57。Host 拒绝非法值不等于模型选择参数正确 |
| C01 | P13/P14 全部，以及 P16 的 first-call 句，共 561 字符；20251→19690 | lexical/semantic descriptions 仍完整指导精确词 lexical first、概念 semantic first；P16 余下的弱/空/歧义/不足才补另一工具仍在；recent、SQL、inventory 特定选路仍在 | 一个明确的“主 Prompt 通用首次检索指导去重复”组；不是完整删除 P16，也不是移除全部检索策略。不能宣称模型已无策略提示自主选路 |
| C02 | P33 中 20/40 只是例子而非固定默认的单句，共 90 字符；19690→19600 | 前句仍要求按讨论线索和消息密度选择 later window、单位为消息条数；后句仍禁止小窗证明无人回复，要求覆盖线索并说明边界。Host 默认窗口及工具描述均未改 | 单一数字示例消融，职责清楚；不是删除窗口策略或改变默认值 |

已逐组通过整串等值检查：每个父候选中每段 removed 恰出现一次，按 manifest 顺序删除后的全文与候选逐字一致，无额外编辑。B01 将 `For\nget_schema...` 一并删除，避免留下悬空引导词；B02 删除后 `For\nsemantic_search` 仍组成完整句。

## 真实 Case 的必要覆盖与风险

下列均复用现有已暴露 Development；不扩写 GT，不以工具次序充当答案 GT。若 Case 未实际触发待测工具，应明确该职责未得到动态验证。

- **B01**：优先 `pu-count-utc-day`，检查真实是否调用 get_schema、参数是否为空、后续 SQL 是否仍绑定指定 UTC 半开区间并由本轮 SQL 来源支持。若模型已知 schema 而直接执行合法 SQL，该 Case 可评答案，却不能证明删除后 get_schema 调用行为。还需与非 SQL Case 一起检查是否出现无必要 schema 调用。风险是模型决策或非法参数导致回合失败；Host 只保证拒绝，不能保证不会生成非法调用。
- **B02**：`dev-lexical-chatlog-alpha` 检查精确事实、URL 与证据；`frozen-github` 检查用户明确起点、lexical 最大 limit、0/0 与实际列表覆盖，以及作者去重和正文时间一致性；`dev-context-mattpocock-1` 检查窗口参数合法之外的推荐/使用/反馈覆盖；`dev-zero-excalidraw` 检查空命中不虚构。仅通过一个精确词 Case 不足以排除历史 inventory 退化。
- **C01**：至少同时覆盖精确目标 `dev-lexical-chatlog-alpha`、改写概念 `dev-para-ts-learning` / `dev-para-resume-advice`，再核对精确空命中、讨论 context 与资源清单。首工具选择只是解释机制；最终裁决仍看 reference findings、引用支持、检索送达、负面边界与事实正确性。两个候选首工具一致也可能有答案差异，首工具不同也不必然失败。因现有 description 已有同策略，本组即便通过也只能证明重复主 Prompt 指导可删。
- **C02**：优先 `frozen-reply`、`cal-context-ui-skill`、`dev-context-mattpocock-1`，逐条检查已裁决推荐/后续第三人评价是否进入实际模型输入及最终 evidence，作者与回复关系是否正确，有限窗口是否误写为唯一推荐或此后无人回复。窗口数字不是质量目标；选 8/20/40 或其它合法值应按实际送达与覆盖判断。

上述 coverage 可由同条件累计门禁共同承担，无需为了每个列表机械增加重复请求。最终四条既有 Development 继续按既定“不调候选”边界处理，不能冒充新盲 Holdout。

## 历史失败的约束

`loop-20261006-review.md` 与 `optimization-log.md` 保存了相同参数片段的 DeepSeek 历史筛选：P01/P02 参数合同静态通过，但真实候选曾丢用户 start_timestamp、混淆 canonical 作者数与显示名数、把 GitHub 命中时间当 archive_latest；更大累计候选还出现未覆盖完整线程却宣称唯一推荐、UI 推荐/评价漏召回。P01–P92 是 Policy ID，旧 P01–P16 同时还被用作历史候选轮次名，报告应避免混用。

这些证据要求本轮保留时间、作者、coverage、negative 与讨论恢复检查，但不证明 GPT High 会复现，也不证明某一被删句具有因果。不能用静态责任迁移、Finalizer valid、双方共同漏 GT 或 Prompt 字符减少替代质量通过。若 A 本身未送达/回答关键 GT，应记录 Baseline 局限；该对照不能证明候选通过该高风险职责。

## 验证与未修改事项

- 本地合同/fixture 回归：`test_prompt_limit_contract.py`、`test_prompt_parameter_contracts.py`、`test_context_source_contract.py`、`test_prompt_fixtures.py`，**245 passed，3.17 秒**。
- 覆盖真实 SDK 的非法原始类型拒绝、trusted maximum、get_schema 多余参数与空参数、context 窗口送达与作者/时间/空结果；这些是执行合同证据，不是本轮模型质量数据。
- 本报告未发现候选文本与 manifest 的额外漂移，未修改任何候选或生产文件。无需在本轮引入工具 API、额外 guard、默认值变化或样例专用规则。
