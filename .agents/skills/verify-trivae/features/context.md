# 消息上下文补读

当检索预览无法回答问题时，用户可以继续询问长消息原文或原消息的回复。Agent 用当前查询返回的来源定位后续读取。

## Sub-features

- `read-tail` 读取被搜索预览截去的长消息尾部。
- `read-reply` 补读相距 143 条消息的直接回复。
- `read-boundaries` 保留群聊、时间、转发容器和容量边界。
- `read-query` 从查询走到补读、最终引用和 Trace。

## How to get to it (user POV)

在 Web 或 `trivae chat` 询问一条消息的原文或直接回复。Agent 使用 `get_message_context`，例如请求 `source_id="m1-1"` 并设置 `include_replies=true`。

## Driving it with pytest

前提是已完成 Skill 的 Launch。fixture 包含长消息、远距离回复、跨群重复 ID 和多个转发容器。

- 运行 `tests/test_context_source_contract.py`，检查搜索短预览缺少的“三个月”出现在补读全文中，输出仍在投影预算内，来源回到 `qq:100:long`。
- 运行 `tests/test_reply_context.py`，检查显式补读得到原消息与“实际用过，值得推荐”，回复链接指回原消息。同一文件核对默认局部读取、直接回复、半开时间窗、转发容器和容量截断。
- 核对其中的 `test_sdk_loop_source_handle_reply_citation_and_trace`。固定脚本模型调用 `lexical_search`，用 `m1-1` 调用 `get_message_context`，答案引用解析为 `qq:100:reply`，持久化 Trace 记录 `include_replies=true`。

## Gotchas

- `source_id` 在单次查询中有效。Canonical ID 如 `qq:100:reply` 应走 `message_id` 参数。
- 脚本模型固定工具调用顺序，实际模型是否主动选择补读需要另测。
