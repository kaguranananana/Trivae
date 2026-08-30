# Evaluation 现状审计与两项确认（2026-08-30）

## 一、Harness 现状（10 模块，5354 行）

- `contracts.py`：DatasetSnapshot（deterministic manifest，无正文）/ ReferenceFinding+Evidence+Provenance（per-finding GT，relation=supports/contradicts/context，locator 绑 canonical ID，annotation_completeness=exhaustive/partial/unknown，provenance.adjudicated）/ EvaluationCaseBundle（schema_version=1）/ Suite（4 kind）/ DeterministicCheck / EvaluationRun / EvaluationResult / EvaluationReview / ReviewPacket / PairedComparison（blind A/B）/ FailureDiagnosis（12 DiagnosisOwner）
- `variant.py`：ControlledVariant（available_tools / retrieval_configuration / context_expansion_configuration / index_identity / budget / execution_override）+ fingerprint + variant_diff
- `runner.py`：解析 Snapshot→拒绝漂移→生产 query_executor 执行→读 Trace→存 Run/Result；支持 repetitions
- `checks.py`：确定性契约检查 + operational_measurements（latency / tool calls / usage tokens / coverage_statuses / tool_result_facts / finalization state）
- `store.py`：独立 SQLite（runs/results/reviews/comparisons/diagnoses）
- `review.py`：ReviewPacket / JudgeAdapter / paired comparison / M6 failure regression map
- `retrieval_evaluation.py`：RetrievalQuerySet（绑 Snapshot）→ 双策略真实检索 → 盲标 packet（隐藏来源/rank/score）→ RelevanceAnnotation（llm_assisted_provisional / human_verified）→ 指标（P@k / pool-Recall@k / MRR / top-k hit / relevant coverage）；missing/uncertain 显式 unavailable；corpus_recall 恒 unavailable
- `retrieval_annotation.py`：LLMRetrievalAnnotator（OpenAI-compatible，JSON mode，temperature=0）
- 现有指标能力：precision@k / pool recall@k / MRR / hit / coverage 覆盖（记录非评分）/ latency / tool calls / tokens / finalization。citation 仅确定性校验（locator 可解析），无 entailment
- CLI：eval cases validate / run / show / compare / regression / snapshot / retrieval-packet / retrieval-annotate / retrieval-metrics
- Catalog：13 seed cases（占位 Snapshot）、4 suites、8 variants、agent tool selection diagnostics、m6/m7/deepseek regressions、semantic-vs-lexical provisional v1（12 query，已跑出 provisional 指标）

## 二、生产契约关键事实

- 相对时间锚定 `archive_latest`（capabilities/contracts.py:59 RelativeTimeRange.resolve），不用机器时钟 → 固定 Snapshot 上 temporal query 可复现
- `has_verified_zero_result_evidence`（evidence.py:933）：no_result 需 positive proof（所有 retrieval ok + coverage complete + run 无 facts）
- `AnswerArtifact` 含 Host-owned `retrieval_coverage` / `resolved_time_range`
- `ToolResultRecord.message_items` 保持工具返回顺序，`ToolMessageItem.is_hit` 区分 direct hit vs context-expanded
- `compile_model_no_result_answer` 产物形态：单 content block（id="answer"）+ 无 evidence/citation
- 语义检索 coverage：status=complete/partial，basis=canonical_plus_semantic_index
- recent messages：keyset cursor、每页 coverage/partial/has_more/next_cursor

## 三、确认 1：context_expansion_configuration 不贯穿生产 Runtime

证据链：
1. `grep -rn context_expansion_configuration src/` → 仅 evaluation/variant.py 4 处（fingerprint/序列化）
2. `TrivaeApplication.query()` 签名只接受 QueryRequest + streaming 参数（application.py:621）
3. QueryRequest 无 context expansion 配置字段（query/contracts.py:84）
4. Runner._run_one 只传 available_tools / execution_override / trace_profile（runner.py:160-176）
5. `to_runtime_request()` 构造的 AgentRunRequest 不含 execution_override（query/contracts.py:146-162）
6. runtime 工具调用唯一入口 `runtime_context.capability_registry.invoke(...)`（openai_tools.py 7 处）
7. `CapabilityRegistry.register` 拒绝同名覆盖（registry.py:26-29）→ 运行时装饰工具违反架构

结论：该字段是纯 variant 元数据，对运行时零影响。消融需要唯一最小扩展：`ExecutionOverride.context_window_limit: int | None = None`，贯通 AgentRunRequest / RuntimeContext，在 runtime 构造 lexical_search / semantic_search / search_messages 输入前钳制 context_before/after。get_message_context 不钳制（显式 deepening tool，A/B 不暴露）。Trace `query.received` 已记录 execution_override.to_dict() → 新字段自动可验证。

## 四、确认 2：semantic index identity 部分强约束，benchmark 层需补齐

已强制（生产检索层 per-query）：
- `SemanticRetrieval.search`（retrieval/semantic/retrieval.py:74-97）：identity.serialized 不匹配 → `SemanticIndexStale`；canonical count 漂移 → stale；building/failed → unavailable。不 rebuild、不 fallback
- Identity 组成：database_identity + EmbeddingModelIdentity（model/dimension/pooling/normalized/query_instruction）+ chunker version + chunker config
- lexical：查询前 FTS count vs canonical count stale 检查（database-guidelines spec）

缺口：
- DatasetSnapshot.from_database manifest 不含 semantic index identity
- Runner 只验证 snapshot_id，不验证 index identity
- End-to-end run projection 不记录 serving 的 index_identity

补齐（benchmark 层，零生产契约变更）：
- DatasetSnapshot.manifest 是自由 bounded Mapping → benchmark materializer replace() 追加 `semantic_index` identity，schema_version 不变
- Benchmark 编排器 pre-run gate：live semantic identity == pinned manifest identity，否则整体失败
- ControlledVariant.index_identity pin 真实 serialized identity（替换 ":bind-at-run"）
- 运行中期漂移由现有机制兜底：Runner 每 case 重解析 Snapshot；semantic 查询时 identity 失配显式失败

## 五、真实环境状态

- data/trivae.sqlite3：473,236 messages / 7 sessions / FTS 473,236 行完整
- 时间范围：1753011800000（2025-07-20）→ 1786847688000（2026-08-16）
- semantic index：54,267 chunks，覆盖 473,236 messages，Qwen/Qwen3-Embedding-0.6B 1024d last_token normalized
- provider：opencode-go / deepseek-v4-flash（.env 已配置）
- 现有 provisional query set 绑定的 snapshot_id 与当前 DB 一致
- 隐私边界：data/evaluation/ gitignored（私有正文）；evaluation/ 只进无正文 artifact；snapshot manifest 含 external_chat_id 等私有 source metadata，须 redact 后才能进 evaluation/

## 六、归档任务关键教训（详表见会话调研）

1. Stage 1.10：GT 不用唯一标准答案；per-Finding completeness 三态；质量轴与诊断轴分离；不压总分
2. M7：last-stable 是 pinned Variant 非最优 baseline；Reference unknown 不给质量分；禁止静默绑定漂移数据
3. Semantic slice：12-query provisional 指标（P@8 0.24/0.28，pool-Recall@8 0.35/0.65，MRR 0.43/0.62）；候选池非 corpus-exhaustive → corpus Recall 恒 unavailable
4. Budget regression：citation unresolved=0 只证明可解析不证明蕴含；七轴七标签 executable contract
5. Real-provider A/B：36 cells；timeout/runtime failure 不进质量分母
6. CJK lexical：0-hit 三层论证；bigram v2 = LIKE oracle 100% recall；单字 query 是 known limitation
7. 2699/100 覆盖误判：keyset continuation 修复；按最大 covered_units 汇总；COVERAGE_MISMATCH/TIME_RANGE_MISMATCH fatal
8. 合法空窗被三层拒绝 → kind=no_result + positive proof contract
9. Dogfooding F-DEPTH-01 / F-RUNTIME-02：answer 长度只作 diagnostic；Evidence Artifact 与 Answer Content 目标分离
