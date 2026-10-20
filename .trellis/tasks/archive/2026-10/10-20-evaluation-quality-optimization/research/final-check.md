# 最终复核记录（2026-10-20）

## 范围与方法

按本任务 PRD、design、implement 和 check.jsonl 中的项目规范，复核实验 harness、派生报告、历史 Prompt fixture 测试、开发集统计与候选回退。未调用 Provider，未修改生产代码、测试或历史产物，未提交；本文件由主会话明确要求新增。

复核直接读取当前源码、冻结条件、真实开发运行与共享 HTTP 账本。对报告 `summarize` 的验证将写入替换为内存捕获，再以原生 `ReviewPacket.from_dict` 校验，不重新运行查询，也不改写私有实验材料。

## 已发现并修复的问题

- 文件：`evaluation_quality_report.py`。
- 问题：盲审展示和封存映射原本只有 `case_id/side`。已登记 repeat 复用两个开发 Case，跨 split 的同名展示会失去唯一身份。
- 修复：主会话已在两边加入 `split`，以 `(split, case_id, side)` 关联；并新增 `test_evaluation_quality_report.py` 回归。复核代理未自行编辑这些文件。
- 同时核对主会话新增的失败 ReviewPacket：正式答案不存在时使用 `answer_text=None`、空来源和失败 limitation，保留运行的评审分母；不采用未通过 Finalizer 的 Runtime 文本冒充交付答案。

## 核验事实

- 实际 OpenAI SDK 使用 `httpx2.AsyncClient`，与 harness 补丁包装的发送类相同；生产 Provider client 设置 `max_retries=0`，hosted tracing 已关闭。
- 共享账本在本次检查时为 **112 started / 112 finished**，编号连续，所有已完成发送返回 200，无悬空编号。**这是实验仍在运行时的快照，绝不是最终请求总数或预算结论**；最终完整账本由主会话核验。
- 开发两臂各 8 条成功、各 21 HTTP；总 Token 分别为 523,488 / 584,931，与报告一致。全部 8 对冻结条件经 `verify_conditions(..., prompt_treatment=True)` 比较通过，只有显式基础 Prompt 前缀被放开，动态后缀和其他条件仍参与比较。
- 开发 final Evidence 固定目标为 11/19 → 8/19。Assistant grounded 判定分别为 pass1/fail5/pending2 与 pass0/fail5/pending3；必要事实分别为 pass17/fail3/pending1 与 pass16/fail5。报告未冒称人工审核或质量提升。
- 当前生产 `prompt.py` 与历史 fixture 均逐字等于 `8def8d7` 的完整源码。历史静态审计仍绑定原实验文本，没有为匹配候选而改写旧产物。
- 只读报告投影得到独立验证 A 12/12 成功、B 11/12 成功，固定 Evidence 为 23/29 → 22/29。两边都生成 12 个合法原生 ReviewPacket；B 的无答案运行保留为 `answer_text=None`、`INVALID_FINAL_OUTPUT`，没有从评审分母删除。
- 公开统计结构来自明确字段投影，不包含聊天正文、source locator、完整 Trace 或凭证。原生 packet 和盲审正文仍属于私有目录。

## 未修复问题与边界

此次范围内没有其他需要报告的已证实缺陷。未把潜在 reply 投影损失或 source-hit cap 的披露问题升级为本次坏答案的已证根因。报告链接、最终 44 次运行完整性、最终 HTTP 总量、独立验证必要事实审核及收尾文档由主会话完成，不能用本次中途快照替代。

## 验证

- Lint：`uv run ruff check src tests scripts/evaluation_quality_experiment.py scripts/evaluation_quality_report.py` 通过；主会话局部修订后再次检查两个脚本及 harness 测试也通过。
- TypeCheck：`uv run mypy src` 通过，128 个源文件。
- Tests：harness 与三个历史 Prompt 测试文件共 **266 passed**；随后包含新报告身份回归的 harness/report 专项 **14 passed**，新文件 Ruff 也通过。本次不把尚未取得的完整仓库结果写为通过。
