# 独立语义快照准备

## 问题与决定

实测：历史 Prompt 审计冻结 Canonical 共 473236 条消息；其持久语义索引为 `trivae-semantic-chunker-v1`，当前生产配置为 `trivae-semantic-chunker-v2-forward`。两者不能作为有效同条件实验索引。

库存只读核验结果：

| 索引 | Chunker | Canonical 消息数 | 状态 | 可直接复用 |
| --- | --- | ---: | --- | --- |
| Prompt 审计/讨论质量冻结快照 | v1 | 473236 | completed | 否，身份不同 |
| 当前 data 索引 | v2-forward | 797278 | completed | 否，Canonical 快照不同 |
| 转发验证 attempt1 | v2-forward | 765780 | failed | 否，未完成且快照不同 |
| 转发 failure-case | v2-forward | 2 | completed | 否，微型验证快照 |

选择现有 `Application.rebuild_semantic_index()`：先用 SQLite 只读连接和 backup API 将原冻结 Canonical 复制到 ignored `data/evaluation/gpt-high-ablation-20261018/resume-snapshot/trivae.sqlite3`，然后生成独立 `trivae.semantic.sqlite3`。保留相同文件名，使现有 `database_identity` 合同成立；路径隔离历史文件。不得将 v1 改标签，也不从不同快照直接复制已完成身份。

真实 Embedding 使用现有 `SentenceTransformerEmbeddingProvider` 与本地缓存 `Qwen/Qwen3-Embedding-0.6B`；1024 维、last-token pooling、normalized=true、现有 query instruction 和默认 batch=8 均保持现有实现。没有 GPT/OpenAI 推理请求，不触碰总预算账本。

## 验证与可观察性

私有准备脚本 `resume-snapshot/prepare.py`，执行：

```sh
.venv/bin/python -u data/evaluation/gpt-high-ablation-20261018/resume-snapshot/prepare.py > data/evaluation/gpt-high-ablation-20261018/resume-snapshot/build.log 2>&1
```

脚本拒绝覆盖现有目标；使用生产入口构建，错误直接暴露。构建前后比较冻结 `snapshot_id` 与完整 deterministic manifest 字符串，检验消息/时间/Source/lexical 身份。完整身份和私有统计留 ignored 目录。完成后检查 `semantic_index_status()`、`validate_semantic_index(sample_size=32)`、原生/转发覆盖水位与向量完整性。

首轮真实全量构建保留 447 个已提交块后，经正常 SIGINT 停止并记录 `KeyboardInterrupt`，不丢弃既有进度。考虑当前索引同一模型的已存精确输入，后续用私有 `resume.py` 包装 EmbeddingProvider，并仍调用 `Application.rebuild_semantic_index(resume=True)`。

`SQLiteSemanticIndex.reusable_vectors()` 强制依赖会变更源库的增量事务，不能作为只读跨库接口直接调用。因此私有脚本使用 mode=ro 连接并复制到连接私有 TEMP 池，沿用生产增量池的 `embedding_input TEXT PRIMARY KEY` 全文等值规则。缓存来源必须完整身份逐字段相同、completed、format1、metadata/vector 一一对应且输入不缺失；只取相同输入对应的真实 Qwen float32，并通过现有 unpack/validate 检查维度、finite 与 norm。未命中继续调用原 SentenceTransformer provider，不猜近似文本、不按 chunk_id 或消息总数复用。之前真实计算的 447 块由生产 resume 逐字段验证后保留。

只读完整覆盖审计（复用现有 Chunker，不执行模型）测得：目标 54651 个块，其中 460 个转发块；38558 个输入可精确命中当前真实缓存，16093 个必须真实编码。最长连续未命中 13275 个；31 个未命中输入超过 Builder 的 2048 字符单条隔离阈值，全部未命中输入合计 4281275 字符。

batch=8 续建阶段保留 14949 个缓存命中与 1428 个真实新算块，加首轮 447 真算，共已提交 16824 个。随后经正常 SIGINT 保存状态，采用 Provider 已有公开 `batch_size=32` 继续生产 resume；没有修改模型精度、model_loader、Pooling、归一化或向量合同。当前真实 Builder 续建进行中，最终统计待完成后补充。本次不改生产算法、GT、Holdout 或历史 Evaluation。

## Lexical 版本合同的关联发现

原冻结 Canonical 只保存旧 `lexical_tokenizer_strategy=unicode61+cjk-bigram-v2`，缺当前 `lexical_forward_projection`、canonical revision/count 等标记和 `forwarded_messages` 派生表。因此原源库与初始副本的 lexical 在当前版本都显式 unavailable；不是 Prompt 或 Provider 导致。

当前 Canonical parser 从历史 381 个转发容器解析到 3500 条内部 occurrence。正确调用现有 `rebuild_lexical_index()` 会把 FTS 数从 473236 增至 476736，而既有 DatasetSnapshot ID 包含 lexical 行数，因此必须如实生成新派生快照身份。不会覆盖历史 Case/GT；主实验创建显式派生 Development Case，只变更新快照绑定及 provenance，完整保留质量约束，并在 A/B/C 中固定同一新快照。

并发尝试创建第二 Application 时因语义扫描长读事务返回 `database is locked`，未执行 lexical rebuild；改为语义完成后顺序执行，保留错误日志。`verify_canonical.py` 用 `IS NOT` 对 messages/source 全字段比较，输出差异、新增、删除数量；完整私有结果保存在 `canonical-equality.json`，真实新清单为 `dataset-snapshot.json`。

已完成重建前原生事实比较：messages 的 24 个字段、473236 行及 sources 的 8 个字段、14 行，差异、新增、删除计数全部为 0；Canonical/source identity 均相同。Lexical 重建后再次检查全部字段，差异、新增、删除仍全部为 0；Canonical/source identity 相同。

实际修复步骤：正常 SIGINT 保存到 18320 个语义块（3371 个真实编码、14949 个精确缓存复用），仅对独立 Canonical 执行 `PRAGMA journal_mode=WAL`，再调用 `Application.rebuild_lexical_index()`。该 journal 模式调整由真实 `database is locked` 证明需要，用于独立快照的读写隔离；没有更改历史库。之后仍由生产 `rebuild_semantic_index(resume=True)` 稳定续建，batch=32 不再为吞吐重启。

Lexical 真实统计：8.120 秒、FTS 476736 条 = 原生 473236 + forward occurrence 3500；45 个 unexpanded forward 节点；canonical revision 仍为 0，当前 lexical readiness 通过。真实新 DatasetSnapshot ID：

```text
snapshot-v1:messages=473236:first=1753011800000:last=1786847688000:sources=14:lexical={'present': True, 'message_count': 476736}
```

此 ID 与原件不同完全归因于真实派生 FTS 行数变化，原生 messages/source 全文没有变化；不能将独立副本伪装成原冻结派生清单。

## 边界与演进

根因归属：派生索引身份漂移，非 Prompt 质量。当前 v2 的另一快照不能证明此冻结快照索引 ready。全量重建成本为真实本地模型计算时间和独立磁盘占用；不会计作 GPT 消融请求费用。若未来出现同一 Canonical、相同完整身份、已完成且通过完整性检查的派生快照，可按既有合同复用；本次库存没有可直接整库复用者。

Interview Defense Notes：问题证据是只读 `semantic_index_state`；选择原因是复用生产 Builder 和既有身份检查；失败诊断是 `build.log` 与持久状态；有效性依赖最终 completed/readiness/抽样回读，不能用启动成功替代。


## 设备与实际吞吐

相同生产 constructor 使用本地现有权重独立加载实测：`device=mps:0`、`dtype=torch.bfloat16`、batch32，加载 10.55 秒；运行环境为 torch 2.13.0 / transformers 5.16.1 / sentence-transformers 5.7.0。设备默认选择规则也确认 MPS 可用，没有 CUDA。未改变运行中 Builder 的精度或加载器。

只读观察 10 个持久化批次，每批 32 块，间隔毫秒为 10717、17669、9143、7968、7754、7599、9162、7268、7054、8127；此指标包含编码、切块和存储，不能冒充纯模型调用耗时。纯每次 encode 延迟当前进程未单独埋点，明确未知。已有公开 batch 参数已使用可用加速器，没有为缩短时间修改向量语义。完整准备操作记录在私有 `commands.md`。

## 完成验收

后台构建已正常结束。最终status=completed，473236原生与3500forward覆盖水位均匹配，revision0；当前配置与持久身份完全相等。54651 metadata chunks与54651 vectors一一对应，missing/orphan均0；32个抽样向量及32个范围回读全部有效，最大norm偏差5.077118725438368e-09，范围invalid0。index文件378036224字节。

最后一次resume用时5429044.72ms（不含此前轮次），真实provider统计为23162精确缓存+13169真实Qwen；与已保存18320块合计54651。跨所有轮次共38111精确缓存复用、16540真实Qwen计算；独立覆盖审计的16093“必须新算”与实际计算量不同，因为最初尚未接精确缓存时已真实计算447个本可命中缓存的输入。不能把Builder的embedding_count36331误称最后阶段真实模型新算数，它包含包装Provider返回的真实缓存。没有GPT调用。

新派生16条Case正式创建成功；原始文件及全部质量约束保留。除证据定位/精确全量集合/空窗外，Host相对7天仍锚定archive_latest，15221 eligible、partial；指定UTC日期只读COUNT=883，与原GT相等。
