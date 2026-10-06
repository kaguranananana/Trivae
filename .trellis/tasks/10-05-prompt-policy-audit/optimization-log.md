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
