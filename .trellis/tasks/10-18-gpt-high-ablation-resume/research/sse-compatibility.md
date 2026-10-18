# SSE metadata 兼容性核对

## 实测根因
原 Trace 只保留 SDK 字段错误，不含实际未知事件体。原账本的第2个真实HTTP以现有Application/Screening入口复现，诊断response hook在内存读完整SSE，只保存metadata、事件形状和终态usage，不保存私有reasoning/output。

实际事件固定顶层 type=response.metadata、response_id、sequence_number、metadata（object）；内容是 openai_chatgpt_moderation_metadata，其中prompt保护结果is_blocked=false，generation/tool_call/tool_response为空对象。该事件位于function arguments delta和done之间，后续真实response.completed/model=gpt-6.1-sol/usage存在。因此原异常确实在合法旁路事件处提前中断，且破坏工具参数done/终态送达；不能仅跳过所有未知事件。

## 上游核对
- [公开Responses参考](https://developers.openai.com/api/reference/python/resources/responses)：当前获取页面没有response.metadata。
- [官方Codex SSE实现](https://github.com/openai/codex/blob/8c076942cb70fba8e5c4732c23f1faabc4aed484/codex-rs/codex-api/src/sse/responses.rs)：显式读取response.metadata中的moderation/verification/headers，作为旁路信息处理；仍独立等response.completed。
- 本地openai-agents0.22.0要求openai>=3,<4；安装openai3.5.0的ResponseStreamEvent无metadata。远端最新release3.35.1及main的同文件也未包含该类型；盲升依赖不能解决根因。
- SDK的工具/Usage/Reasoning接口已验证，选择在自有ChatGPTResponsesModel仅增加该精确事件的严格typed envelope。无需依赖升级。

## 最小修复
新增strict/extra=forbid的metadata类型，必需response_id非空字符串、sequence_number非负严格int、metadata JSON object；验证后投影响应身份/序号/metadata键到安全transport observation。metadata不进入assistant内容/replay/Usage，不视作完成，不解释审核结果为成功。未知事件/错误形状继续MALFORMED_STREAM，完整终态/工具/Reasoning仍用SDK原类型。metadata响应身份变化或与completed不符明确错误。

旧最小metadata测试没有response_id/metadata，仍必须失败，诊断从未知union tag变为缺必需字段；这不是放宽失败断言。新测试先2红5绿，修复后补合法/非法/未知/断流、真实SDK两轮/隐藏replay/usage及后续失败/错误关联验证。

## 网络边界
初始直接网络请求出现EOF/SSL失败；只读系统proxy配置后使用现有127.0.0.1:7892代理的进程环境完成官方来源读取与第2次诊断，没有修改用户网络或.env设置。
