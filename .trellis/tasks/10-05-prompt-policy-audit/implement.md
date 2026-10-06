# 执行计划（第一批已批准）

## 本轮已授权审计

- [x] 读取当前 Prompt、真实 SDK schema/request、Host/Finalizer、相关 spec 与上轮验证。
- [x] 用 P01–P92 覆盖 L7–230，标注六种去向及实际承接条件。
- [x] 产出 PRD、审计与等价重构设计。
- [x] 完成文档覆盖/链接/context 检查与 145 项 baseline 验证。
- 规划文件在检查后提交并推送；推送结果以本轮最终回复为准。

## 第一批产品实现：执行记录与步骤

1. 用户评审 PRD/design/本计划后，配置 context 并 `task.py start`；用户明确要求不使用子代理，由主会话应用 trellis-before-dev/trellis-check 直接实施。agent-runtime-guidelines.md 超过自动注入单文件上限，主会话需从原文件读取相关完整章节，不能仅靠截断注入。
2. 固定 `460259d` 的原 Prompt 与相关 baseline；若 main 已前进，先重新审计相关差异，不能沿旧基线静默实现。
3. 按审计重复簇重写 `prompt.py`：Markdown 层级、每条策略一次、已有 Host enforcement 简述；保留 JSON mode 生成字段与尚需字段指导。生成代码加简体中文注释，关键逻辑逐行解释。
4. 必要时仅压缩 `openai_tools.py` 中跨工具重复文字；保留实际字段说明/Schema/typed input/description 语义。不变更 defaults、工具 surface、capability enforcement 或 Finalizer。
5. 文本断言变化需记录旧断言 → Policy ID → 新语义的对应；运行参数、来源、zero-result、时序与执行路径测试不得因候选失败而放宽。
6. 跑相关 pytest、全量 pytest、Ruff/mypy；随后执行真实 Development 配对，确认模型行为而非仅文字正确。
7. 保存全部失败并定位；关键讨论/清单/时间/身份/零结果回归后才交付，不以更短或更少调用单独宣称质量提升。
8. 评测通过后必要的 spec 同步、工作提交、归档/journal 收尾提交，最后统一 push。真实回归通过前不归档；本轮候选未通过，恢复原版并等待评审。

## 相关契约 baseline 命令

```bash
# 这些真实文件验证当前 Host/SDK/Finalizer 契约；不访问 Provider。
uv run --all-extras pytest -q tests/test_agent_tool_surface.py tests/test_agent_runtime.py tests/test_context_source_contract.py tests/test_temporal_relation_regression.py tests/test_retrieval_budget.py tests/test_evidence.py tests/test_temporal_overview_coverage.py tests/test_temporal_zero_result_integration.py tests/test_recent_messages.py tests/test_sqlite_read.py

# 第一批实现后必须做完整工程检查；本轮文档审计不伪称已执行。
uv run --all-extras pytest -q
uv run --all-extras ruff check src tests
uv run --all-extras mypy src
git diff --check
```

## 真实配对 Evaluation 计划

- 使用上轮讨论 Failure Case + 已暴露 Development Suite；数据备份、query、scope、时间锚、provider/model/effort、路由/冻结 Plan、工具/输出预算保持两侧一致。
- Baseline 必须重新跑当前 `460259d` 条件；历史 `7bac928`/`8805aa2` benchmark 和上轮 AABB 不能替代这次单变量 Baseline。
- 用既有 [real_pair.py](../10-05-discussion-answer-quality/real_pair.py) 与生产 Application 入口为执行依据；脚本如需改实验顺序/输入，改动必须显式说明并保留实际请求。runner CLI 参数以实际 help/源码为准，不在规划杜撰新命令。
- 用交错配对并保留重复；重点核对推荐/补充是否进入 context 和答案、作者/日期/关系、资源链接/类别、scope、partial/empty 与无意义重复调用。精确零命中不能被表述成整个时间窗无消息。
- 尽可能盲评；已暴露案例和非人工 Judge 必须标明，不宣称 blind Holdout/generalization。无需新机械总分；逐 finding 与 Trace 核对。
- 明确记录真实请求体积与 token/latency、cold/warm/cache 条件；不把主 Prompt 字符减少等同于完整请求成本减少。

## 第二批及 Deferred

Schema 非空/非负/互斥只有在真实需求与 provider contract 证明有价值后补，Host 校验始终保留。Structured Outputs、日期解析/no_result 语义更改、全局去重 ledger 需独立评审与验证。本次不新增 fallback、retry、repair 或依赖。


## 实际完成

- [x] 用户批准第一批并 start，主会话直接实现。
- [x] 完整候选的 Markdown 分层、同义去重、Policy 映射与五项断言 patch；回归失败后运行源码恢复原版。
- [x] 145 相关测试、662 全量测试、Ruff/mypy、Trellis context 与链接检查。
- [x] v1 32 次 + 最终修订14次真实配对，23/23 初始 HTTP 非策略 body 相同。
- [x] 保存全部失败和候选版本，未扩大预算、修改 Provider 或新建 fallback/guard。
- [x] 现有责任与评测边界沉淀到 runtime spec。

全面语义等价没有证实，宽讨论仍漏推荐、精确查询答案有时序错误，详见 [validation.md](validation.md)。当前未通过等价门禁，任务继续 in_progress；候选保留供评审，不扩大预算、增加重试或样例补丁。

## 2026-10-06：低成本小步优化（本轮用户直接授权）

旧大改计划与默认付费配对不再用于本轮。主会话直接实施，沿用 in_progress task，保留历史失败与完整候选。

最小缺口：现有 EvaluationRunner 默认 repetitions=1、支持生产 query 与冻结 snapshot，但没有 policy 筛选、冻结结果复用、probe 提前终止和硬 Provider 计数。复用 suite_tags、EvaluationRun/Trace/Review，不建第二套 Agent。实验 runtime 子类只在既有 builder 注入候选及首调用拦截，正式 runtime 不增加 mode 分支。

预期文件：新增 prompt screening module/CLI、fixture/tests、责任矩阵和迭代日志；P01 仅 lexical limit 契约与独立候选。逐字保护讨论/negative/time/stop/routing，默认窗口、预算、Provider、Finalizer 不改。

关键模块七问：输入是当前 case/query/scope/snapshot 与生产 Prompt；输出是可复核 screening artifacts；依赖正式 Application.query 与既有 SDK/Trace；成功是明确拒绝非法 limit、预算内执行与可复用冻结结果，不宣称语义等价；失败保留原异常/Trace、不得覆盖 artifacts；验证由真实 SDK/SQLite、ScriptedModel 与 fixture 完成；演进只在受影响 policy 的最低 tier，release 才 fresh paired gate。

分离提交：A00 只读审计；H01 评估能力；F01 fixture；P01 一个参数职责迁移。每轮真实 API 预计/最多均 0。Prompt 候选在 L0 接受后仍需 release gate，不替换 production。禁止使用之前失败候选作 baseline。

## 当前会话连续迭代授权

用户要求完成一轮后自主分析并进入下一轮，不请求继续确认。保持每轮唯一主要scope、独立commit和原失败记录；本会话预计/最大真实Provider请求均0。

先按P02 lexical context非负 → P03 semantic dense_top_k正值 → P04 find_members query非空逐条核验，前一轮验证通过才开始下一轮。只触及对应SDK字段、零Provider contract tests、累计候选与log；production Prompt不变，discussion/negative/time/stop/routing字节不变。再依据实际剩余缺口选择下一轮，不顺带改其它参数。

继续自主进入P10 recent.limit、P11显式context窗口合法性；每轮最大Provider0。依据剩余真实owner选择下一项，不以一次工程收口作为等待用户确认的边界。

V01为P15批次单fact首工具筛选独立预算2（每侧1），实际2已用完；两侧HTTP除Base一致，参数有差异，L1 inconclusive。不得继续付费补统计；后续零成本fixture/已承接机械规则另轮执行，production语义gate仍Pending。
