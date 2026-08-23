# Semantic Retrieval Vertical Slice Validation

## Truth status

本文件严格区分 deterministic contract、真实机器 measured facts、无标签 diagnostics、
LLM-assisted provisional metrics 与仍需人工验证的结论。真实聊天正文、候选上下文、
逐条 notes 和 audit queue 只保存在 gitignored local artifact，不进入 Trellis 或 Git。

## Branch and checkpoint commits

- Branch: `codex/semantic-retrieval-vertical-slice`
- Base: `2e01168` (`Merge model provider configuration`)
- Vertical slice checkpoint: `cc62625`
- Rebuild telemetry/integrity: `ccc083c`
- Provisional retrieval Evaluation workflow: `ef85d22`
- Cross-Parent batching and interrupted-state fix: `6d41e60`
- Annotation provenance and metric availability hardening: `fb4238d`, `4e9424e`

## Deterministic contract validation

当前测试覆盖以下主链路：

- Time-aware Parent + Small Child、child overlap 与 semantic-void exclusion；
- `Qwen/Qwen3-Embedding-0.6B` 的 1024 dimensions、last-token pooling、normalized、
  query-only retrieval instruction 与可读 secret-free identity；
- 独立 sqlite-vec rebuild、internal row consistency、canonical range recovery、reopen 与 stale；
- building/failed/stale/partial/truncated 错误透明，且不执行 lexical fallback；
- Semantic Tool、Runtime SDK、Trace、current-run Evidence/Citation canonical provenance；
- 跨 Parent bounded embedding batch、zero-child Parent watermark 与 Ctrl+C failed terminal state；
- blind/sealed packet 分离、canonical candidate 去重、LLM provisional provenance 和 audit queue；
- perfect/partial/miss/duplicate/rank/no-relevant/unknown/partial annotation/invalid Snapshot/
  paired comparison 指标语义，missing/uncertain 不作为 negative。

最终完整门禁结果在全量 rebuild 与 paired Evaluation 完成后更新。

## Real environment preflight

### Machine and runtime

| fact | measured value |
| --- | --- |
| OS / architecture | macOS 26.5.2 / arm64 |
| Python | 3.14.6 |
| PyTorch | 2.13.0 |
| transformers | 5.15.1 |
| sentence-transformers | 5.7.0 |
| sqlite-vec | 0.1.9 |
| CUDA | unavailable |
| MPS | built and available |
| unified physical memory | 16 GiB |
| free disk before full run | approximately 18 GiB; minimum observed during run 12 GiB |
| Qwen cache | present, approximately 1.1 GiB |

### Canonical Snapshot

```text
snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 473236}
```

Measured Snapshot facts：473,236 canonical messages、14 sources、首时间戳
`1753011800000`、末时间戳 `1786847688000`；lexical FTS index 存在且为
473,236 rows。Semantic rebuild 只写独立的 `data/trivae.semantic.sqlite3`，canonical
database 未被 rebuild 修改。

## Qwen provider calibration

官方 sentence-transformers provider 在 MPS 上加载成功。真实 3,000-message slice
产生 32 个 chunks；同一批输入的 bounded batch comparison：

| batch | chunks/s | MPS current allocation | MPS driver allocation |
| ---: | ---: | ---: | ---: |
| 8 | 3.180 | 1,136.4 MiB | 3,298.8 MiB |
| 16 | 2.848 | approximately the same | 3,298.8 MiB |
| 32 | 2.032 | not selected | 6,370.8 MiB |

因此真实 full run 保持 model、1024 dimensions 和 batch=8，不因耗时改用其他模型、
降维或更大 batch。模型加载约 12.257 seconds；provider 输出 dimension=1024、
norm=1.0、pooling=last_token、normalized=true，query instruction 与 identity 一致。

一个只读全量 chunk-shape pass（不生成向量）测得 14,552 Parents、54,267 eligible
child chunks、5,109 skipped void-only chunks；embedding input chars 的 p50/p95/p99/max
分别为 278/502/987/5,702。该结果是 rebuild 前 sizing diagnostic，最终 authoritative
count 以后续成功 rebuild 输出为准。

## Real Failure Cases and fixes

### Qwen normalized projection drift

真实 provider smoke 暴露 Qwen3 bfloat16 Normalize projection 的 Python-float norm 约为
1.002–1.003。根因修复是在官方 encode 后以 float 值做一次确定性 normalization，再执行
严格 unit-norm validation；没有放宽 normalized contract，也没有 retrieval fallback。

### Parent-scoped underfilled embedding calls

第一次 full run 的局部事实显示已写入 2,592 chunks 分属 588 Parents，平均仅 4.408
chunks/Parent，而配置 batch 为 8。旧 builder 在 Parent 边界强制结束模型调用，造成大量
underfilled calls。运行 1,839.21 seconds 后仅推进到 19,503 messages；该 derived run 被
主动中断并重建，未修改 canonical store。

最小修复是在 builder 内用 bounded pending queue 合并相邻 Parent，同时只在对应 Parent
的全部 vectors/metadata 写入成功后推进 canonical watermark。10 个单-child Parents 的
回归测试确认实际 provider batches 为 `[8, 2]`；zero-child Parents 不调用模型但仍推进
最终 watermark。该修复减少模型调用次数，但最终吞吐只以成功 full run 数据为准。

### Interrupted run left `building`

上述旧进程收到 Ctrl+C 后，`KeyboardInterrupt` 越过 `except Exception`，derived state
遗留为 `building`。builder 现捕获可重新抛出的 `BaseException`，先写
`failed / KeyboardInterrupt` terminal state，再原样传播中断。测试直接复现并验证终态；
不可捕获的进程强杀仍需下一次显式 rebuild 清理，不伪装成成功或 partial。

旧中断 run 的 `/usr/bin/time -l` 记录：maximum RSS 704,397,312 bytes（约 671.8 MiB），
macOS peak memory footprint 15,254,129,592 bytes（约 14.2 GiB）。它是失败运行的资源证据，
不能替代最终成功 run 的性能结果。

### Variable-shape MPS cache growth

第二次长跑在 1,376 chunks / 9,982 messages 时，`vmmap` 测得 process physical footprint
14.2 GiB、MPS graphics allocation 13.2 GiB，swap 使用约 15 GiB；短校准的 driver allocation
仅约 3.3 GiB。主线程 sample 显示它持续等待 `embeddings.cpu()` 的 MPS synchronize，说明
变量长度 batch 的空闲 cache 持续累积已成为真实内存/吞吐风险。该 run 在 1,524.16
seconds 主动中断，state 正确落为 `failed / KeyboardInterrupt`。

Provider 现每 16 个 document batches 调用一次 `torch.mps.empty_cache()`，query embedding
完成后也释放空闲 cache；只在模型实际位于 MPS 时执行，不改变 model weights、input、
dimension 或 output。真实 128-chunk 校准中，driver allocation 从第 15 批约 3,219 MiB
降到第 16 批后的 1,163 MiB，embedding time 34.309 seconds（3.73 chunks/s），process
peak footprint 约 3.77 GiB。最终 full run 启动后再次测得 footprint 3.7 GiB / peak
3.8 GiB，证明修复进入真实主链。

### Unavailable index performed query embedding too early

`SemanticRetrieval.search()` 原先在 store 的 queryable-state check 之前生成 query embedding；
因此 identity 已匹配但状态仍为 `building` 或 `failed` 时，最终虽会显式报错，却可能先
加载 Qwen 并执行无用计算。状态检查现前移到 embedding 之前，回归测试用调用计数确认
`building` 请求返回 `SEMANTIC_INDEX_NOT_READY` 且 query provider 未被调用；仍未加入
lexical fallback。

### Partial human upgrade provenance was not representable

初版 annotation set 只有 `llm_assisted` 与 `human` 两种 annotator type；逐条把一部分
provisional labels 升级为 `human_verified` 时，前者会拒绝 verified 条目，后者又会让整包
看起来像人工完成。contract 现增加显式 `mixed`：它必须同时包含 provisional 与 verified
statuses；`human` 则要求全部条目均为 `human_verified`。测试覆盖 partial upgrade 与禁止
把 mixed set 冒充 fully human verified。

## Full real-data Qwen rebuild

当前最终 full run 正在同一 Snapshot 上执行；完成后在此记录 authoritative message/
eligible/void/parent/chunk/vector counts、batch count、model/embed/write/total wall time、
throughput、RSS/MPS best effort、index size、status 与完整 identity。任务归档前不会把
`building` 写成 completed。

## Integrity validation after rebuild

成功后执行并记录：

- `status == completed`，configured/persisted identity exact match；
- canonical/indexed message watermark 为 473,236，dimension 为 1024；
- metadata rows、vec0 rows、state chunk count 一致，无 missing/orphan vector；
- bounded sample norm deviation 与 canonical first/last range recovery；
- 中文、英文、中英混合、短/长、emoji/Unicode、URL、code/technical、repeated/
  near-duplicate 的分层 canonical recovery；
- 新进程 reopen/status/search 与 identity mismatch stale detection。

## Blind annotation and paired Evaluation

Version-controlled query set 固定 12 个 diagnostic queries，覆盖 literal/lexical-easy、
paraphrase、中文自然语言、technical term、GitHub/tool recommendation、time-bounded、
synthetic no-result、broad ambiguous 与 nearby-context。每个 query 在同一 Snapshot 运行
lexical-only control 和 semantic-only candidate，合并后按
`(query_id, canonical_message_id)` 去重。

本地输出目录：`data/evaluation/semantic-vs-lexical-provisional-v1/`。预期文件：

- `blind-packet.json`：query、candidate 和 bounded context；不含 method/rank/score/variant；
- `sealed-metadata.json`：检索方法、rank、score、index/variant provenance 与 diagnostics；
- `annotations.json`：每个 blind ID 的 label、confidence、notes 和 verification status；
- `audit-queue.json`：低 confidence、uncertain、partial、方法分歧和指标高影响项；
- `metrics.json`：不含聊天正文的 paired report。

真实 OpenAI-compatible provider smoke 已成功返回严格 JSON；安全 identity 为
`opencode-go:deepseek-v4-flash:retrieval-relevance-v1`。所有自动标签被 contract 强制为
`llm_assisted_provisional`，`ground_truth_claim=false`，不得升级为 `human_verified`。
最终 annotation/label/confidence/audit counts 与 paired metrics 在 full index 完成后记录。

## Metric interpretation

- Precision@k：只在对应 top-k label resolved 时计算；
- Recall@k：仅为完整标注的 merged lexical+semantic candidate pool Recall；
- MRR / Top-k hit：只保留无需把 unknown 当 negative 即可确定的事实；
- relevant message coverage 与 partial relevant coverage 分开；
- `partially_relevant` 不计作 full relevant；
- corpus Recall 永远 unavailable，原因是 reference 不具备 corpus-exhaustive annotation；
- LLM 标签产生的数字全部是 provisional metrics，不是 human ground truth，也不作为
  production gate。

## Default Agent exposure and deferred decisions

`semantic_search` 已实现并可由显式 request/Controlled Variant 启用；production 默认
Agent exposure 继续是兼容 `search_messages`。在 human-verified labeled Evaluation 前，
不默认同时暴露 lexical/semantic，也不引入 RRF、reranker、Hybrid、另一个 embedding
model、dimensionality reduction 或 lexical fallback。

`dense_top_k=40`、Parent gap、Small Child bounds、overlap、context bounds 与 semantic-void
rule 都保持 baseline。paired diagnostics/labels 可以形成后续假设，但本轮不把主观观察
写成“最优参数”。

## Known limitations

- LLM confidence 是单条自评，不是人工一致率；audit queue 仍需人工抽查。
- Semantic retrieval 的评测 anchor 是 child 内首个非-void canonical message；正文与
  bounded context 一起标注，因此 message-level 指标应按该 anchor contract 解读。
- Candidate-pool Recall 不能外推为 corpus Recall。
- 本机性能只代表当前 16 GiB MPS 环境与固定 Snapshot，不是跨机器 SLA。
