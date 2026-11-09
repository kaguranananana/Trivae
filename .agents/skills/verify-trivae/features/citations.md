# 引用校验

用户在回答中看到的消息引用应当可以回溯到该次查询检索到、且位于授权范围内的原始消息。

## Sub-features

- `citation-bind` 验证回答中的来源绑定到真实消息。
- `citation-reject` 拒绝伪造、跨运行或超范围引用。
- `citation-degrade` 无效引用触发诊断，可用引用仍可保留。

## How to get to it (user POV)

在 Web 或 `trivae chat` 提问并查看回答附带的来源。返回的 Trace ID 可通过 `trivae trace show <trace_id> --database <db>` 检查。

## Driving it with pytest

前提是已完成 Skill 的 Launch。使用既有 ToolResult 和合成消息 fixture。

- 正向绑定复用 `tests/test_reply_context.py::test_sdk_loop_source_handle_reply_citation_and_trace`，核对回答来源是 `qq:100:reply`，并从 SQLite 回读补读调用的 Trace。
- 运行 `tests/test_evidence.py` 中 `ProvenanceValidationTests` 的 `test_fabricated_run_tool_result_item_and_old_run_fail` 和 `test_source_outside_execution_scope_fails_even_if_context_was_returned`。逐项检查伪造身份与范围错误的稳定错误码。
- 运行同文件 `GracefulFinalizationTests` 的 `test_one_invalid_citation_is_dropped_while_valid_citation_survives` 和 `test_all_invalid_citations_keep_answer_but_do_not_look_grounded`。两种情况均应披露 `degraded`；部分失效保留一条有效绑定，全部失效没有来源绑定。

## Gotchas

- 来源绑定验证身份、范围和结构。原文是否支持自然语言结论需要独立审阅。
- 默认旅程从测试内回读 Trace，验证完成后仅保留断言报告，临时 Trace 数据库随 fixture 清理。
