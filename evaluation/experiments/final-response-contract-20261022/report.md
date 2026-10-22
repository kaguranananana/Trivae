# 最终回答格式资格修复（2026-10-22）

**Runtime现在把Finalizer已验证的no_result资格告知下一次模型输入。** 原错误输出仍被拒绝；固定原失败工具决策、SQL和时间窗后，一次真实Plan / gpt-6.1-sol / medium最终综合改用普通claims，正确回答目标日为空并通过三条统计来源引用校验。

## 原因与最小改动

历史zero-empty-2已经取得目标UTC日完整空检索，但此前又读取了日期分组SQL行。它最终选择no_result并把邻近日期统计写入summary，违反专用空结果格式。现有Finalizer会拒绝这种组合，不能靠放宽校验来提高交付率。

原Runtime只有通用格式说明，没有把当前工具历史在Host中实际计算出的资格明确传给模型。修复仅在动态instructions中复用`has_verified_zero_result_evidence(tuple(context.tool_results))`，工具返回后重新计算allowed/unavailable；不可用时要求可引用事实采用普通claims并保留限制。

不改Finalizer、不改检索或预算、不替模型修改输出、不新增重试/Judge。模型仍可能忽略提示，最终校验仍是权威；本轮没有证明所有空结果请求都会成功。

工作提交6ba2596；回放HTTP身份修正提交4a9dde8。

## 确定性验证

- 真实SQLite→Capability→SDK四种工具历史：完整空窗、空窗加数值COUNT、空窗加日期分组、单独COUNT。资格信息缺失的4项回归先失败，修复后全部通过；错误格式仍由原Finalizer拒绝。
- 相关回归36 passed；完整pytest **1,251 passed / 1 skipped（30.51s）**，Ruff src/tests/scripts及mypy src（129文件）通过。
- 后增Responses调用身份回归后，该文件5 passed。未把单项追加测试描述为重新运行的完整1,252项。
- 原10-20失败答案和原工具决策零HTTP重放：Runtime completed，Query/Finalizer failed，保留`zero-result final answer lacks verified complete-and-empty retrieval evidence`。新提示没有使错误输出被接受。

## 真实最终综合验证

复用811,892条原快照的独立克隆，保存原问题、原SQL和绝对时间窗；固定历史三个工具轮（get_schema、两次execute_sql、get_recent_messages），ScriptedModel只回放工具决策，最后一轮交给真实Plan Medium，且不再暴露工具。不是自主检索或整题质量A/B。

正式有效综合使用独立目录live-responses-identity，一次HTTP、一次response.completed、Query completed、finalization valid；真实输入10,674/输出214/总10,888Token，其中reasoning33。

模型最终返回claims，说明UTC [2025-08-23T00:00:00.000Z, 2025-08-24T00:00:00.000Z)未发现发言，无当天主题可总结，并限制为当前收录记录。完整空窗事实与覆盖该日的完整跨日统计一致，引用的三个日期组分别为8月21日33条、22日1条、24日1条；未把这些数值放入无引用的no_result summary。三条引用通过、无丢弃或降级。

## 实验入口失败与计数

- 首次offline脚本漏Plan的trivae namespace，Runtime在工具执行前失败；保留工件，不计为有效历史重放。修正后另存offline-namespace，才完成有效零HTTP重放。
- 首次live请求因脚本的历史函数调用项id不以fc开头而HTTP400，在模型生成前被拒绝。定位为回放接口身份错误，修正namespace/item_id/call_id并补回归后，另建一次独立验证；旧失败未覆盖或从分母中删除。
- 本项总真实发送尝试2次：1次HTTP400（Usage不可用）、1次完成（10,888Token已知）；不能报告为两次都成功，也不能把HTTP400的未知Usage计为0。每个验证unit限一次真实综合，SDK无自动重试。
- 没有为了让产品测试通过增加样例特判。修正的是实验回放项满足真实Responses接口的通用身份约束，产品仍使用SDK原公开namespace。

完整正文、最终实际模型输入、SQL结果、Trace、独立账本、脚本冻结及上述失败工件保留ignored `data/evaluation/final-response-contract-20261022/`。公开复现入口：`validate_final_response_contract.py`。
