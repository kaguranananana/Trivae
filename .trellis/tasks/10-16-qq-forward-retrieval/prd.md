# QQ 合并转发完整检索与证据追溯

## Goal

用户询问 QQ 合并转发内部讨论时，生产 Agent 能通过既有 lexical / semantic 工具检索具体子消息，生成有引用且可追溯的回答。

## Requirements

- 递归读取 forward/data/messages，保存内部身份、发送者、原始时间、直接父与最外层父、JSON 路径及当前群聊来源。
- 空 messages 节点显式标记 missing，不把预览当正文；原始 JSON 与 Canonical 统计、身份和去重行为保持不变。
- 接入现有 FTS5、semantic、context、Tool Result、Evidence/Citation、历史序列化与 source inspection。
- 当前群的时间过滤使用转发时间；内部原始时间独立展示。群范围来自最外层父消息，不推断原始群。
- 相同子消息在不同转发位置保留不同来源，单次投影幂等；跨群身份隔离。
- 新旧索引识别与 stale 检测明确，索引失败显式暴露。

## Acceptance Criteria

- [x] 两个真实 Failure Case「远程连接」「情感锚点」的 FTS5、实际 embedding semantic 与 production Agent 查询命中并提供准确子消息引用。
- [x] 回归覆盖多层、空节点、重复转发、跨群、时间范围、context、历史 Citation round trip、普通消息不变与 stale。
- [x] 本地必要索引重建；记录实际耗时、数量与查找时延；不修改原始文件、冻结 Evaluation/GT/实验。
- [x] lint、type-check、相关与全仓测试通过，按长期授权自动提交、归档、记录 journal 后统一推送。

## Notes

已知：QQExportParser 完整保存 content_json/raw_payload_json；现有 FTS5 与 SemanticMessage 只索引外层 content_text。真实群 messages[6235]、messages[6803] 漏检，用户报告 1,636 个展开父消息、5,675 条子消息及 11 个空的更深层节点，需本地复核。

不调用 QQ、不重新导出、不修改原始文件；不新增第二套检索系统、不按预览补全文本。已有 .opencode/package.json 改动不属于本任务。用户明确要求直接实现、测试、必要索引重建及安全范围内自主修复，不逐阶段询问；本次按此授权完成规划与实施。
