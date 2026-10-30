# R2离线对照结果（2026-10-30）

复用Z Code全部51个semantic候选池，不重算embedding，正式检索类恢复canonical区间。Baseline逐调用核对expanded ID集合与accepted chunk序列，51/51一致；Candidate的选中chunk对象逐项完全一致。两臂容量≤100、原scope和时间展示顺序均保持。

| 指标 | Baseline | Candidate |
|---|---:|---:|
| 最高dense排名chunk零消息交付的调用 | 19/51 | 0/51 |
| accepted chunk零消息交付的个数 | 271 | 208 |
| 已知GT消息按调用累计出现次数 | 8 | 18 |

40/51调用消息集合变化；已知目标新增10次，丢失0次。新增分布：Case01两条/一次调用、Case07一条/两次调用、Case08一条/四次调用、Case16一条/两次调用。这个分母是51个semantic调用，不能称为全库召回率、64Run事实覆盖率或答案准确率。后续预算层仍可能截断/缩短正文，排名不证明相关性，208个低优先级chunk仍因容量没有正文，保留partial/truncated。

修复为retrieval.py内部三处优先序传递，不改候选召回、Top-K、100条上限、过滤或Prompt。先红后绿两项；相关19项通过；全量1395 passed/1 skipped（39.64s），Ruff、Mypy148源码、diff检查通过。

原始输出为ignored data/evaluation/agent-quality-codex-20261030/semantic-rank-candidate.json；真实Agent阶段按R2-design.md执行，最终结论以后续续记为准。

真实预检曾两臂均被eval@v1的固定variant合同拒绝（eval v1 variant conditions differ）：该历史Suite只允许模型/Prompt变化，不能宣称它允许检索配置变化。HTTP账本仍0。保留两份preflight日志；没有放松验证或修改历史Suite，而是创建独立agent-quality-retention@v1实验Suite，精确复用原16 Case/version/GT/snapshot；两臂都使用该新Suite，移除只适用于历史eval的allow-prompt-variant参数。实际Agent实验结果不回填旧64Run矩阵。

补充精确S3核验：audit_projection_gaps.py逐项复核Z Code的26条S3记录，正式canonical区间证明7条为真实core容量损失、6条仅在parent但不在selected child、13条为数字区间假阳性。由此保留Z Code末端“7条真断层”的发现，否定把26条都当投影Bug。该离线精确核验0模型请求。

第二次真实入口预检两臂因工作区包含原始R1未跟踪材料及本轮改动，被干净Git门禁拒绝；未形成Run/HTTP，原日志保留。已完成的代码与确定性验证可创建本地阶段提交；使用该提交的独立干净实验worktree继续，原始R1文件不移动/不暂存，不关闭该门禁。
