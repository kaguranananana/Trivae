# Planner Evaluation 最终工程收口

日期：2026-10-03。结论：**限制使用**。保留 Thin Planner 架构与 P1/none，production routing 继续保守，Jev 保持 shadow；本轮没有依据扩大 Planned 的使用范围。low/none 研究与当前 Standard/Planned validation 均 closed，不安排后续付费 Planner 实验。

证据口径：这是八条已暴露 Development Case 的单次配对工程检查。数字从完整 raw 派生；语义结论是主代理逐 Claim 对 canonical 来源的非盲审复核，**不是人工 adjudication、独立盲审、统计显著性或 fresh Holdout 结论**。

## 1. 最终生产配置

| 模块 | 当前身份与职责 |
| --- | --- |
| Router | Rule-first；独立官方 DeepSeek `deepseek-flash` completion、`low`、2048、temperature=0、JSON。当前环境 Jev enabled / shadow，不升级其生产路由地位。 |
| Planner | P1 canonical prompt；官方 DeepSeek `deepseek-flash`；独立 `reasoning_effort=none`；2048 completion budget、20 秒、temperature=0、JSON。只生成一次 soft guidance。 |
| Runtime | 同一个生产 OpenAI Agents SDK Runtime；官方 DeepSeek `deepseek-flash`、`low`；8 turns、3 tool rounds、16384 output budget，现有动态 ToolResult budget。 |

Router / Planner completion settings 与 Runtime SDK ModelSettings 分开构建。Standard 直接进入 Runtime；Planned 先调用一次生产 SoftPlanner，再注入生产 renderer 的 guidance。Planner 不执行 Tool、不生成 Tool arguments、不拥有 Step Executor、Workflow、执行状态或 Replanning Loop。检索、context 参数、Evidence selection 与 Answer synthesis 仍归 Runtime；Finalizer 使用既有确定性契约。

**为什么 low 改成 none：** 历史 Planner-only 中 low 6/8 valid、2 次 `provider_length`，none 8/8 valid；mean completion latency 6.700→1.301 秒。更早 P1 + none 消融有 24/24 valid、0 `provider_length`。2048 completion budget 被 low reasoning 消耗、造成 Plan 截断是已确认问题。因此 none 是 **completion reliability / latency 的工程选择**。

**为什么不能声称答案更好：** `361a38e` 的 16 次 production E2E 中 none 有两条最终质量回退；`221f57a` 的四次 Frozen Plan replay 固定 guidance 后，context 参数、Evidence selection 与 synthesis 仍变化。原 none 错误没有重现，low-r2 又出现同日错误。该重放未固定 ToolResult，不能隔离纯 Answerer 方差，也不能证明两种 effort 质量等价。上述历史结论和 Gate A 均保留。

## 2. 修复的两个 Failure Case

### source_id / message_id

- 现象：历史 Frozen replay 4/4 runs 把 `m1-1` 等句柄填入 `message_id`，共七次 `MESSAGE_NOT_FOUND`；随后改成 `source_id` 成功。
- 根因：resolver 本来正确；SDK schema 两字段缺少独立 description，Tool description 合并两类身份，而 ToolResult 实际只向模型公开 run-local source handle。
- 修改：`openai_tools.py` 的真实 SDK/Pydantic schema 用 Annotated/Field 分别说明；`source_id` 优先列出，表示当前 run 的 `mN-K`；`message_id` 明确表示 legacy canonical internal ID。`prompt.py` 同步用法。
- Regression：`test_context_source_contract.py` 覆盖 generated schema、projection、resolver、canonical 直接调用、错误字段显式失败，以及 streamed `model_output` 原始 `source_id` 和 normalized Tool Trace canonical `message_id` 的区分。没有形状猜测、silent alias、重试或兼容分支。
- 正式观察：11 次 context 调用全部用 raw `source_id=mN-K`，归一化后全部是 canonical `message_id`，0 参数错误；这是本轮观察，不是未来错误率保证。

### temporal relation

- 现象：low-r2 正确取回 7k=`2026-07-23T09:25:23Z`、9.5k=`2026-08-06T02:40:20Z`，却在 Claim / finding / criterion 中增加“同一天”。实际间隔 **13 天 17 小时 14 分 57 秒**。
- 根因：Retrieval 时间事实正确，Evidence/Answer synthesis 的关系推断错误。确定性 Citation validation 证明来源存在及 provenance，不能证明 Claim 关系受到来源支持。既有 Tier 2 Judge 的 canonical excerpt 还只提供正文，丢失判断所需的日期元数据。
- 修改：原样保存真实 Claim、Evidence、Citation 与两条 canonical facts 到 `archify-temporal-relation.json`；Runtime prompt 明确时间、顺序、reply/reaction 与 sender_name/content 的边界；既有 benchmark Judge 的 evidence excerpt 先提供 UTC timestamp，再提供独立 message_content，避免正文截断吞掉时间。Judge prompt 要检查来源是否支持关系，不能用 finding 自证。
- Regression：`test_temporal_relation_regression.py` 验证 fixture 与原工件一致、日期不同、顺序及精确间隔；复用 LLMClaimJudge 输入/parser 测试与正确对照，`test_benchmark_judge.py` 验证实际 orchestrator 的日期投影。离线测试稳定否定已明确编码的旧同日关系，**不是对任意自然语言做自动语义判断**；mock verdict 不证明真实 Judge 准确率。
- 正式观察：当前两条 cite-archify 输出均未重现同日错误，但 Planned temporal-30d 仍写错样本跨度。提示和评审输入修复没有消除所有关系幻觉；不增加第二套 NLI/temporal engine，也不把该事实隐藏为通过。

## 3. Standard vs Planned 实验身份

- execution commit：`14de11fb50b809384a42b254eb349ae46489b5bc`，branch `codex/planner-p1-stability`。实验前 Git 仅新 output 目录未跟踪，无生产代码未提交修改。
- Snapshot：`canonical-m1-v1`；473,236 messages、14 sources；UTC 范围 `2025-07-20T11:43:20Z` 至 `2026-08-16T02:34:48Z`；FTS 473,236；Qwen3-Embedding-0.6B / 1024 / last_token / normalized，semantic completed、54,267 chunks。
- Case：沿用八个已有 IDs、原 version / gt.* finding / snapshot；GT provenance 已 adjudicated。`utility.structured_answer` 不作为人工 GT。dependent/context 的 GT 为 partial；cite GT 不覆盖所有 star 邻居；temporal GT 只覆盖 window/coverage/truncation/zero，主题结论须另看来源。未修改 GT。
- Provider：`https://api.deepseek.com` / `deepseek-flash`；Planner none、Runtime low；SDK retries=0；无付费 Judge。
- 规模：8 Case × 2 treatments × 1 = **16 logical E2E**；固定相邻配对 AB/BA，各四对，seed=20261004；16 个新 conversation，无 prior history。
- Standard：Planner HTTP=0；Planned：每次生产 Planner HTTP=1。正式 forced route 绕过 Router/Jev，本轮 Router/Jev HTTP=0。
- 两路 Dataset、Runtime、schema、retrieval、预算、Finalizer、Evidence/Citation、Evaluation 完全相同。八对实际首次 Runtime HTTP 去掉生产 renderer 的 guidance 后逐字段相等。

create-only preflight-v1 因 ControlledVariant 不接受 runtime_configuration 的 `api_key_configured` 字段而失败，记录 **0 formal attempts / 0 Provider calls**。修正为独立 configured boolean 后，v2 和 formal preflight 通过；未落盘 key。模型序列化由 MockTransport 完成。源文件、八条 Case/GT、schema 和设置保存逐字副本/完整结构作为身份，不生成摘要值。

完整链路位于 [runs.jsonl](experiment/runs.jsonl)：Query / route override → Planner 与 guidance → Runtime HTTP / 原始 function arguments → normalized Tool arguments / ToolResult → Evidence / Citation → AnswerArtifact → Evaluation / Trace。每条另存于 raw、traces、answers、evaluation；SQLite 为同一运行的辅助持久化。

## 4. 逐 Case 结果

表中 Tool 数是已完成业务 Tool invocation；HTTP 包含 Planned 的一次 Planner。完整 Claim→Evidence→canonical 事实见 [semantic-review-packet.json](experiment/semantic-review-packet.json)，逐工具原始/归一化参数及 GT 差距见 [analysis.json](experiment/analysis.json)，复核判断见 [source-audit.json](experiment/source-audit.json)。

| Case | Standard | Planned | Quality judgment / Evidence / Citation | Tool behavior | E2E 秒 S→P |
| --- | --- | --- | --- | --- | --- |
| pu-dependent-mattpocock | 分享、用法、正反评价；GT evidence 1/2、context 0/1 | 更多正面自述与适用边界；同样 1/2、0/1 | P 的调查组织更贴问题，但“我已经离不开了”是自用表态，不能直接否认 firsthand；S 把 7/18 好评称作 7/19、7/21 推荐的后续，顺序不支持；P 把两条君莫笑消息称为同一条也不准确。双方漏掉真正 reply GT，收益有限且混合。 | S 2 lexical+2 context，其中 generic github.com 扩到 100 条；P 1 lexical+4 context，避免 broad URL 搜索，但未补 GT。HTTP 3→5，Tool 4→5。 | 14.962→14.482 |
| dev-context-archify | 未看到 firsthand feedback | 同样未看到反馈，更多作者更新 | 两路漏取并漏引已确认的“@! 好用”回复，evidence 1/2、context 0/1。“没有反馈”的 finding 超出证据；部分 7k/gallery Claim 未绑定对应来源。P 没有 context recovery 收益。 | S 1 lexical+1 context；P 1 lexical+2 context，增加窗口仍漏 GT。HTTP 3→4，Tool 2→3。 | 7.540→10.459 |
| dev-cite-archify | 7k→9.5k、gallery、赞助、plugin 与外部讨论 | 9.5k、gallery、plugin、外部讨论，未写 7k | 两路原 GT 3/3、expected fact 1/1，当前日期关系无同日错误。P 已取回 7k 却未选择/回答；未声称“只有9.5k”，属于完整性退步。GT 通过不能覆盖该差距。 | S 1 lexical，context3/3；P lexical1/1+2 context。HTTP 2→4，Tool 1→3。 | 5.990→10.128 |
| dev-temporal-30d | 最新100/73863，明确partial；另有整窗会话计数 | 最新200/73863，更多就业/硬件内容，明确partial | P 有可见内容广度收益，但“末尾一天多”错误，200条实际跨度10h26m12s；finding 的“频率最高/数量最庞大”缺计数且相互不一致。两路部分扩展描述有未绑定的邻居事实，不能称完整citation entailment。S明确把“寻找一些实习”归为昵称，P用实际求职正文。 | S recent+schema+group SQL；P recent+精确cursor续页，无整窗主题统计。HTTP 4→4，Tool 3→2。 | 13.542→14.787 |
| dev-zero-empty-3 | 完整空窗正证明，verified zero 1/1 | 同样 verified zero 1/1 | 均无虚构话题；未出现历史 SQL-first / Finalizer 异常。单次成功不宣称长期修复率。 | 两路同一get_recent_messages，UTC2025-08-26，0条；HTTP 2→3，Tool 1→1。 | 4.419→5.883 |
| dev-lexical-forge | 正确分享者、repo、用途与同名歧义 | 同样正确，更明确把使用表态归作者 | 两路 evidence 3/3、fact 1/1。S finding“群成员正面使用反馈”易被误读为第三方，实际是作者自用；P attribution 更准确。核心业务问题两路均解决。 | 相同 lexical forge 与2/2 context、相同 canonical 取回集合；HTTP 2→3，Tool 1→1。 | 6.096→7.288 |
| pu-rank-utc-session | 最高 qq:677019167=224 | 同样，明确UTC半开窗 | 两路 fact 2/2，structured来源支持计数。未验证所有并列场景；该日唯一第一名明确。 | schema+SQL，两路同6行，日期函数 vs 毫秒半开窗；HTTP 3→4，Tool 2→2。 | 5.196→5.716 |
| pu-aggregate-utc-types | text814 / reply17 | 相同计数与其他类型 | 两路 fact 2/2，structured引用支持。无质量收益。 | P 多一次全库MIN/MAX/COUNT，对指定UTC日期无必要；HTTP 3→5，Tool 2→3。 | 7.610→13.383 |

这些判断保留多个轴，不造 better/same/worse 综合质量率。required context 漏失和 false absence 是旧问题在当前两路继续出现，不能归咎于本次 source resolver 修复。有限窗口即便覆盖更多消息，也不能称 corpus-exhaustive 调查。

## 5. 聚合结果

| 实际测量 | Standard | Planned |
| --- | ---: | ---: |
| 完成 E2E / valid AnswerArtifact | 8/8 | 8/8 |
| Planner valid / provider_length | 不调用 | 8/8 / 0 |
| E2E mean / median 秒 | 8.169 / 6.818 | 10.266 / 10.293 |
| Planner mean 秒 | 不调用 | 1.436 |
| 实际 Provider HTTP | 22 | 32 |
| Planner / Runtime HTTP | 0 / 22 | 8 / 24 |
| Tool calls / errors | 16 / 0 | 20 / 0 |
| Partial ToolResult calls | 2 | 2 |
| Input tokens | 275,233 | 284,194 |
| Output tokens | 9,832 | 12,509 |
| Total tokens | 285,065 | 296,703 |
| Cached input tokens | 197,504 | 181,884 |
| Runtime reasoning tokens | 3,730（22/22返回） | 4,741（24/24返回） |
| Planner reasoning tokens | 不调用 | unavailable（0/8返回，不补零） |
| Monetary cost | unavailable | unavailable |

Planned mean E2E 增加 **2.096 秒 / 25.66%**，total tokens 增加 **11,638 / 4.08%**，HTTP 增加10，Tool增加4。Planned Runtime 单独 total tokens 284,980，Planner额外11,723。缓存与顺序保持生产语义；AB/BA 不消除 Provider/cache/输出随机性，不能把此次差值解释成稳态性能因果效应。

全体54/54 HTTP返回200，8 Planner+46 Runtime model turns；16 raw / 16 Trace / 16 AnswerArtifact / 16 Evaluation，16 conversation / 32 messages。36次Tool原始function与normalized序列对齐。Formal integrity 检查源文件/Case与Snapshot未变、retry0、八对首次HTTP隔离一致。valid artifact 和运行成功不等于答案正确。

## 6. 最终 Planner 决策

**限制使用。** P1/none Thin Planner 保留为可选复杂调查路径，production routing 继续已有保守策略，不扩大 Planned，也不把 Jev shadow 提升为生产 decision owner。本轮不修改 Router 规则。

具体收益：dependent 的 targeted context 和组织覆盖更多自述、避免 generic URL 扩搜；temporal 的cursor续页提供额外100条与更多主题；forge 的作者归属更准确。但 dependent/context **没有修复 required evidence**，dependent 本身也存在过严使用证据判断，temporal 有错误跨度和无支持频率结论，cite 少写事实，aggregation 多做全库探测。没有清晰、可靠且足以支持扩大路由的净收益。

Confirmed facts：配置、HTTP/Tool/usage、canonical日期与来源、缺失GT。Observed Development evidence：本轮覆盖差距、错误关系、额外消息和开销。Reasonable interpretation：none适合completion可靠性，Planner在某些调查中能改变覆盖与组织，但当前不值得扩大。Not proven：none最终质量优于low、Planned稳定质量提升、无严重回退、人工准确率、fresh泛化、最优预算/路由阈值、真实用户收益或金额成本。

## 7. 停止说明

```text
Planner low vs none evaluation closed
Standard vs Planned engineering validation closed
No further paid Planner experiment scheduled
```

正式16次后停止，targeted repeat=0。发现的当前 required-context 漏失属于已有 Failure Case，非新稳定 regression；cite 的7k遗漏影响完整性；temporal“一天多”是明确事实错误，须保留，但它没有破坏已显式标记的partial范围/零结果/Tool contract，也不改变“限制使用、不扩大路由”的决定。这里不声称错误 harmless，也不声称没有新错误；工程判断是尚无必须通过新增付费复验才能作出保守生产决定的阻断问题。

只在以后出现新的真实、严重并影响生产决策的 Failure Case 时重新评估；不因随机性、措辞、不同工具序列或延迟扩大样本。本次未创建自动任务或实验计划。旧工件、GT和失败记录保留；completed任务留在原目录以保持冻结来源和链接稳定。

## 8. 工程验证

正式请求前全量pytest **659 passed**，Ruff `src tests evaluation scripts`、mypy `src`（115 files）、diff check通过。包含真实SDK schema/source contract、stream原始与normalized ownership、日期fixture、Judge入口日期投影、production none请求、route调用次数、16次AB/BA及create-only preflight失败零付费回归。

根目录额外 `ruff check .` 有62个**既有**问题，21个未改管理/历史脚本与`221f57a`逐字相同；完整诊断在 [ruff-root-diagnostics.json](ruff-root-diagnostics.json)。不能称仓库根扫描全绿，本轮未用忽略规则掩盖它们。

收口后的复检与工件/历史保持核验见 [validation.md](validation.md)。本轮没有付费Judge；确定性Relation测试和mock仅覆盖记录的事实及评审输入。

## 9. Git 状态与集成

在正确的 `codex/planner-p1-stability` 分支延续完整历史链：开始时`221f57a`相对`origin/main=12f2f75` **ahead14 / behind0**，main是本分支祖先。代码与正式执行身份已提交为`14de11f`；收口工件和文档使用正常新提交，不重写历史。

推荐通过该分支向main正常集成，保留原14个提交及本次修复/收口提交。最终交付HEAD、fetch后的origin/main、ahead/behind、push与clean状态由最后一次Git检查给出；报告的execution commit始终固定为`14de11f`，不会随文档提交改写。

### 复核入口

- [manifest.json](experiment/manifest.json)：执行commit、完整Snapshot、设置、Case身份与开销边界。
- [preflight.json](experiment/preflight.json)：原Case/GT、canonical targets、SDKschema、两路输入与Planner序列化。
- [integrity.json](experiment/integrity.json)：正式分母、HTTP、隔离与冻结检查。
- [analysis.json](experiment/analysis.json)：逐tool raw/normalized参数、ToolResult与GT差距、真实usage。
- [source-audit.json](experiment/source-audit.json)：逐case语义判断与停止理由。
- [semantic-review-packet.json](experiment/semantic-review-packet.json)：所有Claim、binding、canonical日期、作者与原时间失败。
- `analyze_closure.py`可从正式raw离线重建analysis/packet，不调用Provider。
