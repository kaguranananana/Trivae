# Semantic Retrieval Vertical Slice

## Goal

在现有 Trivae Query 主链路中落地一条可重建、可评估、可观测的 Semantic Retrieval vertical slice：Canonical Messages → Time-aware Parent/Small Child → Embedding → 独立 sqlite-vec Derived Index → Semantic Retrieval → bounded canonical context recovery → Agent-facing Tool → Runtime → Evidence/Citation → Trace。

## Requirements

- Semantic v1 的 primary indexing unit 必须是 Time-aware Parent + Small Semantic Child，不实现默认逐 Message embedding。
- 默认本地 Embedding baseline 为 `Qwen/Qwen3-Embedding-0.6B`：1024 dimensions、normalized embeddings、last-token pooling、query retrieval instruction；Python 实现优先使用官方 Hugging Face / sentence-transformers，provider 必须与 Retrieval Core 解耦。
- 模型、provider、dimension、pooling、normalization、query instruction、chunker version/config 和 canonical database identity 必须进入可追踪的 Semantic Index identity；secret/API key 不得进入 identity、Trace 或 Evaluation fingerprint。
- Semantic index 必须是与 Canonical Store 分离的可重建 Derived Data；模型或 chunker identity 不匹配时必须显式报告 stale/rebuild/unavailable，禁止静默回退到 lexical。
- Chunker 必须显式配置 parent gap、parent/child bounds、overlap、semantic-void threshold 与 embedding input bound；semantic-void/高噪声消息保留在 canonical range/context 中，但不得大量占用 embedding input。
- Embedding input 必须包含 bounded 的 source/session、time range、participant 与有效正文；document 不添加 query instruction，query 必须添加 retrieval instruction。
- Semantic Retrieval 必须支持 bounded top-k、session/time/sender/message-type filters（在当前 contract 能表达的范围内）、score provenance、partial/coverage/truncated 与 canonical message recovery。
- Agent-facing surface 使用独立 `lexical_search` 与 `semantic_search`；不新增 `search_messages(strategy=...)`、`hybrid_search` 或固定 Hybrid pipeline。现有 `search_messages` 兼容调用若仍保留，必须复用同一 Lexical Capability，不得成为第三条检索链路。
- Semantic Tool 必须继承 trusted Data Access Scope，错误保留 origin stage；Semantic Index 不可用、stale、embedding failure、dense retrieval failure 与 context recovery failure 不能被 Tool 静默吞掉。
- Semantic Tool 必须通过现有 Runtime SDK adapter、Evidence/Citation provenance、Trace normalized event 与 Application Composition Root 进入生产链路；最终 citation 只能指向 canonical Message source，不指向 chunk/vector row。
- 复用现有 EvaluationCaseBundle/ControlledVariant/EvaluationRunner/Store/Trace；补充 lexical-only baseline 与 semantic-enabled candidate 的最小 comparison fixtures，不扩建独立评测基础设施。
- 创建真实数据只读 semantic index build + retrieval smoke 记录；不得把未经验证的质量或性能结论写成事实。

## Acceptance Criteria

- [ ] 聚焦测试覆盖 chunking、semantic void、provider contract、identity/stale、sqlite-vec build/rebuild、filters/top-k/coverage、scope/tool errors、Trace attribution 与 current-run citation provenance。
- [ ] `TrivaeApplication.rebuild_semantic_index()` 能通过注入 provider 重建独立 index；同一 identity 可重复重建，identity 变化不会继续使用旧 index。
- [ ] 真实 Agent Runtime 可见并调用 `semantic_search`，Tool Result 可进入现有 finalizer；失败时不执行 lexical fallback。
- [ ] semantic candidate 能恢复为 canonical `MessageProjection`，Evidence/Citation 不暴露 chunk/vector 作为最终 source。
- [ ] baseline/candidate evaluation variant 显式记录 available tools、retrieval configuration 与 semantic index identity。
- [ ] 运行 `pytest -q`、`ruff check src tests`、`mypy src`、`git diff --check`；失败先修实现根因并记录。
- [ ] validation.md 明确记录真实 smoke 是否完成、测试事实、已知限制与 Pending Evaluation，不把未完成项写成完成。

## Notes

- 参考 ChatLab 的 Parent/Child、semantic-void、contextual embedding input、独立 sqlite-vec 与 explicit index status；具体数值不直接复制。
- 仓库 AGENTS.md 禁止写哈希/SHA256，因此 index identity 使用 canonical、可读、无密钥的结构化 JSON/字段，不实现 ChatLab 的 hash 算法。
- 当前分支已有 M1/M2/M3/M4/M5/M6/M7 的基础链路；本任务应保持已有 lexical/evidence/conversation/trace 行为稳定。
