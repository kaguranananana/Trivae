# Import real chat records with incremental group merging

## Goal

把项目根目录 `data/raw` 中的真实 QQ 群聊导出文件导入 Trivae 的第一版 Canonical Store。
同一 QQ 群的全量文件、增量文件和重复导出必须按稳定群号合并，稳定消息 ID 重复时只保留一条 canonical message，同时保留可追踪的来源和冲突统计。

## Requirements

- R1. 读取 QQChatExporter V5 与 0.1.0 两种当前真实文件格式，并在 Adapter/Normalizer 中消化格式差异；Importer 和 Store 不出现按导出版本分支。
- R2. 群身份使用 `platform + external_chat_id`。0.1.0 文件优先读取 `chatInfo.peerUid`；V5 文件从当前文件名中的群号解析。无法得到稳定群号时必须显式报错，不能按群名猜测或合并。
- R3. 消息去重优先使用 `platform + session + source_message_id`。当前真实数据均有稳定 `message.id`；对缺失 ID 的独立测试场景使用可解释的结构化 fallback identity key，不实现哈希算法。
- R4. 同一 session 的重复稳定消息只写入一条 canonical message。重复记录的输入数、去重数和按规范化核心字段发现的 payload conflict 必须进入 ImportBatch/来源记录；不同 session 即使消息 ID 相同也不能合并。
- R5. Canonical message 保留查询和追溯所需的 session、author identity、membership display、source message ID、seq、Unix 毫秒 timestamp、规范化 message type、原始 content/raw payload、reply 关系、recalled/system 状态。
- R6. 导入操作按输入文件形成可观测 ImportBatch，记录 received、inserted、duplicate、conflict、error、status 和开始/结束时间；文件级解析失败不能静默跳过。
- R7. CLI 提供薄的 `trivae import` 入口，支持指定 raw directory 和 SQLite 输出路径；重复执行同一批文件必须幂等，并返回可核对的导入摘要。
- R8. 原始 JSON 文件保持不变；生成的 SQLite Canonical Store 是可重建检索索引的事实来源，当前任务不生成 Embedding、Lexical Index 或 Query/Agent 链路。

## Acceptance Criteria

- [x] `PYTHONPATH=src python3 -m trivae import --raw-dir data/raw --database <path>` 能成功处理当前 14 个 JSON 文件，识别 7 个 logical ChatSession。
- [x] 当前数据的汇总满足：received 为 494,628；按 session + stable message ID 去重后的 inserted 为 473,236；重复数、conflict 数和每文件 ImportBatch 可从数据库/CLI 摘要核对。
- [x] `cs61abc`、`一群开心快乐的小奶龙`、`星河社（星河大学）`、`爪哇就业交流群`、`识海(吉祥物是西娅公主)`、`贺兰の计算机技术交流群` 的多文件输入各只形成一个 session；同群增量消息不会因文件名不同而新建群。
- [x] 同一 `message.id` 的重复记录不会产生两条 message；同一 ID 出现在不同 external_chat_id 时分别保留。
- [x] 旧版/新版导出在 canonical message 中可查询，原始 payload 与 source file provenance 可追溯；规范化差异不会静默覆盖。
- [x] 对缺少 stable group ID、非法 JSON、缺少稳定 message ID 等输入，测试证明错误显式暴露或进入可见的 batch error，不会静默吞掉。
- [x] 单元测试覆盖文件名群号解析、两种导出格式、时间戳、reply、重复/冲突和幂等重跑；真实数据导入完成后执行 SQLite 计数校验。

## Notes

- 真实数据盘点：14 个文件、7 个 external_chat_id、494,628 条输入消息；稳定 ID 去重后预期 473,236 条。
- 同一稳定消息在旧版 V5 与新版 0.1.0 导出中存在 type、reply、图片占位文本和成员显示名差异。第一版不把差异静默覆盖：canonical 记录按确定性输入顺序选定，其他规范化版本保存在 message variant/conflict 记录中。
- 任务执行前必须通过规划摘要审批；`task.py start` 之前不修改产品代码。
