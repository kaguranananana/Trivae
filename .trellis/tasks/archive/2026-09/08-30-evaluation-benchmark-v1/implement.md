# Implementation Plan: resume-benchmark-v1

> Revision 2：吸收 review 修正——新增 Stage 1.5 calibration pilot gate；Stage 3 末尾「冻结 commit 全 dev rerun」；Stage 4 改为 holdout 一次定稿、结果封存、修复进 v2（删除降级替换重跑流程）。
> 四阶段：Measurement Substrate → Benchmark Dataset → 干净 Ablation → Judge + 冻结后 holdout。
> 每阶段末尾有 review gate；gate 未过不进入下一阶段。
>
> **Gate 4 收口（2026-09-25）**：Gate 3 review、final freeze、v1 holdout 封存、v2 recovery validation、fact index 与面试证据审计均已完成。Gate 4 以“结果和限制可追溯”为通过条件；v1 holdout 没有质量值，Tier 2 没有人工逐条 adjudication，二者均不得升级成质量结论。本轮不重跑 benchmark、不改 Evaluation 或生产逻辑；检查通过后使用 Trellis task 工具完成归档。
>
> **历史快照（2026-09-08；已由下方 Gate 4 收口 supersede）**：**Human GT Adjudication Gate、Gate 2
> Development Freeze、Module Retrieval、Failure-driven iteration、最终 clean 37×5 和 Tier 1
> / Tier 2 Development Evaluation 均已完成**。47/47 case 已人工裁决（Accept 26 / Modify 21 /
> Reject 0；calibration 10 / development 37），deterministic audit 为 green（47 cases / 47
> adjudicated / 0 error / 0 warning，`data/evaluation/benchmark/gt-audit-stage3-final.json`）。
> Gate 2 使用 ordered versioned Case identities + canonical Variant configuration text 作为可复现
> identity；execution commit 为 `b1f7b78...`，冻结后的 clean execution commit 为
> `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`，根因修复后的 post-fix clean execution commit 为
> `f24775099cb2314772c7d409341e8ebceeceac23`。最终 headline 只使用 Development 37×5=185
> runs；calibration 排除，正式 holdout 已完成一次性运行。Gate 3 candidate commit 为
> `8805aa2bf58fcb2702817d54afe96bd819645db2`，已在干净 worktree 捕获 Environment 并完成新的
> Development 37×5 acceptance；D-only Judge 为 provisional partial，人工 packet 已完成核验。
> 该历史状态中的“不要 archive 本任务”只描述 2026-09-08 当时的 Gate 4 前停止点，不适用于本次完成的 Gate 4 收口。

---

## Stage 1: Measurement Substrate

### 1.1 ExecutionOverride 最小扩展
- [x] `ExecutionOverride.context_window_limit: int | None = None` + 校验（非 None 时 ≥0）+ to_dict/from_dict（旧 JSON 缺字段 → None）
- [x] `AgentRunRequest.context_window_limit` 新可选字段；`QueryRequest.to_runtime_request()` 贯通
- [x] `RuntimeContext.context_window_limit` 贯通；openai_tools.py 中 lexical_search / semantic_search / search_messages 输入构造点钳制 context_before/after；tool 完成 payload 记录 `context_window_applied`
- [x] `get_message_context` / `get_recent_messages` 不受影响（显式验证）
- [x] 现有全部测试零改动通过；后续完整 pytest 与 `tests/test_benchmark.py` 有回归覆盖

### 1.2 Run projection 扩展
- [x] `checks.query_result_snapshot` 增加 `retrieval_calls`（per-call：direct_hits 前 50 带 rank / expanded_ids 前 50 / counts / coverage_status / truncated / recorded_depth / omitted_ids；per-run：call cap 8 + `retrieval_calls_omitted`）与 `evidence_sources`（bounded）
- [x] `checks.tool_result_facts` 复制清单加入 `context_window_applied`
- [x] 新 deterministic check `context_expansion_override`（声明 limit=0 ⇒ 所有 retrieval call applied=0）
- [x] 深度语义落地：`not_observed_within_recorded_depth` 状态可供 failure 分类消费

### 1.3 Benchmark 模块
- [x] `benchmark/gt.py`：criterion 约定解析（三轴 expected_coverage_status / expected_truncated / expected_zero_result 互斥与一致性校验；expected_fact 为 alias 列表）
- [x] `benchmark/environment.py`：BenchmarkEnvironmentManifest（canonical snapshot_id + lexical identity + semantic serialized identity + git commit）+ pre-run gate 三查
- [x] `benchmark/retrieval.py`：**薄 adapter**——Case → RetrievalQuerySet → 现有 RetrievalAnnotationWorkflow 执行路径 → RetrievalRunRecord → GT 评分；不重写 invocation/ranking/coverage
- [x] `benchmark/metrics.py`：Tier 1 指标（scope 策略：exhaustive→corpus / partial→target / unknown→unavailable；MRR@K 显式 cutoff；Expected Fact Answer Coverage 只查 answer_text；Coverage 三轴各自独立；Execution Completion Rate / Valid Answer Rate 无条件指标；provider failure 剔除条件分母但单独呈现）
- [x] `benchmark/report.py`：JSON + Markdown（overall / per-category / per-split；full 列做 commit 一致性断言）
- [x] `benchmark/failures.py`：acceptance-condition 触发 + 单 Run observation category 判定链（semantic_miss 不在此层）
- [x] CLI：`trivae eval benchmark ...` 编排子命令

### 1.4 Stage 1 测试
- [x] Unit：各 scope 的 Recall@K / Hit@K / MRR@K、Evidence Recall、Context Recovery、Coverage Status Accuracy（三轴独立）、Truncation Accuracy、Expected Fact Answer Coverage（answer_text-only 假阳性负例）、False/Verified Zero-Result、无条件完成率、GT 解析与一致性校验、environment gate、override 钳制 contract
- [x] Integration：fixture DB 上 fixed snapshot + fixed case 走通 Runner→projection→metrics→report；override=0 ⇒ expanded_ids 空且 check passed；drift/identity mismatch 拒绝；retrieval_calls 全 run cap 生效
- [x] 全量 `pytest -q`；`ruff check` / `mypy` 在 Stage 1 closure 及后续 closure 中通过

### 1.5 Calibration Pilot Gate（人工批量审核之前）
- [x] **B — 校准切片已按 Calibration 实施**：10 个 Calibration cases 运行通过；实际覆盖 exact_lexical、semantic_paraphrase、context_recovery、temporal_overview、zero_result 五类。原计划要求 pilot 六类全覆盖，但 pilot 未含 citation_evidence；最终 Development 六类齐全并含 citation_evidence，故本项作为历史计划差异披露，不将其伪称为 pilot 已覆盖。
- [x] 10-case 校准切片走通 GT/parser、retrieval、A/B/C/C2/D 五 Variant、projection、metrics 与 report；五个 Variant 各 10 条 raw run。
- [x] 校验 GT / projection / unavailable / failure / report contract；实现问题在批量 Development 前修复。
- [x] 已完成 Measurement Substrate 校准 gate；证据见 `pilot-*-v1` artifacts、最终 Development reports 与测试套件。

**Gate 1（用户 review）**：Stage 1 代码 + pilot 结果面审；确认指标定义、投影 schema、报告形态。

---

## Stage 2: Benchmark Dataset（40~60 case）

### 2.1 Snapshot / Environment 固化
- [x] pre-run gate 通过 → 写 `data/evaluation/benchmark/environment.json`（完整版）+ `evaluation/snapshots/resume-benchmark-v1.json`（redacted 提交版）
- [x] DatasetSnapshot 本体保持零改动（绑定仍走 case.dataset_snapshot.snapshot_id）

### 2.2 Case 构造
- [x] 汇总真实问题来源：dogfooding 历史问题、归档 failure cases（2699/100、CJK 0-hit、合法空窗等）、数据挖掘候选
- [x] LLM 辅助生成 candidate question + candidate evidence（三路检索）→ provisional Case
- [x] exhaustive 证明仅对 predicate 可枚举类执行（FTS+LIKE 全库扫描）；semantic/target 类如实标 partial
- [x] 生成人工 review markdown（query + 候选摘要 + 建议 GT + 修改槽）
- [x] **用户逐条审核** → adjudicated=true（2026-08-31 完成：47/47，Accept 26 / Modify 21 / Reject 0）；`why_relevant` 无正文泄漏检查

### 2.3 冻结
- [x] development cases（含已知 failure regression）→ `evaluation/cases/benchmark/dev/`（提交）
- [x] `evaluation/suites/resume-benchmark-dev-v1.json`（提交；裁决后 suite version→2）
- [x] 冻结记录：时间、ordered versioned dev identity、canonical Variant configuration text（提交：`evaluation/snapshots/resume-benchmark-v1-freeze.json`）
- [x] **本阶段不创建任何 holdout 文件**（holdout 推迟到 Gate 3 冻结后的 Stage 4.0）
- [x] 无效条目预声明规则写入冻结记录：仅 (a) GT 与 Snapshot 事实矛盾 (b) 重复 (c) 数据损坏 三种情况允许替换，且必须记录原因
- [x] 数量口径：Development headline = 37 cases；calibration（10）排除；holdout absent，不生成 53~60 的 full split

**Gate 2（用户 review）**：dev GT 逐条审核完成；dev 集冻结确认。

---

## Stage 3: 干净 Ablation（只看 dev）

### 3.1 Retrieval-only（确定性，不调 LLM）
- [x] Type A/B case × {lexical, semantic} 全量跑 → Recall@5/10、Hit@K、MRR@10（exhaustive→corpus scope；target→Target Recall；`data/evaluation/benchmark/stage3-module-retrieval.json`）
- [x] context ablation（module 层 before/after 0 vs 生产默认）→ Context Recovery（retrieval 侧；无 required context 的 query 显式记为 not applicable）

### 3.2 End-to-End（真实 LLM，1 rep，dev only）
- [x] pre-run gate → dev case × A/B/C/C2/D 五 variant（最终 clean = 185 runs）
- [x] Evidence Recall / Context Recovery / Coverage Status Accuracy / Truncation Accuracy / Expected Fact Answer Coverage / False+Verified Zero-Result / completion rates
- [x] latency / tool calls / tokens 诊断聚合
- [x] 跨 Variant 归因（B−A / C−B / C2−C）在 report 层产出；D 与其他 Variant 明确为多变量差异

### 3.3 迭代纪律（只允许 dev）
- [x] 每修复：保存 failure artifact → root cause → 通用机制修复 → 重跑同 case → before/after 留档（first / targeted / final artifacts 已保留）
- [x] 禁止针对单 case 特殊逻辑；禁止查看 holdout（目录隔离 + 纪律）

### 3.4 冻结 Rerun
- [x] 末次修复后：**在 `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f` 上完整重跑整个 dev suite**（全部 variant），作为最终 dev 数字
- [x] 根因修复后再次执行 clean 37×5：`f24775099cb2314772c7d409341e8ebceeceac23`；产物为 `data/evaluation/benchmark/stage3-root-cause-final-clean-real/` 与独立 Evaluation SQLite。该批次用于验证 failure attribution 与 Application lifecycle；C/C2/D 的大批量 provider timeout/connection window 按实际 failure 保留，不能重新解释为 ablation quality
- [x] 记录最终 execution commit、环境、Variant identity 和 final rerun identity；后续仅增加 report/documentation artifact，不改变 production behavior

### 3.5 Tier 2 Development Judge
- [x] D full-system 37 条完成 atomic claim / citation judge；Grounded Claim Rate 与 Citation Correctness 按 `benchmark-judge-v1` 输出
- [x] 所有 judge item 保持 `llm_assisted_provisional`；8 条有 provisional 判定、29 条 `judge_failed` 显式保留、0 条人工 adjudicated
- [x] 生成 `data/evaluation/benchmark/stage3-final-judge-audit-queue.json`；未进入人工逐条 adjudication，不把 Tier 2 数字写成 human verified

## Stage 3 completion evidence（2026-09-04）

- **Gate 2 freeze**：`evaluation/snapshots/resume-benchmark-v1-freeze.json`；freeze verification 12/12 passed，environment gate 4/4 passed；`holdout` absent。
- **Module retrieval**：`data/evaluation/benchmark/stage3-module-retrieval.json`，27 个 Development query，lexical / semantic 均保留 corpus 与 target scope、Recall@5/10、Hit@K、MRR@10 和 context applicability。
- **First real run**：`data/evaluation/benchmark/stage3-first-real/`，185 条 provisional run；failure artifact 112 条，分类和旧结果不进入 final headline。
- **Failure-driven iteration**：streaming/provider terminal observation、finalization projection、失败分类和 report denominator/operational/pair aggregation 已修复并有 regression；context recovery / temporal partial coverage 的剩余限制已通过 targeted rerun 复核并显式保留。
- **Targeted reruns**：`data/evaluation/benchmark/stage3-targeted/`，包含 stream A/C、C2 context 和 D temporal classification 的真实 production Query path 复核。
- **Final clean**：`data/evaluation/benchmark/stage3-final-real/` + `data/evaluation/benchmark/stage3-final-evaluation.sqlite3`；A/B/C/C2/D 各 37 条，合计 185，final report 只使用这批数据。
- **Tier 1 report**：`data/evaluation/benchmark/stage3-final-real/report.json` / `report.md`，包含分子/分母/rate/macro、unavailable reason、operational、B−A/C−B/C2−C、failure analysis、freeze/environment identity。
- **Tier 2 report**：`data/evaluation/benchmark/stage3-final-judge-d.json` 和 audit queue；结果是 LLM-assisted provisional，仍待人工 adjudication。
- **Root-cause closure clean**：`data/evaluation/benchmark/stage3-root-cause-final-clean-real/` + `data/evaluation/benchmark/stage3-root-cause-final-clean-evaluation.sqlite3`；raw / SQLite / Trace 均为 185，A/B/C/C2/D 各 37。failure artifact 146 条：provider_failure 114、retrieval_miss 12、coverage_error 7、context_missing 4、ranking_failure 4、answer_generation_error 2、zero_result_error 3；`not_observed_within_recorded_depth=0`，`evaluation_infrastructure=0`。
- **Root-cause closure audit**：A 31/37、B 35/37、C 5/37、C2 0/37、D 0/37 completed。全批次 114 条 terminal provider failure 中，C/C2/D 占 106 条；这些 failure 在 Trace 中为 `APITimeoutError`/`APIConnectionError`，并集中伴随 `ROUTER_COMPLETION_TIMEOUT`，C2/D failure 没有首个 model turn。独立 recovery smoke 中 D 成功、C2 仍一次失败，故保留为 provider availability/timeout observation，不新增 provider retry 或变体特判。
- **评估缺陷修复**：failure classifier 改为按单次 direct retrieval call 保留 rank，排除 context call，新增 `ranking_failure`；benchmark CLI 改为 async Application context，所有 Variant 在同一个 event loop 执行和关闭。新增 CLI lifecycle regression；全量 `pytest` 594 passed。
- **历史停止边界（2026-09-04）**：Stage 4 的 registration、一次性 holdout run 和 dev/holdout/full merge 已完成；当时等待 Gate 4 复核。holdout 的 90 条 run 全部为 `SettingsError` exception，v1 不生成 holdout 质量指标，也不重跑。

**Gate 3（用户 review）**：dev 最终结果面审 + 系统冻结声明（commit pin + variant fingerprint 记录）。

---

## Stage 4: Judge + 冻结后 Holdout（一次定稿）

### 4.0 Holdout 生成与审核（Gate 3 冻结之后，构造时序隔离）
- [x] 从冻结前未使用的问题池生成 18 条 holdout candidate（六类各 3 条，含新的真实问题）
- [x] 用户逐条人工审核 → adjudicated；存放 `data/evaluation/benchmark/holdout/`（gitignored）
- [x] holdout 有序 Case 身份与 canonical 配置注册到本地冻结记录
- [x] 无效条目替换仅限预声明三情形（GT 矛盾 / 重复 / 数据损坏），本轮无需要替换的条目

### 4.1 Tier 2 Judge（dev 上先验证）
- [x] `benchmark/judge.py` 已实现 atomic claim 切分 + entailment，输出仍为 `llm_assisted_provisional`；代码与 Gate 3 输出见 `src/trivae/evaluation/benchmark/judge.py`、`data/evaluation/benchmark/gate3-review/gate3-final-development-judge-d.json`。
- [ ] **C — 剩余限制，不作为 Gate 4 质量 claim**：开发集 Judge 输出没有逐条人工确认或 `judge-human agreement` 报告。Gate 3 的 12 条人工 packet 是答案/系统诊断，不等同于 claim-level Judge adjudication；其中 `packet.json` 仍为 `pending_human_review`，而 `review.md` 记录了已完成的人工核验。37 条 D-only Judge 为 21 judged、5 skipped、11 failed，成功项均 provisional，0 条 claim 被人工 adjudicate。Gate 4 保留这一限制，不把 Tier 2 数字升级为人工结论。

### 4.2 Holdout 运行（一次性，同冻结 commit + 同 variant fingerprint）
- [x] 五 variant × holdout case（1 rep）+ Tier 1 projection；本轮 90/90 在设置校验阶段 exception，未产生 Tier 1 质量值或 Tier 2 答案
- [x] **结果封存**：无论好坏，v1 holdout 结果即最终结果，照实报告；claim 为 completed，90 条 `SettingsError` exception 保留（artifact observation category 为 `provider_failure`，根因是本地 settings 缺失，不是 Provider availability failure）
- [x] **B — 根因修复在后续提交完成**：SettingsError 根因已记录在现有 `benchmark-root-cause-closure.md`；CLI 后续加入 Application/claim 前 `load_settings()` 预检，并要求冻结 worktree 显式传入 `--env-file`。v1 claim、90 条 raw/Evaluation/Trace 和报告不变；独立 v2 recovery 使用独立 freeze/registration/output。
- [x] **D — 无替换需要**：未发现满足预声明条件（GT 与 Snapshot 矛盾、重复、数据损坏）的 holdout 条目；没有换题、没有重跑 v1。
- [x] full 报告合并断言：dev rerun commit == holdout commit；final report 的 `full_available=true`，但 holdout 质量矩阵为空

### 4.3 交付
- [x] 最终 Comparison Report（full / development / holdout + per-category + 无条件指标 + 跨 Variant 归因；holdout 指标 unavailable）
- [x] Failure Analysis（acceptance-condition failures + `SettingsError` 运行根因）
- [x] 2~4 条简历候选事实已补入 fact index，每条写明数字、分母、scope、证据和限制。v1 holdout 优先条件无质量数据可用；候选事实因此来自 Development baseline / module retrieval / failure diagnosis，不伪造 holdout uplift。
- [x] `interview-defense.md` 已更新最终生命周期、测量边界和 20 个基于真实实现/结果的追问映射；Tier 2 保留 provisional。
- [x] 已补充现有 benchmark root-cause record 和 `problem-records.md` 索引；没有重复创建问题档案。

**Gate 4（最终交付 review）**。

---

## 验证命令

```bash
.venv/bin/pytest -q                      # 全量测试
.venv/bin/ruff check src tests           # lint
.venv/bin/mypy src                       # 类型检查
python -m trivae eval benchmark gate --database data/trivae.sqlite3      # pre-run gate
python -m trivae eval benchmark pilot    # Stage 1.5 校准 pilot
python -m trivae eval benchmark run --suite evaluation/suites/resume-benchmark-dev-v1.json --variants evaluation/variants/ --database data/trivae.sqlite3
python -m trivae eval benchmark report --input data/evaluation/benchmark/...
```

## 回滚点

- Stage 1：benchmark 模块未接入生产链路，revert 对应 commit 即可；ExecutionOverride 新字段默认 None 可独立回滚
- Stage 2/3：case/suite 为纯新增文件；数据产物在 gitignored 目录；GT 不合格 case 废弃即可
- 全程不改 GT 迁就系统输出；holdout 一次定稿，v2 才是新起点

## 2026-09-07 收尾实施批次

此前 Stage 3 历史完成结论保留；用户已同意推进收尾。本批次不将历史未勾选条目机械改为完成。

- [x] 实现 Gate 3 freeze-final、冻结后 holdout 注册与首次 run 封存，并接入 CLI。
- [x] 实现 dev/holdout 同身份报告合并，异版本 full unavailable。
- [x] 补 Judge 证据读取/解析/provider 错误根因与回归测试。
- [x] 准备 12 条人工复核 packet（初始为本地 pending，现已完成核验），核对旧 judge failure 的可诊断范围。
- [x] 更新 README 操作顺序及事实边界，运行相关测试、ruff、mypy、全量 pytest。
- [x] 换 key 后完成单条 Judge smoke；修复了 2048 token 截断并保留 provisional 状态。
- [x] Gate 3 closure implementation 已先提交到远端 `cd973588e0b5e99304770b4a159e21ff20c2baf9`，后续候选验收约束提交为 `8805aa2bf58fcb2702817d54afe96bd819645db2`；原有 `interview-docs/` 工作区改动未混入这些提交。
- [x] 补齐 clean-worktree Environment guard、独立 final-development 目录口径，并让 `freeze-final` 强制校验完整 Development Case/Variant 覆盖；候选 commit `8805aa2` 已捕获 Environment，并完成 37×5 Development acceptance（185/185 pairs）。
- [x] 在候选 commit 的干净 worktree 完成 provider smoke 与完整 Development：raw / Evaluation SQLite / Trace 各 185 条；D-only Judge 输出 21 judged、5 skipped、11 failed 的 `partial` provisional 批次；已生成并完成 12 条人工 review packet 核验。
- [x] 用户完成 Gate 3 人工核验：6 条通过（含备注）、2 条内容失败、4 条系统失败；不据此修改冻结代码或 GT。
- [x] 在 Gate 3 freeze `8805aa2` 后生成 18 条 holdout candidate；Case contract、消息级隔离、候选内 GT 去重和 temporal/zero-result 确定性校验通过。
- [x] 用户逐条审核 holdout candidate 后登记、正式运行一次并输出最终报告；本轮正式运行 90/90 为 `SettingsError` exception，结果不用于 holdout 质量宣传。

## 2026-09-08 配置加载回归修复

- [x] benchmark `run` / `run-holdout` 在创建 Application、写入 claim 和遍历 Case 前预检 `load_settings()`；缺少 Provider 配置时 fail-fast，不再产生 90 条逐 Case 设置异常。
- [x] 保持 dotenv contract：默认仍只读取当前目录 `.env`；冻结 worktree 的运行命令通过 `trivae eval --env-file PATH benchmark ...` 显式注入外部配置，不新增父目录搜索、fallback 或 retry。
- [x] 增加 CLI 回归覆盖缺配置时不创建 Application/claim；从无 `.env` worktree 的实际命令复现 fail-fast，显式 `--env-file` 的 Case 校验通过。
- [x] `.venv/bin/pytest -q` 596 passed；`.venv/bin/ruff check src tests`、`.venv/bin/mypy src` 和 `git diff --check` 通过。
- [x] V1 holdout claim、raw、Evaluation SQLite、Trace 和 final report 保持原样；本修复不触发 V1 重跑，后续真实质量实验仍从新的 v2/fresh freeze 开始。

## 2026-09-08 Holdout v2 recovery validation

- [x] 按用户决定复用 v1 的 18 条 holdout Case、GT 和 18/18 人工核验；不重新构造或改写 GT。
- [x] 复用同一 execution commit `8805aa2` 的 Development acceptance，创建独立 v2 recovery freeze / registration / claim / output，避免触碰 v1 terminal claim。
- [x] 从冻结 worktree 显式注入主工作区 `.env`，完成 18×5=90 次 production-path run；raw / Evaluation SQLite / Trace 均为 90 条。
- [x] Recovery 结果为 52 条 completed、38 条 failed，failure artifact 58 条；`final-report-v2-recovery/` 合并成功。
- [x] 报告标注为 recovery validation / known holdout：不能把复用的 Case/GT/裁决解释为全新 blind holdout 或独立 generalization；v1 失败产物保持不变。

> 历史备注（2026-09-08）：当时保留的 `interview-docs/` 工作区改动未混入提交，待人工确认项不标为完成；后续 Gate 3 review 与 holdout adjudication 已按各自证据完成。

## 2026-09-25 Gate 4 文档收口审计

- **A — 已完成**：Gate 3 review、候选 freeze、18/18 holdout adjudication、一次性 v1 run 和 final merge 均有真实证据；v1 90 条全部 `SettingsError`，质量 unavailable。
- **A — 已完成**：v2 recovery 是独立身份，90 条中 52 completed、38 failed，保留 58 个 failure artifact；继续标为 known/reused holdout。
- **B — 已由后续实现 supersede**：`benchmark/judge.py` 在原计划 Stage 4 之前已实现并执行；Judge 失败原因可追踪，但成功判定仍 provisional。
- **C — 明确保留的限制**：claim-level 人工 Judge adjudication / judge-human agreement 未完成。Gate 3 答案人工 review 不冒充 Judge agreement；本任务没有将 provisional 结果升级或用于简历质量 claim。
- **D — 不适用**：v1 sealed holdout 不重跑；没有符合预声明规则的无效 Case，因此无需替换。
- **Evidence discrepancy**：Gate 3 `packet.json` 的 `pending_human_review` 与 `review.md` 中已记录的 12 条人工核验状态不一致。以人工核验文档与 Task validation 记载的审阅结果作为 review evidence；不改写本地历史 packet，也不把这 12 条说成 Judge claim adjudication。
- Gate 4 结论为 **通过并带明示限制**：已交付可审计事实、结果边界、问题记录和面试材料；不宣称 v1 holdout quality、fresh generalization、Judge-human agreement 或稳定 semantic/context uplift。
