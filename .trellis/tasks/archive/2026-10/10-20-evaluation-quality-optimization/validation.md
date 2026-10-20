# 验证与结论（2026-10-20）

## 交付结论

实验与证据交付完成，未取得可信端到端质量提升。候选已拒绝，生产 `prompt.py` 恢复 `8def8d7` 原始源码；候选冻结提交 `3d9cc0e` 和全部负结果保留。没有放宽引用、零结果、权限或工具预算合同，也没有加入重试、fallback、Case特判。

20题正式A/B共40次，另有两题各一对敏感性复测，共44次生产Query。共享发送前记账的HTTP账本最终118 started / 118 finished，连续编号，全部HTTP 200，预算120，不再发起Provider调用。单次Query失败与传输成功分别归因。

## 实验完整性

- 数据副本固定811,892 canonical、14,119 recoverable forward occurrence、88来源、826,011 FTS行、98,012 semantic chunks；执行后快照未变化。
- Development固定8题19个target：两侧均8/8交付，Evidence 11/19→8/19，HTTP 21→21，Token 523,488→584,931。
- 调参外验证固定12题29个target：交付12/12→11/12，Evidence 23/29→22/29，HTTP 30→33，Token 651,643→799,248。Case来自历史Development，非fresh/blind Holdout。
- 补充复测独立分母各2题5target，两侧1/5；HTTP 6→7。立场题B恢复双向证据，揭示非确定性，未覆盖首次退化；工具题替代资源适用性仍需人工裁决。
- 44 raw、44 Evaluation run/result、44 Trace、43正式AnswerArtifact、44原生ReviewPacket对应；唯一run/trace身份，Trace事件完整性44/44。
- 777次附带消息引用的canonical、时间和正文前缀全部匹配，包含重复引用；这不是777个独立事实，也不证明语义支持。内容采集仍遵守既有bounded capture限制。
- 开发8对显式Prompt treatment条件检查通过：只有基础Prompt及其初始前缀允许不同，动态后缀、工具Schema、预算、模型、Case、Scope、索引等保持一致。固定执行顺序、Provider随机性和缓存限制已披露。
- 新快照GT适用性与答案人工语义审核仍pending。Assistant同21条必要事实的复核为provisional非盲审核，不是人工或独立LLM Judge；人工通过率、事实引用支持率与货币成本均unavailable。

完整私有材料位于Git忽略目录，公开metrics只投影运行身份、计数和性能。原生ReviewPacket保留失败侧无正式答案；未来人工展示隐藏arm/run，封存映射使用(split, case_id, side)，避免复测重名混淆。

## 根因与异常处理

- 历史context失败的目标回复未获取，不把旧bounded Trace未展示等同于未召回。Gate3仅两条明确内容fail，四条无交付失败与其余review分类分开；历史12份packet未改写。
- 当前工具发现题的已知target未进入完整Host/tool结果，零Provider词法诊断证明结合用途与资源线索可达。最小Prompt假设有真实失败支持，但候选仍采用宽词，主链路未闭合，故撤回产品改动。
- 调参外零结果题B：Runtime completed但Finalizer报`INVALID_FINAL_OUTPUT`。目标日完整零结果之外混入其他日期分组行，不满足辅助纯数字聚合合同；不是Provider故障，不为提分放宽校验，失败保留分母及Trace。
- 两次历史Prompt审计测试与旧matrix曾误绑定可变生产Prompt。修复为读取`8def8d7`完整原始源码fixture，保留历史artifact及原精确比较，未修改历史指标或放宽断言。
- 首次全套收集遇到仓库内临时worktree重复conftest，移至仓库外后正常全量收集；没有添加排除规则或跳过测试。
- 报告复核发现repeat复用Case时盲审身份遗漏split，已修复并增加真实歧义回归；失败侧保持`answer_text=None`。
- 应用管理worktree创建曾长时间pending；实际实验使用冻结detached CLI worktree。结束后管理worktree已出现，收尾按工具归档；临时实验worktree清理不影响冻结commit及私有证据。

## 最终验证

- `.venv/bin/pytest -q`：**1201 passed, 1 skipped in 27.38s**。
- Ruff覆盖src、tests及两个实验脚本：**All checks passed**。
- mypy src：**Success: no issues found in 128 source files**。
- harness/report专项14项通过；历史fixture原文与原始commit精确一致，生产Prompt也精确恢复。
- 新增4条Claim账本与总10条Claim账本通过共享validator；分子/分母、review状态、commit、证据限制齐全。
- 脱敏JSON与文档链接检查通过；最终Git whitespace/staging检查由提交前收尾完成。

只提交本任务改动；既有`.opencode/package.json`、数据库import lock和未命名Obsidian base不纳入。按项目长期授权执行工作提交，再归档/journal提交，最后统一push；远端状态以实际push结果为准。
