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

## 第二轮：合并真实运行副本并压缩共享历史快照

用户认为第一轮释放量不足，明确要求进一步清理。本轮扩大到已结束真实运行的重复数据库；下列结果更新当前存储状态，前文“真实运行快照保留”仅描述第一轮当时的操作边界。

- 删除55份重复数据库，逻辑体积81.37GiB，并删除3个指向已清理数据库的符号链接。覆盖最终格式、首轮预算、回复修复、观点覆盖、长窗及空日等已结束实验的运行副本；每次运行的独立结果库、答案、Trace、协议、请求账本和失败记录继续保留。
- 逐库只读核对Canonical版本、消息数、来源数及内嵌会话/Trace数量：811,892条语料的重复运行副本具有相同冻结来源和内嵌证据数量。809,850条、473,236条两个历史语料版本单独保留，不用新语料替代。
- 六份代表数据库原9.82GiB，无损gzip压缩后共1.91GiB。包括811,892条语料的旧bigram、新单字索引两个版本及共享语义库，809,850条Canonical，以及473,236条Canonical和语义库。每份压缩完成并落盘后，完整解压流逐块与原文件比较相等，才移除未压缩文件。
- 本轮实测可用空间2.47→15.88GiB，增加13.41GiB；结束时`df`显示约16GiB。整个测评目录`du`约2.9GiB，不能与APFS物理回收量混算。系统其他活动会影响之后的可用空间读数。
- 更新收据前2,770个原有非目标文件大小、修改时间保持；随后只更新61份存储说明。完整操作与失败记录在`data/evaluation/storage-cleanup-20261023/round2-manifest.json`，共享版本清单在同目录`shared-snapshots.json`。
- 清理入口最初将CJK目录3个符号链接按目标大小统计；删除原A/B后，跟随链接的stat明确失败。确认根因为别名后，改用lstat区分文件与链接，修正逻辑体积和文件数，并逐项保存删除状态。没有把链接统计为独立回收空间，原错误与已完成两项均保留在清单。
- 在线`/api/readiness`实际返回数据库ready/827,614、语义completed/827,614、Plan/Sol ready；0新增模型请求。线上数据库、原始导出及Trellis历史实验不在本轮清理范围。

### 当前共享归档与恢复

| 语料/索引 | 保留的归档路径 |
| --- | --- |
| 811,892条，旧bigram | `data/evaluation/quality-optimization-20261020/trivae.sqlite3.gz` |
| 811,892条，当前单字索引 | `data/evaluation/quality-repair-20261022/current-production-validation/snapshot/trivae.sqlite3.gz` |
| 上述语料共享语义库 | `data/evaluation/quality-repair-20261022/current-production-validation/snapshot/trivae.semantic.sqlite3.gz` |
| 809,850条历史Canonical | `data/evaluation/cjk-bigram-v1/snapshot.sqlite3.gz` |
| 473,236条历史Canonical及语义库 | `data/evaluation/gpt-high-ablation-20261018/resume-snapshot/trivae.sqlite3.gz`、同目录`trivae.semantic.sqlite3.gz` |

共享快照现在为压缩归档，旧脚本不能直接运行原数据库路径。重跑前先将对应`.sqlite3.gz`解压为原`.sqlite3`文件，再按原协议和源码创建各次独立运行副本；CJK候选A/B索引需按保存的输入和实验源码重建。不要让多个实验直接写入同一共享数据库。转发修复前的唯一语义索引另行原样保留。
