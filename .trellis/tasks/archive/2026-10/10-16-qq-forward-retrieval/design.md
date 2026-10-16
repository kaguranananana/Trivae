# Design

## Boundary and decision
最小缺口是已保存嵌套正文未进入检索和 citation。保留 messages Source of Truth；以只读解析 content_json 生成独立可删除、可重建的 forwarded_messages 投影。FTS 继续唯一 messages_fts，加入子消息记录；semantic 继续唯一 builder/chunker/vector store。普通 structured 查询和统计只读 messages。

相比正文直接拼入父消息，独立投影能准确定位具体子消息、保留发送者和时间；相比把子消息插入 messages，不改变群消息数量、成员统计或 canonical 去重。代价是 read adapter 必须识别子消息 locator 和在父 JSON 中复核来源。

## Shared retrieval contract
MessageProjection 增加可选 forward 元数据（独立 frozen dataclass ForwardProvenance），以及缺失节点路径信息。子消息 internal_message_id 由最外层父 ID + JSON 路径组成，不使用摘要；source_message_id 为内部原始 ID。timestamp 始终是当前群外层转发时间，forward.original_timestamp 独立保存。forward 包含 root_message_id、parent_message_id、path、original_timestamp 和外层 source ID / source record 定位。session_id/display 由最外层父继承。内部发送者不是当前群 Membership 事实。

Read adapter 的 read_message_by_id、context、range 能恢复子消息；最外层父与嵌套路径始终足以从 canonical JSON 恢复并核验，索引不是证据真相源。context 不混合无关转发树。相同正文重复转发的不同父/群保留不同 occurrence，合并上下文按 occurrence ID 去重。

## Index lifecycle
FTS rebuild 单事务更新子消息投影、FTS 和版本/Canonical watermark，失败保留旧索引；查询拒绝旧版本或 Canonical 漂移。Semantic identity 增加本次投影版本，正常旧索引拒绝并需 rebuild。实际 rebuild 在相邻临时文件完成、校验后切换，保留旧文件以便回退。不得改动冻结 snapshot 或 experiment。

## 已复现的构建中断与显式续建

全量构建进程消失后，实际留下 building 状态、169476 条已覆盖普通消息及 20104 个块。旧 builder 只支持销毁后重建，不能完成这次长跑恢复。因此在既有 builder/store 上新增显式 `rebuild(resume=True)` / `semantic rebuild --resume`，不是自动重试，也不复用旧版本索引。

续建先核对 identity、Canonical revision/count 与 forwarded count；检查已有 metadata/vector 一一对应；按同一确定性双流重放，复用 metadata 完全匹配的已提交块，只计算缺失块。未完成 Parent 的进度通过重放恢复，最终覆盖/块数必须与干净构建一致。SQLite 的块提交与进度提交分属两次事务，合法中断时水位可滞后，不能将其当作损坏。missing/completed/stale 明确拒绝；损坏不降级，保留原数据并报告错误。报告区分实际计算与 reused_chunk_count。

## Seven questions
1. Responsibility：data ingestion owner 解析 QQ；storage owner 投影/SQL；retrieval owner 检索；Evidence owner 对当前 Tool Result 做可信 snapshot。
2. Failure：空节点、ID 重复、深层路径、内部时间早于转发、跨群同 ID、旧索引；用针对性 fixture 与真实 case 验证。
3. Observability：沿用 metadata/coverage/limitations、分类 stale/error 和 Trace；新运行独立保存 ignored data 下。
4. Attribution：未展开归 Source 数据缺失；漏索引归 Retrieval；丢 locator 归 Evidence/transport；模型不引用归 Answer Generation。
5. Decision：独立 derived occurrence、单检索入口，避免 Canonical 污染；无额外模型或基础设施。
6. Verification：回归、真实 embedding、production query、Citation/source inspection 与性能测量。
7. Regression：保存两项真实 case 的定位摘要和可复用合成回归；不把私人聊天正文提交 Git。

## 全库竞争候选的实际重排修复

全量索引通过后，真实短语「远程连接」的目标子消息已被 dense pool 召回，rank=28 / pool=80，却因结果 limit=20 被截掉；「情感锚点」rank=19。该 failure 是排序和后续容量保留问题，不是正文或向量缺失。只在原有 pool 内，对硬过滤合格的完整 query 字面命中优先排序，再使用原 dense rank；原 score/dense_rank 保留，策略进入 metadata/Trace。没有新增 FTS 依赖、扩大 K 或关键字特例，不改索引生成或 identity。

Context 和 Evidence 同时保护实际字面命中：范围超出 100 条时优先保留其 occurrence；canonical 结果继续按时间显示；模型 handle/正文/预算 slots 使用同一优先序。没有字面匹配时保留既有排序。候选池外仍明确属于 ANN 有界召回限制，由 Agent 自主组合既有 lexical 原语完成精确查找。
