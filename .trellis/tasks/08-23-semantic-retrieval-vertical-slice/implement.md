# Semantic Retrieval Vertical Slice Implementation Plan

## Ordered work

1. Add research/identity artifacts and activate the Trellis task after review.
2. Add semantic domain contracts and deterministic chunker with explicit baseline config.
3. Add provider protocol, lazy Qwen3 sentence-transformers provider, and vector/index identity validation.
4. Add sqlite-vec derived store, build/rebuild service, streaming canonical message read and range read.
5. Add semantic retrieval result types and bounded context recovery.
6. Add semantic capability/tool and retain the existing lexical capability as a shared primitive; expose canonical `lexical_search`/`semantic_search` SDK tools while preserving only the minimum existing direct-call compatibility needed by current contracts.
7. Add Application composition/rebuild entry, lifecycle close, config defaults, dependency metadata, and Runtime SDK tool mapping.
8. Add focused tests and lexical-only/semantic-enabled evaluation fixtures/variant metadata.
9. Run focused tests, then full quality gates. Reproduce and fix failures at the owning layer.
10. Run a real-data smoke with an explicitly selected provider/database path if local model/runtime is available; otherwise record the exact external dependency blocker and keep deterministic validation complete.
11. Update project overview/architecture status only for facts actually implemented; update interview-defense and write validation.md.

## Planned files

- `src/trivae/retrieval/semantic/contracts.py`
- `src/trivae/retrieval/semantic/chunking.py`
- `src/trivae/retrieval/semantic/embedding.py`
- `src/trivae/retrieval/semantic/index.py`
- `src/trivae/retrieval/semantic/retrieval.py`
- `src/trivae/retrieval/semantic/builder.py`
- `src/trivae/retrieval/semantic/__init__.py`
- `src/trivae/retrieval/structured.py`, `context.py`, `src/trivae/data/storage/sqlite_read.py`
- `src/trivae/capabilities/contracts.py`, `search_messages.py`, new semantic capability/tool modules, registry/tool adapter
- `src/trivae/query/runtime/openai_tools.py`, `openai_adapter.py`, `query/contracts.py` as needed
- `src/trivae/bootstrap/application.py`, `config/settings.py`, `pyproject.toml`
- focused tests and evaluation case/variant files

## Validation commands

```bash
source .venv/bin/activate
pytest -q
ruff check src tests
mypy src
git diff --check
python -m compileall -q src
```

Focused first pass:

```bash
pytest -q tests/test_semantic_retrieval.py tests/test_capabilities.py tests/test_evidence.py tests/test_observability.py tests/test_agent_runtime.py
```

## Review gates

- No API key or provider secret appears in identity, Trace, Evaluation fingerprint, error text or committed files.
- No Python full-vector scan, silent lexical fallback, retry, or catch-all error conversion is introduced.
- Every new normalized Trace payload keeps strategy/index identity/candidate/range/score/coverage/latency facts bounded and source-owned.
- Existing lexical, citation, conversation and trace tests remain valid unless an intentional public tool-name change is explicitly covered.

## Authorized real-run and Evaluation follow-up

12. 记录 Python/Torch/transformers/sqlite-vec、CPU/MPS、RAM、磁盘、模型 cache、Snapshot 与 rebuild 前状态；只根据实际 Failure Case 调整 operational batch size。
13. 扩展 build stats 与 index integrity read model，记录 parent/child/vector、模型加载/embedding/write 时间、batch、throughput 与文件大小所需事实。
14. 在全部 473,236 条 canonical messages 上运行真实 Qwen rebuild；完成后验证 identity、1024 dimensions、internal row consistency、canonical recovery、reopen persistence 和 stale detection。
15. 在现有 Evaluation package 内增加 retrieval query/run、blind packet、sealed metadata、annotation、metrics 和 audit queue contracts；本地 artifact 目录加入 gitignore。
16. 生成同 Snapshot 的 lexical/semantic 候选并去重，使用隐藏方法身份的 packet 完成全部 LLM-assisted provisional annotation；逐条保存 confidence，绝不写入 `human_verified`。
17. 计算带明确 provenance/availability 的 paired provisional metrics 和 diagnostics；corpus Recall 在没有 exhaustive reference 时保持 unavailable。
18. 对真实运行暴露的问题执行 reproduce → regression test → minimal fix → validation；不引入 RRF、reranker、hybrid、降维、另一模型或 lexical fallback。
19. 更新 validation/architecture/interview-defense，运行完整门禁，按逻辑提交、归档 Trellis task、记录 journal 并 push feature branch。
