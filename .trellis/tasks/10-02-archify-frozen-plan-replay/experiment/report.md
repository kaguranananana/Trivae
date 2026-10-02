# Archify 冻结 Plan 生产 Runtime 重放报告

本轮固定两份有效 Plan 各重放两次，4 次生产 E2E 全部完成。**两次 none guidance 均未重现上轮的“唯一 star 数值”矛盾或“真的假的”反应错配。相同 low guidance 的两次运行则分别漏取 7k 上下文、把相隔约两周的 7k/9.5k 消息写成同一天。**

因此已经观察到相同初始输入下的下游执行方差，不能把上轮 Archify 错误归为 none Plan 的稳定、必然效果。这不是质量等价证明，也不撤销上轮 Gate A：历史错误仍存在，temporal Case 本轮没有重放。

## 1. 身份、范围与隔离

| 项目 | 事实 |
| --- | --- |
| Execution commit | `361a38e0dc78db4fdfe59b6969bfac454de59700` |
| 工作树 | 起点 clean；执行时新增未提交 replay runner/tests/task，逐字副本在 frozen/ |
| Timestamp | 2026-10-02T08:40:22.088+00:00（Asia/Shanghai 16:40:22） |
| Source | 上轮 e2e/raw/dev-cite-archify-low-a1.json 与 none-a1.json 的已验证 Plan |
| Query | archify 项目最近发展怎么样？star 数有被提到过吗？ |
| Snapshot | 原 473236 条消息、14 sources，首末时间戳 1753011800000 / 1786847688000；全部数据身份字段相等 |
| Provider/model | 官方 DeepSeek / deepseek-flash |
| 本轮 treatment | 固定 low-origin Plan / none-origin Plan 的 rendered guidance |
| Runtime | 两侧均为生产 low reasoning、8 turns、3 tool rounds、16384 output budget |
| 顺序 | seed=20261003：low-r1 → none-r1 → none-r2 → low-r2，两个 AB/BA 块 |
| 请求 | 4 logical runs；**16 HTTP requests，全部 downstream；Planner HTTP=0** |
| Retry / timeout | 0 / 0，无替换、补跑或追加 Case |

low/none 仅是 Plan 的来源标签；不能把本轮写成新一轮 reasoning_effort A/B，或者再比较 Planner latency。既有 Planner protocol 被 FrozenPlanner 实现，返回原 Plan；没有伪造历史 Provider observation。生产 Orchestrator 使用同一个 render_plan_guidance，生产 Runtime 自主调用 Tool，生产 Finalizer 生成正式答案。

预检对生产 Agent builder 的 instructions/input/model settings/tool schemas 比较，仅 guidance 不同。四次真实首个 HTTP body 剥离精确 guidance 后，与上轮初始 Runtime body 完全一致；**同一 guidance 下两次初始 HTTP body 逐字段完全相等**。每次新 conversation，同一预热 embedding；Provider cache 保留生产语义并记录，不能视为彻底消除顺序影响。代码、Case、两份来源 raw Plan 和 Snapshot 在每次执行前后核对一致；未修改任何生产源码/prompt/schema。

Snapshot created_at 是每次 materialize 的观测时间，本轮只排除这一字段比较，其余完整身份全部固定。它不表示数据更新。预热耗时单独保存，不进入 treatment latency。

## 2. 完成与逐次结果

| Run | E2E | HTTP | Tool calls / errors | 检索 unique 消息 / selected 消息 | 主要语义结果 |
| --- | --- | ---: | --- | --- | --- |
| low-r1 | completed，13.214s | 4 | 6 / 2 | 36 / 5 | 仅报告 9.5k；没取到 7k/画廊上下文；把 30 天区间称“两个月” |
| none-r1 | completed，13.561s | 4 | 6 / 2 | 152 / 10 | 正确报告较早 7k、较晚 9.5k；区分其它项目 star 数；未引用“真的假的”作反应 |
| none-r2 | completed，10.924s | 4 | 5 / 2 | 41 / 8 | 正确报告增长、赞助、画廊和插件；未出现原两处错误 |
| low-r2 | completed，13.642s | 4 | 4 / 1 | 29 / 7 | 7k/9.5k 均命中，但 Claim 与 Evidence 将两个日期写为“同一天” |

自动指标四次均为标注 Evidence 3/3、expected fact 1/1、valid answer=1。这些目标主要验证仓库 URL 与三个命中消息，不覆盖全部 star/时间/引用 entailment。自动通过不能盖过人工发现的时间错误或相邻上下文遗漏。

本轮不生成混合总分；语义判断由 root 对完整原始 ToolResult 与 Citation 逐条核对，**是未盲的事实审计，不冒充独立盲审、human adjudication 或 numeric citation precision**。machine facts 与人工解释分别保存在 analysis.json / manual-audit.json。

## 3. 原错误是否复现

### 原 none 的两处错误：本轮 0/2 次重现

none-r1 与 none-r2 都把 7k、9.5k 作为前后两次数值报告，没有再称 9.5k 是唯一数值。两次都检索到了 `qq:1039179741:7670740394980322206`（“真的假的”），但均未选择该条作 Citation，也未把它写成 Archify 反应。因此本轮的改善不能解释为“错误消息没有被检索到”；变化确实发生在 Evidence selection / synthesis。

这个反应消息在 2026-08-06T02:30:24Z，9.5k 公告在 02:40:20Z，相差 596 秒且无 reply relation。当前证据不支持把它认作对稍后公告的回复。

### low-r1：检索路径遗漏，不是先读到再丢弃

初始 archify 检索限定 archive_latest 最近 30 天、context_before/after=0，取得 5 个 named hits；第二次 archify AND star 检索为 0。之后围绕 9.5k 公告和较晚插件公告 deepening，没有扩展早期仓库分享，所以“已经7k了”“加了个画廊”均未进入完整 ToolResult。

因此只报告 9.5k 的直接原因是 retrieval/context coverage 缺口，不能说 Answerer 删除了已取得的 7k。三个标注目标本身仍全部命中。答案另外把 2026-07-17 至 08-16 的 30 天称为“两个月”，是独立的时长表达错误。

### low-r2：数据正确，时间关系在 Evidence/Answer 中被改写

同一 Plan 的第二次初始 archify 检索带 context_before/after=2，直接取得：

- `qq:1039179741:7665652145777619588`：“已经7k了”，**2026-07-23T09:25:23Z**。
- `qq:1039179741:7670742957499269309`：“archify 9.5k了，项目收到了赞助”，**2026-08-06T02:40:20Z**。

两条相隔 13 天 17 小时 14 分 57 秒。Claim-2 却写“在同一天的更早消息”，Evidence e2 finding/criterion 也写“同日”。绑定确实包含这两个正确 canonical messages，因此能定位到 **Evidence relation / Answer synthesis 的时间关系错误，非 Retrieval 时间解析错误**。

low-r2 还从 archify AND star 的全库零命中概括“群内没有人直接用 star 一词讨论 archify”；该零命中只证明同条消息中的 exact-term AND 未命中，不能排除跨消息语境或其它指代。这列为 unsupported broad negative claim，不宣称已找到反例证明它为假。

## 4. Tool contract 的新增归因

本轮 21 次 Tool calls（low 10，none 11），全是 lexical/context，无 semantic；7 次失败全部是 source handle 填错参数，4 个 runs 均出现。正确的调用链是：

`Provider arguments {message_id: "m1-1"}` → canonical lookup → MESSAGE_NOT_FOUND

`Provider arguments {source_id: "m1-1"}` → 已有 SDK handle resolver → normalized canonical message_id → successful context

**Normalized Trace 中看到 canonical ID，不代表模型自己生成了 canonical ID。** 本轮和上轮全部相关恢复调用的原始 Provider arguments 都是 source_id；映射由已有 adapter 完成，不是新的 fallback，也不是 transport retry。

实际 schema 两个字段只有 title/type/default；Tool description 合并写 message_id or source_id，没有说明 mN-K 必须填 source_id。Search 的模型可见结果公开的是 source_id。当前证据可确认参数选择错误和契约表达有歧义，尚不能证明仅调整说明就能彻底消除失败。本轮不修改 schema 或加入 message_id→source_id 静默兼容。上轮“canonical calls”指归一化后的执行参数，此处补充 Provider 与 normalized 两层的区别。

none-r1 的额外全库 star 检索为 partial，带来无关项目数字和更多 input；答案正确区分了对象，但这些附加检索不能当作 Archify 质量改善的必要步骤。none-r2 没有该额外检索仍完成主要目标，显示同 guidance 下检索策略也有变化。

## 5. 性能与成本代理

| Plan 来源 | mean E2E | HTTP | input | output（含 reasoning） | reasoning | cached input | total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| low | 13.428s | 8 | 82274 | 4041 | 1078 | 60288 | 86315 |
| none | 12.242s | 8 | 122946 | 3588 | 1348 | 74368 | 126534 |

两侧都运行 Runtime low，本轮 reasoning usage 全部实际返回。cached 是 input 子集，reasoning 是 output 子集，不重复相加。none-r1 的泛 star 检索拉高 input；同 guidance none-r1 total=84808、none-r2=41726，相差超过一倍。样本极小且有 cache/Provider 方差，不能宣称哪个 Plan 稳定更省。**Monetary cost unavailable**。

## 6. 结论与下一步

1. 本轮未复现原 none 的两条 Archify 错误，不能认为 none Plan 必然生成这些错误。
2. 相同 first HTTP body 下，两侧都出现 Tool 参数/anchor/context 范围变化，none 还出现额外泛 star 检索。因此 **下游执行方差有直接证据**；并非所有差异来自新 Planner 输出，因为本轮根本没有生成新 Plan。
3. low 两次都执行双 lexical 和最近 30 天，说明 guidance 对路径可能有影响；但次数不足，不能把某个句子认作已确认稳定因果机制。
4. 这次重放没有固定 ToolResult，不能将全部波动进一步归为“仅 Answerer 随机性”；Tool selection、arguments、Evidence selection 和 synthesis 都有变化空间。
5. 上轮实质错误和 Gate A 保持，尤其 temporal 的昵称/消息错误本轮未验证。不得据此重开全量质量确认或宣布 none 等价。
6. 下一步应进入独立修复：优先用本轮 4/4 重复的 source_id/message_id 参数误用建立 provider-free Failure Case，修正 Tool 参数契约表达；另以 low-r2 的真实两个日期作为事实关系回归案例。暂不追加付费重放，不当场加入兼容或语义 fallback。

## 7. 工件与复现

manifest / preflight / plans / run_order / integrity 固定身份与输入；attempts/runs 各 4 条；HTTP requests/responses 各 16 条；Evaluation runs/results 各 4 条；Trace 共 4 条、262 events、16 completed model turns。raw 保存公开 Provider 输出、完整 ToolResult、AnswerArtifact 和评测；隐藏 reasoning 正文不归档。

每个 Claim 的 canonical source IDs、归一化 Tool arguments 与原始 Provider arguments 都在 analysis.json。人工判断与具体句子单列 manual-audit.json。自动重算：`analyze_replay.py <experiment-dir>`，不调用 Provider。

正式执行前后 runner/生产源码/Case/源 Plan 逐字冻结。首次 provider-free 预检误把 snapshot created_at 当数据身份，已定位并修复，0 formal attempts / 0 DeepSeek requests；失败目录保留。SDK ModelSettings 正式 JSON 投影问题在无 Provider 测试中修复。无正式 harness/provider failure，只有真实 Tool 参数错误。

工程检查：648 provider-free tests 通过；Ruff 与 mypy src 通过；分析重算与 diff check 通过。最终检查详情见任务 validation.md。

工程事实索引：选择既有 Planner injection 是为移除 Planner 生成方差，同时保持生产 Tool/Evidence/Answer；没有固定或 mock 正式 ToolResult。HTTP 原始参数与 normalized Trace 的区别解释了恢复调用的真实 ownership。规模仅 4 runs / 16 requests；所有因果和成本结论受限。未来只有修复目标明确、provider-free 回归完成后，才另行设计真实验证。
