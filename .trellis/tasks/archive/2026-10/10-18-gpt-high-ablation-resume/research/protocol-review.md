# SSE 协议修复独立复核

复核范围：提交 `b669bcc` 的 `chatgpt_responses.py`、`test_chatgpt_responses.py`，以及当前任务合同、`sse-compatibility.md` 和 ignored 诊断文件 `metadata-capture.json`。本次仅写本报告，不改代码、Prompt、凭据、GT、预算或历史产物；未向 Trivae 被测 Provider 额外发送 Judge 或实验请求；Codex Agent 自身复核属于模型审查。

## Findings (fixed)

无。本轮未发现需要修改实现的可复现问题，因此保留实验所固定的代码版本。

## Findings (not fixed)

- 文件：`chatgpt-plan-guidelines.md`。
- 问题：`GPT High 与 Prompt Screening` 开头仍称当前真实请求在 `response.metadata` 遇到 `MALFORMED_STREAM`；Validation & Error Matrix 仍要求该事件失败；Tests Required 仍使用“未知 metadata 明确失败”的旧表述。与现已实测并显式建模的已知事件合同不一致。
- 建议：主任务收尾时同步为已知 `response.metadata` 的严格 envelope 验证，保留缺字段／错误类型／额外顶层字段／未知事件拒绝，并说明 metadata 不代表终态、不得进入回答／隐藏 replay／Usage。保留原失败历史并链接本轮验证，避免把旧阻塞描述覆盖成历史请求成功。
- 未直接修改原因：本轮明确仅拥有研究报告写权限，规范由主任务统一更新。

## 实现核对

- 真实诊断的顶层字段恰为 `type`、`response_id`、`sequence_number`、`metadata`；与新增 `strict=True / extra=forbid` 模型一致。字段类型分别为固定字符串、非空字符串、非负严格整数、JSON 对象。原来缺字段的最小反例仍失败，错误类型从未知 union tag 变为明确缺字段，属于合同修正。
- 新分支只消费已验证的该精确事件名；其它类型仍交由原 SDK 判别联合，未知类型继续 `MALFORMED_STREAM`。未升级依赖或替换 SDK 工具处理逻辑。本地版本为 `openai-agents 0.22.0`、`openai 3.5.0`、`pydantic 2.13.4`。
- metadata 不作为成功信号。断流仍 `STREAM_INTERRUPTED`，后续 failed/incomplete 仍原错误分类，completed 仍必须为 completed 状态，metadata 与完成 Response 身份不一致明确拒绝。
- 函数参数 done 的 name 仍只来自本次已验证 added item 的 item_id 关联；metadata 分支没有修改 arguments、call_id、命名空间或 Runner dispatch。实际 SDK 两轮回归保留工具结果与 encrypted reasoning 的下一轮重放，并从真实 typed terminal 汇总 Usage。
- 观测仅新增 response ID、序号与 metadata 顶层键；实际审核内容不进入观测。metadata 不加入模型输入或输出，不重写 Usage，不修改 reasoning 文本过滤或错误脱敏路径。
- 原 `async with`、`aclosing`、取消处理与 finally 观测路径保留。另用真实捕获 metadata 的本地流验证：消费 metadata 后等待网络时取消，仍抛出 `CancelledError`、关闭 HTTP 流、报告 `REQUEST_CANCELLED` 与 `stream_completed=False`。

## Verification

- Lint：通过，`uv run ruff check src tests`。
- TypeCheck：通过，`uv run mypy src`，128 个源文件。
- Tests：通过，`test_chatgpt_responses.py`、`test_chatgpt_query.py`、`test_completion_transport.py`、`test_prompt_screening.py`，共 68 passed，2.71 秒。
- 补充本地验证：直接加载 ignored 真实 metadata 对象，在 added → metadata → 缺 name 的 arguments.done → completed 流中验证 done name 恢复及完成；在 metadata 后阻塞并取消，验证关闭与安全观测。均通过，未写入代码或额外测试文件。
- 本次未重新运行全量测试，也未新增 Trivae 被测 Provider 请求；主任务已有与后续端到端／全量结果由主任务合并报告。Mock 与本地重放仅证明协议适配，不证明答案质量。
