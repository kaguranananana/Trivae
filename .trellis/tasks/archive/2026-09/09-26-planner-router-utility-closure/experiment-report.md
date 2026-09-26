# Planner Utility → Jev Router Utility：针对性工程与真实验证

## 2026-09-27 后续状态（补记，不改写 2026-09-26 当时记录）

归档后完成了 15 道盲审与揭盲人工复核，并对新增四道 Case 进行 GT applicability adjudication。`evaluation/planner-utility/adjudication-v1.json` 中有 6 道 Case 绑定当前 v2 Snapshot、Variant 与真实 run IDs：`dev-zero-empty-3` 和 `dev-context-archify` 各有两组 paired observation，另有 `pu-dependent-mattpocock`、`pu-count-utc-day`、`pu-rank-utc-session`、`pu-aggregate-utc-types` 各一组。当前 v2 正式结果是 `planned_beneficial=0`、`standard_preferable=2`、`indifferent=4`、`uncertain=0`。另外 9 道是旧 Variant 的历史人工观察，没有填入当前 v2 的正式 run 绑定；15 道跨版本合计 `0 / 4 / 11 / 0` 仅为人工观察汇总。

四个新增 `pu-*` Case 的 GT applicability 均由人工 Accept，原 GT 事实未改。`pu-dependent-mattpocock` 仍标明 target 非 corpus-exhaustive、required context 是人工检查点、retrieval 为 partial/truncated；未命中单条 target 不自动等同答案错误。人工逐题理由见 `evaluation/planner-utility/human-review-2026-09-27.md`。

累计 Provider ledger 已从本地 9 份 raw batch、canonical Trace 起点与 Jev 路由观测重建：22 条 raw run、74 次 provider invocation（Planner 11、Runtime 61、Existing Router LLM 0、Jev Decisions 2）。事件内容与 `provider-ledger-final-after-all-pu.json` 一致；重建与存档只在同一时刻事件的稳定排序上不同。Planner 实际返回 input/output usage 为 5,356 / 16,028 tokens；Runtime 为 620,232 / 24,962 tokens；DeepSeek cost unavailable。Jev Decisions 返回 input/output 为 1,212 / 72 tokens，实际返回 cost 合计 0.000050904。此前 47 次是 dependent / count / ranking / aggregation v2 运行之前的归档阶段累计数，不代表当前累计数。

当前 v2 的 16 条 raw run 与 Evaluation run、Evaluation result、canonical Trace identity 对齐，覆盖 6 道 Case 的 8 组 paired observation。四个新增 Case 的 GT applicability 保持 Accept，未改写 Holdout 或 canonical 数据。这次裁决仍没有正向 Planned treatment 证据。Jev production 保持 `shadow`；没有 Holdout 实验，也没有 rollout 或“复杂问题 → Planned”的依据。下一阶段单独建立 Retrieval Degradation Root-Cause task，先逐层对照 dependent 与 archify 的生产 Trace，再决定是否需要最小通用修复；本报告中的历史实验数据和原始结论保持原样。

## 身份与范围

- 起点 commit：`d46b8f3`；Phase A 实现 commit：`4524778`。第一冻结实验环境 commit 为 `112ebb5`，第二冻结实验环境 commit 为 `246112b`；第二版本的 Planner/Runtime 提示词代码 commit 为 `29522e1`。
- 两版本都使用当前 473,236-message canonical Snapshot、同一 lexical/semantic index、官方 DeepSeek `deepseek-flash`、相同 Tool/Runtime/Evidence 主链路。Standard/Planned Variant 各版本除 ID 外只在 `execution_override.forced_route` 不同。forced route 绕过 Existing Router LLM；Jev 使用隔离的 route-only runner，不改变生产 `shadow`。
- 这次只有 2 条已暴露 Development Case 被真实 forced 运行：`dev-zero-empty-3@v2`、`dev-context-archify@v1`。新 dependent、count、rank、aggregate Case 已构建并通过契约检查，未发起真实 treatment。旧 37×2、Holdout 和 16 Case Router 诊断 artifact 未修改。

## zero-result 根因与修复边界

历史主实验及两次 repeat 中，Standard 3/3 valid + verified-zero，Planned 0/3 `INVALID_FINAL_OUTPUT`。Planned 的 SoftPlanner 建议额外调查；Runtime 先从 `get_recent_messages` 获得完整零条结果，后取 schema 和 SQL 聚合行，最终仍输出 `kind=no_result`。首次真正阻断位于 Evidence finalizer：它把数值统计行当作候选消息事实，否定了已有的完整空窗证明。这不是 Retrieval miss、Planner Provider 失败或 JSON 解析失败。

Evidence 修复只在明确时间窗的完整零条 `get_recent_messages` 存在时允许数值 SQL 聚合并存；SQL-only、partial/error、实际消息、普通 SQL 行及同窗正计数冲突仍拒绝。确定性回归测试通过。第一冻结版本的第二对真实运行出现完整零条检索后继续 SQL 聚合，Planned 成功 verified-zero，证实了该子路径。

第一冻结版本第三对暴露另一条路径：Plan 建议先 `get_schema` 再 SQL 日统计/当日计数，Runtime 没有调用 `get_recent_messages`，最后 `no_result` 缺少正证明而失败。`dev-zero-empty-1/2` 的 SQL-first 观察同属此风险，不能通过放宽 finalizer 合并修复。第二版本在 Planner/Runtime 通用提示词明确“按日问是否有人发言和聊什么先检索，SQL count 不能单独证明空结果”，未按 Case ID 特判。第二版本一对成功 Plan 的观察拿到完整空检索并 verified-zero；另一对 Planner 以 `provider_length` 截断（输出 token 达 2048、无正文），随后按原契约降级，不能算成功计划后的验证。

| 冻结版本 | Standard verified-zero | Planned verified-zero | Planned 成功 Plan | 关键限制 |
| --- | ---: | ---: | ---: | --- |
| 第一版本，3 对 | 3/3 | 2/3 | 3/3 | 1 次 SQL-first，无检索证明 |
| 第二版本，2 对 | 2/2 | 2/2 | 1/2 | 1 次 Planner `provider_length` 降级 |

结论：**聚合行误拒已修；SQL-first 风险尚未得到 2–3 次成功计划后的稳定验证。** 不把第二版本的 2/2 说成稳定修复。

## Planner-specific Dataset 与人工裁决

`planner-utility-development@v1` 有 15 条已暴露 Development Case：11 条复用已有 GT，4 条新 CaseBundle 从当前 canonical SQLite / 既有证据构建。覆盖 explicit context recovery、dependent share→feedback、verified zero、direct lookup、lexical、semantic、count、ranking、aggregation、ordinary summary 和大时间窗控制。新数值事实由 SQLite 本地复核；新增 query 的 GT 适用性与答案语义仍需人工审阅。manifest 逐条记录来源与 workload hypothesis，不以 candidate 类别写 route label。

15 条 treatment review 初始均为 `pending` / `uncertain`。人工结论必须绑定 Snapshot、两路 Variant/run、reviewer、时间、理由，并分轴记录 answer correctness、evidence completeness、context recovery、groundedness/citation、zero-result correctness 和 reliability。Latency、token 与实际返回 cost 作为 trade-off，不能覆盖质量判断；旧 16 条 route 分类标签不作为 Planner treatment GT。

## 真实 targeted observation 与 Router Utility

`dev-context-archify` 历史 repeat 的自动方向为 better/better/same；这次两对分别为 Planned worse、same。第一对 Standard evidence recall/context recovery = 1.0/1.0，Planned = 0.5/0.0；第二对双方 = 0.5/0.0。这说明历史条件收益不稳定，不能填 `planned_beneficial`，仍待人工盲审答案和证据。

Jev 对 `dev-zero-empty-3` 与 `dev-context-archify` 各做 1 次真实 Decisions 请求，两次均可用、无降级、预测 `standard_execution`。Router Utility runner 将真实 forced raw、Evaluation DB、当前 Snapshot、Jev route 与待裁决模板连接，输出 2 份 create-only 分析。两条 direction 都是 `unadjudicated`；不能由 Jev 预测或自动指标计算正式 accuracy。Rule gate 与 Provider 分开统计，两份结果中的 2 条均由 Jev Provider 决定。

7 对 forced run 形成 14 条 raw；对应 14 Evaluation run、14 Evaluation result、14 canonical Trace，身份逐项对齐。顺序反转在两轮之间交替，实验 order manifest 首次请求前 create-only 落盘。历史配对顺序未改写。

## Provider 成本账本

Phase A 零次付费。真实运行后逐小批读取 Trace 请求起点、Planner observation 与 Jev route，重建 ignored 本地 `provider-ledger-final.json`；失败和截断照计。下表仅含本任务新增请求，历史实验不在分母。

| Provider 请求用途 | 次数 | 真实返回 usage |
| --- | ---: | --- |
| DeepSeek Planner | 7 | input 3,312 / output 10,408 tokens |
| DeepSeek Runtime | 38 | input 365,328 / output 13,221 tokens |
| Existing Router LLM | 0 | forced route 绕过 |
| OpenRouter Jev Decisions | 2 | input 1,212 / output 72 tokens；实际返回 cost 合计 0.000050904 |
| **合计** | **47** | DeepSeek 货币 cost unavailable，未推算价格 |

每对 forced run 的最坏上界为 Standard 8 Runtime + Planned 8 Runtime + 1 Planner = 17 次；初始、每次追加前均检查剩余额度。47 次超过 30–40 的正常目标，是因为第一版本 SQL-first 再现、第二版本一次 Planner `provider_length` 以及 context recovery 与历史方向冲突，符合 Phase C 的追加条件。剩余 13 次不足完整下一对的 17 次上界，停止新增 DeepSeek 调用；已有 2 次成功 Jev route 足以验证新链路，未继续增加样本。总量低于 60 次 hard ceiling。无自动重试。

## 工程结论与下一实验

- 生产架构保持 Rule-first Router、一次性 SoftPlanner、两路共享 Agent Runtime，Jev 继续 `shadow`。没有引入 workflow、step executor、replan 或第二 Agent。
- Router Utility 基础设施及 15 Case Suite 已准备；真实证据仅 2 条未裁决 smoke，无法支持 production rollout、fresh generalization 或普遍 Planner utility 结论。
- 下次先人工审核新增 GT 和现有 treatment pair，再在新干净 execution commit 重新捕获 Environment。若对 15 Case 各做 1 对 forced treatment 和 1 次 Jev route，最坏上界是 `15 × (8 + 8 + 1 + 1) = 270` 次；需要独立批准的新预算。重复 2 轮则最坏 540 次。这些正式实验**已准备但本轮有意不执行**：`Prepared for larger paid evaluation; intentionally not executed under current cost budget.`

本地原始答案、Trace 正文、Evaluation SQLite、Jev response projection、review packet 和逐次调用账本均位于 Git 忽略的 `data/evaluation/planner-router-utility/2026-09-26/`，没有进入版本控制。用户未要求 push，本轮不 push。

| 收口项 | 状态 |
| --- | --- |
| Planner zero-result regression | 聚合行误拒已修；SQL-first 稳定性未解决 |
| Planner-specific utility dataset | 15 Case ready；4 条新 query 的人工 GT 复核 pending |
| Treatment utility adjudication | contract ready；15/15 pending human review |
| Router Utility infrastructure | runner、identity preflight、analysis ready |
| Real Router Utility evidence | 2 条未裁决 smoke；无 accuracy 结论 |
| Jev production mode | shadow |
| Large paid experiment | 已准备命令，本轮因成本上限有意不执行 |
