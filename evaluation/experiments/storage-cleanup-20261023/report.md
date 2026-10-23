# 测评数据库副本清理

日期：2026-10-23。用户明确授权清理已核对的重复测评数据库。本次仅执行此前清单的第一、二批，未清理真实推理运行使用的快照或最终格式实验的四份数据库。

## 实际操作

- 第一批：14组零推理准备数据，删除28份大数据库，逻辑体积44.64GiB。逐组核对请求账本为0，保留认证预检失败及其他所有小型工件。
- 第二批：12组已完成的离线重放、投影与CJK索引对照数据，删除29份可重新准备的数据库，逻辑体积45.64GiB。保留原协议、输入、结果及源码版本记录。
- 合计删除57份数据库，逻辑体积90.28GiB。APFS写时复制共享磁盘块，实测可用空间约0.74GiB→2.48GiB，实际增加约1.75GiB，不能把逻辑体积报告为释放空间。
- 删除前记录完整路径、大小、修改时间及所有非目标工件。删除后核对2,805个原有非目标文件全部存在且大小、修改时间未变；该检查不代表逐字节内容比较。随后新增26份存储收据，修正4份旧收据指向已删除准备副本的问题。

## 清理范围

以下目录均位于`data/evaluation/quality-repair-20261022/`，仅删除其中大于100MiB的`.sqlite3`数据库，不删除目录及其他文件。

| 分组 | 目录 |
| --- | --- |
| 零推理准备 | compact-baseline、compact-candidate、compact-v2-baseline、compact-v2-candidate、current-baseline、snapshot-reuse-smoke |
| 零推理时间窗模板 | temporal-release-14d、temporal-release-2d、temporal-schema-empty、temporal-schema-v2-14d、temporal-schema-v2-2d、temporal-schema-v2-empty、temporal-volume-2d、temporal-volume-empty |
| SDK投影重放 | sdk-compaction、sdk-compaction-promoted |
| 时间窗离线重放 | temporal-batch-fixed-replay-v2、temporal-plan-audit-public、temporal-plan-replay及其v2—v5 |
| CJK索引对照 | cjk-unigram-column-v2、cjk-unigram-separate、cjk-production |

## 保留与恢复

- 历史共享语料及语义索引：`data/evaluation/quality-optimization-20261020/`中的`trivae.sqlite3`与`trivae.semantic.sqlite3`。
- 当前词法索引共享快照：`data/evaluation/quality-repair-20261022/current-production-validation/snapshot/`中的上述两份数据库。只读核对冻结协议身份完全一致，811,892条消息，词法readiness通过。
- 所有真实推理的答案、Trace、请求账本、失败记录、来源核验及最新空日／两天／两周运行快照均保留。线上数据库及原始聊天导出不在清理范围。
- 完整本地操作清单位于`data/evaluation/storage-cleanup-20261023/manifest.json`，每个清理目录新增`snapshot-storage.json`记录数据库去向。四份历史收据保留旧共享路径并转向现存共享快照。
- 最终复核：57份目标数据库均不存在；除明确更新的4份存储收据外，2,801个原有非目标文件大小、修改时间保持。所有共享引用均指向存在的数据库。
- 本地Web的`/api/readiness`实际返回数据库ready、827,614条消息、语义completed且827,614/827,614、Plan/Sol ready；没有触发模型推理。
- 旧离线脚本不能直接使用已移除的数据库路径；重跑前需按原协议、对应源码及实验索引配置重新准备。共享快照保留源语料，不承诺其派生索引与历史实验候选逐字一致。

本次未修改产品代码、模型配置、历史实验结论或真实请求计数，也未发起模型请求。验证以实际文件保留、共享快照身份、索引readiness及在线健康检查为准，不重复完整产品测试。
