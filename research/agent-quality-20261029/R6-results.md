# R6离线验证结果（2026-10-30）

- 固定真实Case08 Envelope和10933预算，旧Host75条/估算10841/目标08b不可见，Candidate80条/估算10742/目标08b可见。读取正式Canonical恢复已选range的优先序，目标从不在模型输入变为实际可见；正文/候选/容量/预算不变。持久化input及完整投影在ignored目录。
- 对原51个semantic调用，先按R2修复生成同一ranked Envelope，再分别过旧/新Host；48调用可比较、3调用两侧均因原Trace只剩控制预算而明确ToolResultProjectionError，没有偷偷当成检索零命中。51总调用中的已知GT模型可见出现次数10→14，新增4/丢失0，7调用可见集合变化。四项新增均为Case08不同原始Run中的同一已知目标。没有新投影错误。
- 所选chunk和capability集合的R2结论不变：1007 selected chunks完全相同，capability目标8→18，最高dense排名整块丢失19→0。不能把这两个不同Baseline/阶段的分子直接合并成全链路召回率。
- 扩展原两项回归至capability→Host预算端到端，先红后绿；相关43通过。全量1398 passed/1 skipped（37.49s），Mypy148源码、Ruff src/tests/scripts与新脚本、diff检查通过。
- 首次广泛Host脚本在原本只有199控制预算的调用上如实抛错；第二版显式登记该已知投影失败类别，仍不修改产品失败边界。两份日志保留；最终3/3不可投影体现原预算条件，不算新候选退化。

R2真实阶段共16个计划Run，Baseline8/8完成，Candidate7/8完成；Case10的另一次在Unicode295因字符串内未转义英文引号失败（parser已关闭字符串、期待逗号/右花括号，却收到“手”）。这是与历史Case03同类的Provider非法JSON症状，原最终正文没有完整落盘，不能声称完整标准parser重放；正常解析规则与JSON mode不改，没有补跑或放宽。73次累计DeepSeekHTTP包含这次失败和先前两个中断流，剩余177；15份完整回答按原v2.1评审中，不给失败Run编分。

R2新Failure为独立研究记录，不把R6当成协议修复；后续R6若开展真实实验，使用新Variant身份，原失败Run仍保留，不回填旧矩阵，也不重跑原Baseline。所有当前实验与额度见STATE/LEDGER/budget。
