# Embedding 加载/编码失败保留原始异常信息

## Goal

修复 `SemanticEmbeddingError` 在转换底层异常时只保留异常类名、丢失原始 message 的问题，使 `SEMANTIC_EMBEDDING_FAILED` 的 Tool Result / Trace 能直接暴露定位所需的根因信息。

## Background

2026-08-27 会话中，Agent 的 `semantic_search` 查询连续失败（trace-8631f2b5fbc4409da294161ec1a509f8），Tool Result 只有一行：

```
failed to load embedding model Qwen/Qwen3-Embedding-0.6B: ValueError
```

真实的 `ValueError.message` 与堆栈全部丢失，无法判断是 HF Hub 网络瞬态、缓存不完整还是模型配置问题。事后人工复现确认当时为加载侧间歇性失败。项目 AGENTS.md 约定"错误应显式暴露，并保留足够的日志或 Trace 便于定位"，当前实现违反该约定。

## Requirements

1. `src/trivae/retrieval/semantic/embedding.py` 中所有把底层异常转换为 `SemanticEmbeddingError` 的位置，错误 message 必须包含原始异常的完整 `str(exc)`（当前只有 `type(exc).__name__`）：
   - `_release_mps_cache`（约 L117）
   - `_load_model`（约 L136）
   - `_encode`（约 L158）
2. 不得引入 secrets：原始 message 可能包含本地文件路径、HTTP URL 等，允许保留；不允许在错误链路新增凭据字段。
3. 不改变异常类型层级与 `error_code` 映射，`SemanticEmbeddingError` 仍是唯一对外投影类型。
4. 不加 retry/fallback/降级分支——本任务只做错误透明化，瞬态网络问题由调用方显式看到失败后自行决策。
5. 保持既有测试全部通过；为 `_load_model` 与 `_encode` 的失败路径补充断言：抛出的 `SemanticEmbeddingError` message 包含注入异常的原始文本。

## Acceptance Criteria

- [ ] 用 fake model_loader 抛出带明确 message 的异常时，得到的 `SemanticEmbeddingError` message 包含 `ValueError: <原文>` 形式的完整信息（不只是异常类名）。
- [ ] encode 失败路径同样保留原始异常文本。
- [ ] trace/tool result 中 `SEMANTIC_EMBEDDING_FAILED` 的 message 可直接读出根因（无需复现）。
- [ ] `pytest` 全量通过，无回归。

## Out of Scope

- HF 下载缓存策略、HF_TOKEN 配置管理。
- Provider 并发加载加锁（单进程 CLI 场景未观察到真实竞态损伤）。
- 其他模块的同类错误模式（如后续发现再立任务）。
