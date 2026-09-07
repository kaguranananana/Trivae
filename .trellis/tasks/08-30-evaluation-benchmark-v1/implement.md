# Implementation Plan: resume-benchmark-v1

> Revision 2：吸收 review 修正——新增 Stage 1.5 calibration pilot gate；Stage 3 末尾「冻结 commit 全 dev rerun」；Stage 4 改为 holdout 一次定稿、结果封存、修复进 v2（删除降级替换重跑流程）。
> 四阶段：Measurement Substrate → Benchmark Dataset → 干净 Ablation → Judge + 冻结后 holdout。
> 每阶段末尾有 review gate；gate 未过不进入下一阶段。
>
> **当前状态（2026-09-04，Stage 3 根因收口）**：**Human GT Adjudication Gate、Gate 2
> Development Freeze、Module Retrieval、Failure-driven iteration、最终 clean 37×5 和 Tier 1
> / Tier 2 Development Evaluation 均已完成**。47/47 case 已人工裁决（Accept 26 / Modify 21 /
> Reject 0；calibration 10 / development 37），deterministic audit 为 green（47 cases / 47
> adjudicated / 0 error / 0 warning，`data/evaluation/benchmark/gt-audit-stage3-final.json`）。
> Gate 2 使用 ordered versioned Case identities + canonical Variant configuration text 作为可复现
> identity；execution commit 为 `b1f7b78...`，冻结后的 clean execution commit 为
> `7bac9282701bd0c21b58ce8e5a4f5cc52c87da9f`，根因修复后的 post-fix clean execution commit 为
> `f24775099cb2314772c7d409341e8ebceeceac23`。最终 headline 只使用 Development 37×5=185
> runs；calibration 排除，holdout 尚不存在。当前 **Stage 3 Complete / Ready for Gate 3**，不
> 进入 Gate 3，不生成 holdout；不要 archive 本任务。

---

## Stage 1: Measurement Substrate

### 1.1 ExecutionOverride 最小扩展
- [ ] `ExecutionOverride.context_window_limit: int | None = None` + 校验（非 None 时 ≥0）+ to_dict/from_dict（旧 JSON 缺字段 → None）
- [ ] `AgentRunRequest.context_window_limit` 新可选字段；`QueryRequest.to_runtime_request()` 贯通
- [ ] `RuntimeContext.context_window_limit` 贯通；openai_tools.py 中 lexical_search / semantic_search / search_messages 输入构造点钳制 context_before/after；tool 完成 payload 记录 `context_window_applied`
- [ ] `get_message_context` / `get_recent_messages` 不受影响（显式验证）
- [ ] 现有全部测试零改动通过

### 1.2 Run projection 扩展
- [ ] `checks.query_result_snapshot` 增加 `retrieval_calls`（per-call：direct_hits 前 50 带 rank / expanded_ids 前 50 / counts / coverage_status / truncated / recorded_depth / omitted_ids；per-run：call cap 8 + `retrieval_calls_omitted`）与 `evidence_sources`（bounded）
- [ ] `checks.tool_result_facts` 复制清单加入 `context_window_applied`
- [ ] 新 deterministic check `context_expansion_override`（声明 limit=0 ⇒ 所有 retrieval call applied=0）
- [ ] 深度语义落地：`not_observed_within_recorded_depth` 状态可供 failure 分类消费

### 1.3 Benchmark 模块
- [ ] `benchmark/gt.py`：criterion 约定解析（三轴 expected_coverage_status / expected_truncated / expected_zero_result 互斥与一致性校验；expected_fact 为 alias 列表）
- [ ] `benchmark/environment.py`：BenchmarkEnvironmentManifest（canonical snapshot_id + lexical identity + semantic serialized identity + git commit）+ pre-run gate 三查
- [ ] `benchmark/retrieval.py`：**薄 adapter**——Case → RetrievalQuerySet → 现有 RetrievalAnnotationWorkflow 执行路径 → RetrievalRunRecord → GT 评分；不重写 invocation/ranking/coverage
- [ ] `benchmark/metrics.py`：Tier 1 指标（scope 策略：exhaustive→corpus / partial→target / unknown→unavailable；MRR@K 显式 cutoff；Expected Fact Answer Coverage 只查 answer_text；Coverage 三轴各自独立；Execution Completion Rate / Valid Answer Rate 无条件指标；provider failure 剔除条件分母但单独呈现）
- [ ] `benchmark/report.py`：JSON + Markdown（overall / per-category / per-split；full 列做 commit 一致性断言）
- [ ] `benchmark/failures.py`：acceptance-condition 触发 + 单 Run observation category 判定链（semantic_miss 不在此层）
- [ ] CLI：`trivae eval benchmark ...` 编排子命令

### 1.4 Stage 1 测试
- [ ] Unit：各 scope 的 Recall@K / Hit@K / MRR@K、Evidence Recall、Context Recovery、Coverage Status Accuracy（三轴独立）、Truncation Accuracy、Expected Fact Answer Coverage（answer_text-only 假阳性负例）、False/Verified Zero-Result、无条件完成率、GT 解析与一致性校验、environment gate、override 钳制 contract
- [ ] Integration：fixture DB 上 fixed snapshot + fixed case 走通 Runner→projection→metrics→report；override=0 ⇒ expanded_ids 空且 check passed；drift/identity mismatch 拒绝；retrieval_calls 全 run cap 生效
- [ ] `pytest -q` 全绿；`ruff check` / `mypy` 通过

### 1.5 Calibration Pilot Gate（人工批量审核之前）
- [ ] 构造 8~12 个 dev pilot case（覆盖全部六类各 ≥1；含 ≥1 个 exhaustive predicate case、≥1 个 target-set case、≥1 个 expected partial/truncated temporal case、≥1 个 true-empty case）
- [ ] 走完全链路：GT parser → module-level retrieval 评分 → A/B/C/C2/D 五 variant end-to-end 单 case smoke → projection → metrics → report
- [ ] 校验点：GT 解析无误、projection 无界增长受控、指标 unavailable 语义正确、failure 分类链不误触发、report 可读
- [ ] pilot 中发现的数据模型问题在本阶段修复（此时改 schema 成本最低）

**Gate 1（用户 review）**：Stage 1 代码 + pilot 结果面审；确认指标定义、投影 schema、报告形态。

---

## Stage 2: Benchmark Dataset（40~60 case）

### 2.1 Snapshot / Environment 固化
- [ ] pre-run gate 通过 → 写 `data/evaluation/benchmark/environment.json`（完整版）+ `evaluation/snapshots/resume-benchmark-v1.json`（redacted 提交版）
- [ ] DatasetSnapshot 本体保持零改动（绑定仍走 case.dataset_snapshot.snapshot_id）

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
- **评估缺陷修复**：failure classifier 改为按单次 direct retrieval call 保留 rank，排除 context call，新增 `ranking_failure`；benchmark CLI 改为 async Application context，所有 Variant 在同一个 event loop 执行和关闭。新增 CLI lifecycle regression；全量 `pytest` 576 passed。
- **停止边界**：当前为 **Stage 3 Complete / Ready for Gate 3**；Gate 3、holdout generation、holdout evaluation、full benchmark 尚未执行。

**Gate 3（用户 review）**：dev 最终结果面审 + 系统冻结声明（commit pin + variant fingerprint 记录）。

---

## Stage 4: Judge + 冻结后 Holdout（一次定稿）

### 4.0 Holdout 生成与审核（Gate 3 冻结之后，构造时序隔离）
- [ ] 从冻结前未使用的问题池生成 holdout candidate（总规模 30~40%，六类分布，含新的真实问题）
- [ ] 用户逐条人工审核 → adjudicated；存放 `data/evaluation/benchmark/holdout/`（gitignored）
- [ ] holdout 有序 Case 身份与 canonical 配置注册到本地冻结记录
- [ ] 无效条目替换仅限预声明三情形（GT 矛盾 / 重复 / 数据损坏），记录原因

### 4.1 Tier 2 Judge（dev 上先验证）
- [ ] `benchmark/judge.py`：atomic claim 切分 + entailment（llm_assisted_provisional）；若不做 atomic 切分则输出 `Cited Content Block Support Rate`
- [ ] dev 抽样人工逐条确认 → per-item adjudicated + judge-human agreement 报告（无整组升级）

### 4.2 Holdout 运行（一次性，同冻结 commit + 同 variant fingerprint）
- [ ] 五 variant × holdout case（1 rep）+ 全部 Tier 1 / Tier 2 指标
- [ ] **结果封存**：无论好坏，v1 holdout 结果即最终结果，照实报告
- [ ] 若暴露真实 Bug：v1 结果保留 + 记录 root cause；修复进入 `resume-benchmark-v2`（届时构造全新未暴露 holdout）；**禁止因系统答错替换/降级 holdout case 后重跑 v1**
- [ ] 仅预声明的无效条目情形（GT 矛盾/重复/数据损坏）允许替换并记录原因
- [ ] full 报告合并断言：dev rerun commit == holdout commit，否则 full 列 unavailable

### 4.3 交付
- [ ] 最终 Comparison Report（full / development / holdout + per-category + 无条件指标 + 跨 Variant 归因）
- [ ] Failure Analysis（acceptance-condition failures + root cause 清单）
- [ ] 简历候选指标 2~4 个（holdout 优先，含 baseline/current/absolute/relative/样本量/scope/GT completeness）
- [ ] `interview-defense.md` 新增「resume-benchmark-v1 事实索引」章节（指标选择/GT 构建与完备度边界/Snapshot 与 Environment 分离/Ablation 设计/防 overfit 与 holdout 纪律/semantic 与 expansion 有效性/coverage 三轴与 citation 验证/真实 before-after/应对质疑话术）
- [ ] `problem-records.md` 视新增 bug 情况补记录

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
- [x] 准备 12 条人工复核 packet（本地 pending），核对旧 judge failure 的可诊断范围。
- [x] 更新 README 操作顺序及事实边界，运行相关测试、ruff、mypy、全量 pytest。
- [x] 换 key 后完成单条 Judge smoke；修复了 2048 token 截断并保留 provisional 状态。
- [x] Gate 3 closure implementation 已提交到远端 `cd973588e0b5e99304770b4a159e21ff20c2baf9`；原有 `interview-docs/` 工作区改动未混入该提交。
- [ ] 补齐 clean-worktree Environment guard 和 final-development 目录口径；完成后生成新的候选 commit，再捕获运行 Environment 并安排 provider smoke / 完整 dev 验收。
- [ ] 用户实际完成答案核验和 Gate 3 review 后生成/审核 holdout，正式运行一次并输出最终报告。

用户已有 interview-docs/ 工作区改动保持原样；本批次不自动 commit、archive 或把待人工确认项标完成。
