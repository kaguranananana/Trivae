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
peak footprint 约 3.77 GiB。

cache release 后的第一份 full candidate run 仍暴露另一个独立峰值：一个超过 4,096 chars
的 input 与七个短 input 同批时，padding 令早期 peak footprint 达到 12.8 GiB。全量 sizing
显示只有 71/54,267 inputs 超过 2,048 chars，因此 builder 现保持原顺序并只将这些长输入
单独 batch，其他输入仍使用 batch=8；向量内容和 identity 不变。最终 run 越过同一区间的
455 chunks 后，实测 current footprint 2.7 GiB、peak 4.7 GiB，证明隔离进入真实主链。

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

### Canonical range boundary was not lexicographic

真实 semantic packet 首次运行在一个同 `timestamp`、同 `seq` 的 QQ 消息边界失败；原
`read_message_range()` 在比较高优先级排序字段时错误复用了最终字段的包含比较符，可能把
range 起点之前的同序消息带入。修复后高优先级字段始终使用严格方向，只有最后的
`internal_message_id` 使用 `<`/`<=`/`>`/`>=` 的调用方语义；新增同 timestamp/seq 的
SQLite regression，随后 12-query packet 重新生成成功。没有通过截断、跳过或 lexical
fallback 掩盖这个数据层错误。

## Full real-data Qwen rebuild

最终 full run 已在同一 Snapshot 上完成，且没有修改 Canonical Store：

| fact | measured value |
| --- | ---: |
| canonical / indexed messages | 473,236 / 473,236 |
| eligible / semantic-void messages | 391,549 / 81,687 |
| Parent count | 14,552 |
| Child / vector count | 54,267 / 54,267 |
| skipped void-only chunks | 5,109 |
| embedding batch size / count | 8 / 6,863 |
| provider model load | 12.665 s |
| embedding time | 13,222.604 s |
| SQLite metadata/vector write time | 19.812 s |
| builder elapsed | 13,313.366 s |
| end-to-end CLI wall time (`/usr/bin/time -l`) | 13,317.45 s |
| throughput | 4.076 chunks/s; 35.546 messages/s |
| maximum RSS | 847,446,016 bytes (808.2 MiB) |
| peak macOS footprint | 6,235,211,288 bytes (5.81 GiB) |
| derived semantic index size | 313,704,448 bytes (299.2 MiB) |
| final state | `completed`, `last_error=null` |

最终 identity 为 `Qwen/Qwen3-Embedding-0.6B / 1024 / last_token / normalized`、固定
retrieval instruction、`trivae-semantic-chunker-v1` 及完整 chunker config；configured 与
persisted identity 完全一致。最终 run 未使用其他模型、降维、reranker、RRF、Hybrid 或
lexical fallback。

## Integrity validation after rebuild

最终 CLI integrity report 与后续独立进程校验均通过：

- `status == completed`，configured/persisted identity exact match；
- canonical/indexed message watermark 为 473,236，dimension 为 1024；
- metadata rows、vec0 rows、state chunk count 均为 54,267，无 missing/orphan vector；
- CLI sample 16 的最大 norm deviation 为 `5.077e-09`，后续 sample 64 为 `6.503e-09`；
- canonical range recovery 为 16/16，后续独立 sample 64 为 64/64，invalid range 为 0；
- 中文、英文、中英混合、短/长、emoji/Unicode、URL、code/technical、repeated/
  near-duplicate 九类分层 canonical recovery 全部 selected/recovered；
- 新进程 reopen 状态为 `completed`，semantic smoke 成功返回 1 个 hit（partial 仅因
  bounded dense pool）；query instruction 改动的 identity probe 正确报告 `stale`。

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
- `evaluation/reports/semantic-vs-lexical-provisional-v1.json`：不含聊天正文的 paired
  report（安全统计报告进入 Git；local packet/annotation artifact 继续 gitignored）。

真实 OpenAI-compatible provider smoke 已成功返回严格 JSON；安全 identity 为
`opencode-go:deepseek-v4-flash:retrieval-relevance-v1`。所有自动标签被 contract 强制为
`llm_assisted_provisional`，`ground_truth_claim=false`，不得升级为 `human_verified`。
最终 packet 有 12 queries、173 个 canonical candidates；173/173 annotations 完整且无
重复，label counts 为 relevant=50、partially_relevant=17、not_relevant=106、uncertain=0。
confidence 为 min=0.5、mean=0.854971、max=1.0；audit queue 为 117 条，priority 为
high=22、medium=69、low=26。没有任何 `human_verified` 条目。

## Metric interpretation

- Precision@k：只在对应 top-k label resolved 时计算；
- Recall@k：仅为完整标注的 merged lexical+semantic candidate pool Recall；
- MRR / Top-k hit：只保留无需把 unknown 当 negative 即可确定的事实；
- relevant message coverage 与 partial relevant coverage 分开；
- `partially_relevant` 不计作 full relevant；
- corpus Recall 永远 unavailable，原因是 reference 不具备 corpus-exhaustive annotation；
- LLM 标签产生的数字全部是 provisional metrics，不是 human ground truth，也不作为
  production gate。

本轮 paired report 的 aggregate snapshot（均明确为 `llm_assisted_provisional`，只用于
后续人工抽查和假设生成）为：Precision@8 lexical=0.2396、semantic=0.2813；pooled-
candidate Recall@8 lexical=0.3474、semantic=0.6526；MRR lexical=0.4348、semantic=0.6212；
Top-8 hit lexical=0.6364、semantic=0.9091；partial relevant coverage lexical=0.3646、
semantic=0.6354。该 candidate pool 不是 corpus-exhaustive reference，corpus Recall 保持
`unavailable`，不能把这些数字升级为 human ground truth 或生产质量结论。

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
