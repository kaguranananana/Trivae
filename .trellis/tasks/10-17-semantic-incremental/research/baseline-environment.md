# Research: 基线测试与真实 Qwen 环境

- Query: 现有 Semantic/auto-import 测试是否通过，真实 Provider 和 vec0 是否可用？
- Scope: internal
- Date: 2026-10-17

## Findings

### Files found / Code patterns

- `pyproject.toml`：Python ≥3.12；sqlite-vec ≥0.1.9,<0.2；semantic extra sentence-transformers ≥3,<6。
- `embedding.py`：`SentenceTransformerEmbeddingProvider` 通过 sentence-transformers 惰性加载 `Qwen/Qwen3-Embedding-0.6B`；document 使用原文本，query 加 instruction，identity 维度 1024、last-token、normalized。
- `docs/qce-auto-import.md:54`：已有正式调度采用 `HF_HUB_OFFLINE=1` 读取已验证模型缓存，避免历史 Hub HEAD SSL EOF；缓存缺失明确失败。
- Related specs：`quality-guidelines.md`、`database-guidelines.md`、`auto-import-guidelines.md`。

### 已运行命令与结果

```bash
.venv/bin/python -m pytest -q tests/test_semantic_literal_ranking.py tests/test_semantic_retrieval.py tests/test_semantic_resume.py tests/test_forward_semantic.py tests/test_auto_import.py
```

结果：**71 passed in 3.95s**。这是现有测试集合的初始运行；与实现并行执行，部分新代码可能在运行期间落盘，因此不能替代最终全仓质量门。

依赖只读检查命令：

```bash
.venv/bin/python - <<'PY'
import importlib.metadata as m
from pathlib import Path
for package in ['torch','sentence-transformers','transformers','sqlite-vec','huggingface-hub','pytest']:
    try: print(package,m.version(package))
    except m.PackageNotFoundError: print(package,'MISSING')
path=Path.home()/'.cache/huggingface/hub/models--Qwen--Qwen3-Embedding-0.6B'
print('cache_exists',path.exists())
if path.exists():
    print('snapshot_entries',[(p.name, len(list(p.iterdir()))) for p in (path/'snapshots').iterdir()])
PY
```

结果：torch **2.13.0**，sentence-transformers **5.7.0**，transformers **5.16.1**，sqlite-vec **0.1.9**，huggingface-hub **1.29.0**，pytest **8.4.2**；官方 Qwen 0.6B 模型缓存存在，10 个快照入口。没有安装/升级依赖或下载模型。

真实 Provider 验证命令：

```bash
HF_HUB_OFFLINE=1 .venv/bin/python - <<'PY'
from time import perf_counter
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
provider=SentenceTransformerEmbeddingProvider(batch_size=2)
started=perf_counter()
provider.preload()
print('preload_seconds',round(perf_counter()-started,3))
started=perf_counter()
vectors=provider.embed_documents(['群聊讨论苹果树浇水和修剪。','增量索引应复用没有变化的历史向量。'])
print('document_seconds',round(perf_counter()-started,3),'count',len(vectors),'dimensions',[len(v) for v in vectors])
started=perf_counter()
query=provider.embed_query('如何处理苹果树的日常养护？')
print('query_seconds',round(perf_counter()-started,3),'dimensions',len(query))
PY
```

结果：preload **12.773 秒**；两条 documents **1.680 秒**，返回 2 个 1024 维向量；query **0.225 秒**，返回 1024 维。模型加载、encode、Provider 输出校验均真实成功。该命令没有写正式 Canonical 或 Semantic 数据库。

SQLite-vec 真实 rollback probe 结果见 `design-review.md`：SQLite 3.50.4 + vec0 v0.1.9 的 metadata/vector 同事务 DELETE/INSERT 可回滚并提交。

### 后续真实集成

等待 root 确认 storage/repository API 就绪后，使用任务内 `real-benchmark.json` 保存真实增量/全量对照结果；单独 Provider smoke 不冒充端到端增量验收。

## Caveats / Not Found

- 没有联网查询依赖最新版本；所有版本均来自本机已安装 distribution。
- 以上耗时是这台机器的一次真实观测，不能作为统计性能百分比。
- 正式历史库和原始 JSON 未用于实验。
