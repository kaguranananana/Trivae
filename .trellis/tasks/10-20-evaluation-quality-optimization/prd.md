# 历史 Evaluation 失败复盘与质量优化

## 目标与授权
复用历史 GT、Trace、EvaluationRunner 和生产 query，定位可复现根因，执行同条件 A/B 并形成可信简历证据。用户明确授权独立完成审计、实验、最小修复与提交推送；不再请求流程确认。

## 要求
- 审计历史 D 的3条 context、49/67 evidence 和 Gate3的12条review，明确元数据、Trace与人工裁决边界。
- 先冻结当前 commit、数据库、官方 DeepSeek Flash、Prompt/工具/预算、评分与6–12个可核验 Development Case，再运行 Baseline；快照变化须新Case版本。
- 最小修复只能来自真实且当前可复现 Failure Case；所有候选无法复现则记录缺口并停止无依据优化。
- 相同条件配对 A/B；实际HTTP总量不超过120，失败和预检计数且不重置。保留所有异常、退化、token与延迟。
- Candidate冻结后准备12–18条未参与本次调参的真实独立验证，未人工审核不得宣称人工Holdout质量。
- 私有数据只保留ignored目录；历史与sealed产物不可修改；报告仅脱敏统计。

## 验收
1. 历史逐Case审计、根因证据或不能复现原因可追溯。
2. Baseline及Candidate条件、原始运行/Trace/Evaluation/Artifact和HTTP账本可审计。
3. 通过率分母含失败；事实/引用未审项明确pending/unavailable；不能以valid artifact替代内容正确。
4. 有实测根因才实施并补回归；pytest/ruff/mypy如实记录。
5. 报告、独立验证边界、简历账本、第五条bullet与面试追问放interview-docs并更新索引。
6. 只提交本任务内容，工作提交后收尾归档journal，统一push。

## 非目标
不重建Evaluation框架、不重写历史、不扩大业务预算、不硬编码测试答案、不改变Scope/Evidence契约、不把Assistant审核冒充人工。
