# P11 semantic diff

Parent=P10；production SYSTEM_PROMPT原文不动。

- Removed：`Keep
context_before/context_after non-negative and bounded. `（60字符）。
- Moved：Base候选→SDK strict/ge=0 + 原typed input共享总量上界 + 原工具description的bounded/message-count语义。
- Reworded：无；Added：两个context字段strict/ge，14项契约测试与中文职责注释。
- Unchanged high-risk policy：get_message_context全部选窗description及默认8/8、Base讨论20/40示例、reply-gap优先、partial negative、scope、stop、Temporal/Routing全文逐字不动。不是改窗口选择策略。

修改前11失败/3通过：SDK转换原类型且Schema缺minimum，原Host共享总量边界正确。修复后8种非法原输入在registry前拒绝；默认8/8与0/20、0/40保持；Host对before+anchor+after超界拒绝且零registry，合法总量边界保持。不添加单侧maximum，也不降低讨论展开可用范围。

static=204 passed in1.90s；Ruff/mypy116通过；8项真实discussion/negative fixture通过。Provider=0、tokens=0、cost=0。累计候选19,903字符，仅contract/L0接受，生产仍原文。
