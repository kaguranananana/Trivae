# 开发前审计

基线：main@22e464f。主工作区的 main 已有转发检索未提交文件；本 worktree 不复制或操作那些改动。独立分支 codex/qce-auto-import。

| 既有模块 | 已确认事实 | 本任务处理 |
| --- | --- | --- |
| SharedImporter | import_paths 稳定排序；先 Parser 验证，后每文件 BEGIN/COMMIT；record 错误 partial；未知异常 rollback | 调用同一入口，每次一个稳定快照，未改源码 |
| QQExportParser | json.load 校验完整 JSON、根结构与来源 identity；原 filename 属于 source/provenance；record normalize 保留原 index | 快照保留 basename；不二次解析，不改转发解析 |
| Canonical Store | source 由 basename 识别；消息按 session + source ID 去重；first-wins；不同 occurrence 的 conflict variant 保留；ImportBatch 有统计和完成状态 | 只新增运维表，不改原 Schema/事务 |
| FTS5 | rebuild 全表 DROP/CREATE/INSERT；read 比较 tokenizer strategy 与行数，stale 显式失败 | 不自动 rebuild；批次级增量工作持久化等待最终 updater |
| semantic builder/index | rebuild 全量 canonical stream，独立 sqlite-vec；chunk parent/child；identity/canonical count 判断 stale | 不改底层；迟到/转发数据的 parent 重切与水位等待集成 |
| CLI / Application | 原 import 经 create_application，会装配 Query、semantic、Evaluation 等资源；CLI 顶层仍 import Application | 新轻量 bootstrap 仅装配原 Store/Importer；顶层 CLI 加薄注册/分发，不改 TrivaeApplication |

## 历史接管证明与限制
旧 import_batches 不保存解析前的文件版本。复核实际复现了 parse 结束后、batch 创建前文件被 QCE 覆盖的竞争：mtime/ctime 早于 started_at 仍不能证明当前内容已导入。因此时间仅筛选候选；首次必须原 Parser 解码稳定快照并用 source_record_index + 已有原始 payload/variant 逐条核验完整覆盖，来源身份也须一致。匹配后跳过消息规范化和重复 SQL，持久文件版本后不再解析。duplicate_equal 未保留 incoming raw 等无法证明的历史走原 import_paths；已解码快照缓存给原入口，保证只解码一次。不靠文件名日期、大小猜测或内容摘要。

## 保持既有冲突语义
write_message 对 same canonical source + record index 会报告 conflict_count，但不会另建 variant；新文件 occurrence 的冲突保留 raw variant。自动导入保持此行为，不借任务扩展重写 provenance。测试分别验证同位置覆盖计数和新文件 variant。

## 必须对接的共享边界
1. 最终 index updater 在 bootstrap/ingestion 接入；成功返回必须代表交接的工作可检索，且重放幂等。
2. 外层 inserted_count 是否足以代表转发内部实际新增/回填，必须按转发任务实现核对；必要时增加最小变更信号。
3. lexical 增量需覆盖原消息及内部记录，正确维护最终 tokenizer/index identity；不能只按 message 总数证明所有层同步。
4. semantic 必须覆盖受影响 session 和迟到消息引起的 parent 边界变化；当前仅有全量 rebuild，不在本分支自行实现增量算法。
5. 普通 import 与 import-once 的写入调度需统一；当前仅 import-once 持互斥锁。
6. 集成后使用新消息、重复、旧时间迟到消息及转发内部消息验收 Canonical / FTS / semantic / Agent Citation；验收前真实 LaunchAgent 不启用。
7. 历史接管当前核验外层消息 raw/provenance；最终转发实现若需要回填既有内部投影，必须先完成回填，或在历史接管核验中接入其版本/完整性条件，不能以外层消息已存在代表内部投影齐全。
