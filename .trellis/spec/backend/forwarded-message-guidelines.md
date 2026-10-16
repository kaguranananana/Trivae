# 合并转发检索与证据契约

## 范围与所有权

`qq_forward.py` 是 QQ 已保存嵌套 JSON 的解析边界；`sqlite_read.py` 从 Canonical root 恢复 projection。`forwarded_messages`、FTS 与向量均为可重建派生数据。子消息不进入 `messages`、`users` 或 `memberships`，不改变普通群消息统计、去重、时间边界和 SQL 聚合。

## Signatures

```python
# 独立读取内部 occurrence；普通 iter_semantic_messages/count_messages 口径不变。
SQLiteCanonicalReadRepository.iter_forwarded_messages(batch_size: int) -> Iterator[MessageProjection]
SQLiteCanonicalReadRepository.count_forwarded_messages() -> int
SQLiteCanonicalReadRepository.canonical_revision() -> int
SQLiteCanonicalReadRepository.forward_content_gaps(scope: ScopeFilters) -> tuple[str, ...]
# 同版本、同源水位的未完成构建可显式续建，默认仍为从头重建。
TrivaeApplication.rebuild_semantic_index(*, resume: bool = False) -> SemanticBuildStats
```

`MessageProjection.forward: ForwardProvenance | None`、`unexpanded_forward_paths: tuple[str,...]` 为跨层新增可选字段。`LexicalIndexStats` 分别报告 `canonical_messages`、`forwarded_messages`、`unexpanded_forward_nodes`，`indexed_messages` 是 FTS 总行数。`SemanticIndexState` / `SemanticBuildStats` 单独保存 `forwarded_message_count` 和 `indexed_forwarded_message_count`，不改变 `canonical_message_count` / `indexed_message_count` 的原生统计含义。

## 来源与时间

- occurrence ID：`<root internal ID>#forward:<element index>.<message index>...`，每层保留两个数组下标。同一内部原始 ID 在不同位置、父消息或群内转发时拥有独立 occurrence。
- `ForwardProvenance` 保存 root、直接 parent、完整 JSON path、内部原始 timestamp、外层 source message ID，以及 Canonical 来源文件和 record index。`container_path` 是直接 messages 数组的计算属性，用于隔离同一父消息下的多个 forward elements。
- `MessageProjection.timestamp` 和快照 `timestamp_ms` 始终表示外层消息进入当前群的时间。所有群聊范围和半开时间过滤 `[start,end)` 依此执行。内部原始时间单独保存在 `forward.original_timestamp`，缺失时显示未知。
- sender 与 source message ID 表示具体内部消息；session 表示当前导出群，不证明内部消息最初来自哪个群。

## 正文、缺失与上下文

递归遍历 `content.elements[].type=forward` 的 `data.messages`。转发容器的 `content.text` 可能复制预览，只索引其真实 text elements；叶子正文保留完整规范化文本，原始 JSON 不改写。空或未提供 messages 的节点记录 `unexpanded_forward_paths`，不得从 preview 补全正文。

子消息的 context / semantic range 限制在同一 root、直接 parent 和 container 中；不能把两个独立转发对话拼成连续原生聊天。来源回读通过 root + 数字位置从 Canonical JSON 恢复，不把派生表正文或模型生成快照当作真相。

## 索引与失效

唯一 `messages_fts` 同时包含普通消息及子消息 occurrence。重建以单个 SQLite 事务替换 FTS、forwarded projection 和版本水位，任何异常回滚。`canonical_revision` 通过 messages insert/update/delete 触发器单调增加，解决数量不变但正文或来源变化时的漏失效；删除派生索引不能重置 revision。

Semantic 沿用既有 builder/chunker/sqlite-vec。普通与转发双流分别分块，在同一个向量库查询；v2-forward identity 明确拒绝旧版本。覆盖进度分别记录 Canonical 和 forwarded 数量，构建中 revision 改变须失败。群/时间过滤进入 KNN 候选选择前，恢复后仍逐条核对 scope。

全库实际短语查询证明，正确子消息可能已在 dense pool 内（本次 rank 28 / pool 80），却在 `limit=20` 截断时落选。因此在既有有界候选池内，先恢复正文并执行群/时间/发送者/类型等硬过滤，再按完整 query 的 casefold 字面串是否出现在合格消息中重排，随后保持原 dense rank。`ranking_strategy=literal_then_dense_v1`、`literal_candidate_count` 与 Host-only `literal_message_ids` 记录该规则；cosine score 和原始 dense rank 不改写。没有字面匹配时仍保持原 dense 顺序，不增加候选池、不调用 FTS、不引入新模型或 fallback。

实际字面命中的 occurrence 通过 `ContextExpander.expand_ranges(..., preferred_primary_message_ids=...)` 优先保留，canonical 结果仍按时间展示。Evidence 的短 handle、模型正文和 token trimming 使用同一命中优先序，防止较晚的真实命中被早期无关 core 或预算裁掉。该规则只在已召回候选内排序；候选池外的字面全文召回仍由既有 FTS 原语承担，不能将 ANN 结果声称为穷举。

Host 对已确认 literal 的初始有界原文不再统一缩至 32 字，再沿既有优先序省略其他 hit。必须区分“来源 handle 还在”与“查询正文仍可见”：真实 52 字、offset 40 的情感消息曾在默认 16000 预算下丢词。初始 600 字模型 excerpt 和 1000 字 Host excerpt 上限保持既有契约，不声称无界传输；所有裁剪仍显式标记。真实核验同时保存 semantic-model 投影，核对正确来源中的词面与实际正文 Citation binding。

内部有效短正文不受原生 24 字符 skip threshold 限制。QCE 将图片加文字优先分类为 image，转发分支须去掉已知媒体占位符后检查真实文字，不能按 image 类型丢弃 caption；原生规则保持既有行为。语义输入仍受已确认 `embedding_max_chars=6000` 上限约束，超过上限的正文需要新的真实 case 再决定分段策略，不能声称无界覆盖。

源文件缺失与索引状态分开表达：完成索引仍可能具有 `coverage.status=partial`、`known_gaps=unexpanded_forward_content`。范围内空节点的数量及有界位置摘要进入工具结果，即使没有命中也不能声称完整穷举。错误不静默降级或改用 LIKE。

长跑实际中断后，`semantic rebuild --resume` 只接受相同 identity、Canonical revision/count 和 forwarded count 的 building/failed/partial 索引。metadata/vector 必须一一对应，块 metadata 必须与确定性重放逐字段一致。合法强停可使 progress 落后已提交块，续建通过重放恢复未完成 Parent；`reused_chunk_count` 和本次实际 `embedding_count` 分开报告。missing/completed/stale 或损坏直接报错；没有自动续建、重试或跨版本缓存。

## Evidence 与验证

工具结果公开具体子消息及双时间语义；Source Handle 仍归当前 run/tool/result/item。Host 从可信 projection hydrate Citation snapshot，保留完整转发来源；Conversation codec、CLI/TUI 和 Web 来源展示使用同一快照。缺失限制随当前结果进入最终 Artifact，不能由模型漏写而消失。

回归入口：`test_forward_retrieval.py`、`test_forward_semantic.py`、`test_forward_evidence.py` 和 `SourcesBlock.test.ts`。真实核验脚本 `verify_forward_retrieval.py` 必须使用新的本地输出目录；真实聊天证据留在 ignored `data/evaluation/`，不修改冻结 Case/GT/实验。验证包括原始 JSON 回溯、重复/跨群/多容器、双时间范围、空节点、stale/rollback、实际 embedding 和生产 Agent。

## Validation & Error Matrix

| 条件 | 可观察行为 |
| --- | --- |
| 空/缺少 `data.messages` | 缺失路径 + coverage gap；不生成 preview 正文 |
| 内部 JSON 结构不合法 | `RetrievalError` 带 root/path；重建回滚 |
| 旧 FTS 版本 / revision 漂移 | `RETRIEVAL_LEXICAL_INDEX`，不改用 LIKE |
| 旧 semantic identity / revision 漂移 | `SEMANTIC_INDEX_STALE`，不执行 query embedding |
| 构建中 Canonical revision 改变 | failed 终态并抛出 `SemanticIndexStale` |
| 续建时 identity / 来源水位变化 | `SemanticIndexStale`，保留既有数据 |
| 续建时 metadata / vector 缺失或错配 | `SemanticIndexStorageError`，不猜测或重算掩盖损坏 |
| 已提交块但 progress 尚未提交 | 接受合法滞后，重放恢复精确覆盖 |
| Source inspection 超出群/时间 | `SourceInspectionError`，不返回原始上下文 |
| 同原始 ID 跨父/群重复 | 保留多个 occurrence，按 scope 返回各自来源 |

## Good / Base / Bad Cases

- Good：内部消息原时间为 6 月，9 月被转入当前群；9 月范围命中并同时显示两种时间，引用具体数组位置。
- Base：普通消息 `forward=None`，消息数和现有 sender/时间排序不变。
- Bad：把内部消息插入普通 `messages`，根据 preview 补正文，或在全库 Top-K 结束后才裁掉其他群而耗尽目标群候选。

## Wrong vs Correct

```python
# 错误：混淆当前群活动、原始发送时间与内部消息身份。
store.write_message(internal_child)

# 正确：保留 root，具体子消息作为派生 occurrence，并从 root JSON 回读证据。
tree = project_forward_tree(root_projection, canonical_content)
child = tree.messages[0]
```

续建回归入口 `test_semantic_resume.py` 应断言：失败后只计算未保存块；部分 Parent、跨普通/转发 batch 与干净构建等价；合法滞后恢复；身份/水位漂移、损坏、missing/completed 均显式拒绝。CLI parser 和 Application facade 必须调用同一个 builder flag。
