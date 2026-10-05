# 技术设计

最小差距是命中锚点后的调查深度与证据事实使用；现有正式上下文工具能找回漏掉的推荐。

修改 `prompt.py` 的调查与归纳指导，以及 `openai_tools.py` 的 get_message_context 描述和 before/after 参数单位。讨论提问优先深挖已知 source_id；相邻消息不自动视为回复。纯 GitHub 清单仍走 lexical URL 召回，学习讨论不由 github.com 规则抢占。

`openai_adapter.py` 的动态 instructions 读取现有 _RunState.tool_rounds 与 max_tool_rounds，提供已耗/剩余轮数；现有 hooks 继续负责消费和 finalizing，不新增计数器或隐藏工具轮。

`evidence.py` 在统一 _model_message_projection 派生 timestamp_utc，复用 format_timestamp_utc，保留 canonical timestamp；日期与 author/source 在裁剪中一起保留。其他 canonical schema 和 finalizer 不变。

实验将 baseline 代码保存在 ignored 目录，候选使用当前代码，输出与隔离 conversation/trace 归实验目录；共享 canonical 数据只读。固定原 Trace 问题、群和上界，强制 Standard 保持无 Planner 差异。先验证工具，再做真实配对；SDK fake 只证明 contract。

更大窗口可能带入闲聊；由模型按线索选取，20/40 仅指导示例。剩余轮数提示和可读时间属于事实增强，不能保证整体质量。若实际 provider 失败显式记录，不换 provider 或加 retry。
