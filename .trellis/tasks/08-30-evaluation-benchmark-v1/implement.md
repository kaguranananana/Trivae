# Implementation Plan: resume-benchmark-v1

执行顺序遵循用户修正后的四阶段：Measurement Substrate → Benchmark Dataset → 干净 Ablation → Citation Judge + 冻结 holdout。
每阶段末尾有 review gate；gate 未过不进入下一阶段。

---

## Stage 1: Measurement Substrate（先于一切 Case 构造）

### 1.1 ExecutionOverride 最小扩展
- [ ] `ExecutionOverride.context_window_limit: int | None = None` + 校验（非 None 时 ≥0）+ to_dict/from_dict
- [ ] `AgentRunRequest.context_window_limit` 新可选字段；`QueryRequest.to_runtime_request()` 贯通
- [ ] `RuntimeContext.context_window_limit` 贯通；openai_tools.py 中 lexical_search / semantic_search / search_messages 输入构造点钳制 context_before/after；tool 完成 payload 记录 `context_window_applied`
- [ ] `get_message_context` / `get_recent_messages` 不受影响（显式验证）
- [ ] 旧 JSON 兼容：无该字段的 variant/override 解析为 None；现有全部测试零改动通过

### 1.2 Run projection 扩展
- [ ] `checks.query_result_snapshot` 增加 `retrieval_calls`（direct_hits(前50,带rank) / expanded_ids(前50) / counts / coverage / recorded_depth）
- [ ] `query_result_snapshot` 增加 `evidence_sources`（evidence_id → source message IDs / locator kinds，bounded）
- [ ] `checks.tool_result_facts` 复制清单加入 `context_window_applied`
- [ ] 新 deterministic check `context_expansion_override`（variant 声明 limit=0 ⇒ 所有 retrieval call applied=0）

### 1.3 Benchmark 模块骨架
- [ ] `benchmark/gt.py`：criterion 约定解析 + 一致性校验（expected_zero_result ↔ relevant 互斥等）
- [ ] `benchmark/snapshot.py`：materializer（manifest 追加 semantic_index / session_count / benchmark 元数据；redacted 提交版生成）
- [ ] `benchmark/retrieval.py`：module-level 双策略 runner（完整 ranking、expanded 分层、GT 直接评分）
- [ ] `benchmark/metrics.py`：Tier 1 全部指标 + GT completeness→scope 策略（corpus/pool/unavailable）+ provider failure 剔除
- [ ] `benchmark/report.py`：JSON + Markdown 矩阵（overall / per-category / per-split）
- [ ] `benchmark/failures.py`：failure artifact + failure_category 判定链
- [ ] CLI：`trivae eval benchmark ...` 编排子命令（pre-run gate：snapshot_id + semantic identity + lexical count）

### 1.4 Stage 1 测试
- [ ] Unit：Recall@K / MRR / Hit@K（corpus 与 pool 两 scope）、Evidence Recall、Context Recovery、Coverage Accuracy、Complete Answer（expected_fact 匹配）、False Zero-Result、Verified Zero-Result、GT 解析与一致性校验、override 钳制（contract 级）
- [ ] Integration：fixture DB 上 fixed snapshot + fixed case 跑通 Runner→projection→metrics→report；override=0 时 expanded_ids 为空且 check passed；drift 拒绝
- [ ] `pytest -q` 全绿；`mypy`/`ruff` 通过

**Gate 1（用户 review）**：Stage 1 代码与测试面审；确认指标定义与投影 schema。

---

## Stage 2: Benchmark Dataset（40~60 case，质量优先）

### 2.1 Snapshot 固化
- [ ] 跑 pre-run gate 通过后 materialize `resume-benchmark-v1`（本地完整版 + redacted 提交版）
- [ ] 记录 git commit / semantic identity / lexical count 进 manifest

### 2.2 Case 构造
- [ ] 汇总真实问题来源清单：dogfooding 历史（web-ui dogfooding 20 题、archive traces）、归档 failure cases（2699/100、CJK 0-hit、合法空窗、31/20 截断…）、数据挖掘候选
- [ ] LLM 辅助生成 candidate question + candidate evidence（三路检索）→ provisional Case JSON
- [ ] exact_lexical / semantic_paraphrase 类执行确定性 exhaustive 证明（FTS+LIKE 全库扫描）
- [ ] 生成人工 review markdown（query + 候选消息摘要 + 建议 GT + 修改槽）
- [ ] **用户逐条审核** → adjudicated=true；`why_relevant` 无正文泄漏检查

### 2.3 冻结
- [ ] suite_tags 标注 category + benchmark:development/holdout
- [ ] 生成 3 个 Suite（dev / holdout / full）+ reserve pool（≥ holdout 数 30%）
- [ ] 归属冻结记录（写入本任务 notes：冻结时间、case 清单 hash）

**Gate 2（用户 review）**：GT 逐条审核完成；dev/holdout 冻结确认。

---

## Stage 3: 干净 Ablation（先 dev，只看 dev）

### 3.1 Retrieval-only（确定性，不调 LLM）
- [ ] Type A/B case × {lexical, semantic} 双策略全量跑 → Recall@5/10、MRR、Hit@K（corpus scope）
- [ ] context ablation（module 层 before/after 0 vs 默认）→ Context Recovery（retrieval 侧）

### 3.2 End-to-End（真实 LLM，1 rep）
- [ ] dev case × A/B/C/D 四 variant 全量跑（编排器统一 pre-run gate）
- [ ] Evidence Recall / Context Recovery / Coverage Accuracy / Complete Answer / Zero-result 指标
- [ ] latency / tool calls / tokens 诊断聚合

### 3.3 迭代纪律
- [ ] 只允许基于 dev 结果修复；每修复：保存 failure artifact → root cause → 通用机制修复 → 重跑同 case → before/after 留档
- [ ] 禁止针对单 case 特殊逻辑；禁止查看 holdout

**Gate 3（用户 review）**：dev 结果面审 + 系统冻结声明（此后不再改任何影响指标的代码/参数）。

---

## Stage 4: Citation Judge + 冻结后最终运行

### 4.1 Tier 2 Judge
- [ ] `benchmark/judge.py`：复用 build_review_packet + JudgeAdapter；Grounded Claim Rate / Citation Correctness（llm_assisted_provisional）
- [ ] dev 抽样人工审核 → adjudicated 升级路径验证

### 4.2 Holdout 运行（一次性）
- [ ] 全 variant × holdout case（1 rep）+ Tier 2 指标
- [ ] 若 holdout 暴露问题：按纪律降级 case → 补 reserve → 修复仅走通用机制 → 重新冻结 → 重跑

### 4.3 交付
- [ ] 最终 Comparison Report（full / development / holdout 三列组 + per-category）
- [ ] Failure Analysis（最差 case + root cause 清单）
- [ ] 简历候选指标 2~4 个（holdout 优先，含样本量与 scope）
- [ ] `interview-defense.md` 新增「resume-benchmark-v1 事实索引」章节（指标选择/GT 构建/Snapshot 必要性/Ablation 设计/防 overfit/semantic 与 expansion 有效性/coverage 与 citation 验证/真实 before-after/应对质疑话术）
- [ ] `problem-records.md` 视新增 bug 情况补记录

**Gate 4（最终交付 review）**。

---

## 验证命令

```bash
.venv/bin/pytest -q                      # 全量测试
.venv/bin/ruff check src tests           # lint
.venv/bin/mypy src                       # 类型检查
python -m trivae eval benchmark snapshot-gate --database data/trivae.sqlite3   # pre-run gate
python -m trivae eval benchmark run --suite evaluation/suites/resume-benchmark-dev-v1.json --variants evaluation/variants/ --database data/trivae.sqlite3
python -m trivae eval benchmark report --input data/evaluation/benchmark/...
```

## 回滚点

- Stage 1 任一步失败：benchmark 模块未接入生产链路，revert 对应 commit 即可；ExecutionOverride 新字段默认 None，可独立保留或回滚。
- Stage 2/3：case/suite 为纯新增文件；数据产物全部在 gitignored 目录。
- 全程不改 GT 迁就系统输出；不合格 case 直接废弃或降级 reserve。
