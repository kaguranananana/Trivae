# 嵌套 SSE 额度错误增量审查

本记录由独立 Codex Agent 按 trellis-check 直接复核，非人工裁决。未向 Trivae 被测 Provider 发送额外 Judge 或实验请求，未改源码、Prompt、Case/GT、预算账本或原运行记录，未提交。

## Findings（fixed）

无。没有发现需要机械自修的源码、类型或测试问题。

## Findings（not fixed）

- 规范同步：本次检查时 `chatgpt-plan-guidelines.md` 尚未明确列出新证实的嵌套 `error` envelope 严格合同、叶子代码分类及 Runtime/Router/Planner 三入口的单请求停止要求。主 Agent 同时维护该文件，已通知其统一补充，避免并发编辑。
- 任务状态文案：检查时 `implement.md` 仍是历史52/120及8 Case状态，应由主 Agent 汇总当前实验、用户明确授权的预算变更与失败边界，不能把历史状态当作最新结论。

以上属于文档事实同步，未发现阻断本次局部源码修复的实现问题。

## 源码与真实 Failure Case 对照

只读旧书籍 A 失败工件：真实一次 HTTP 200，合法 metadata 后为外层 `type=error`、`sequence_number=3`，内层包含 `type/code/message/param`，真实叶子代码为 `subscription_sharing_usage_limit_exceeded`，param 为 null。旧 code=error、未完成流、无 Usage/答案的事实保持原件，没有重写为已修复结果。

新增两个私有 Pydantic 类型与该真实形状一致：严格类型、字段必需、非负整数序号、非空叶子字符串、额外字段拒绝。只在 `type=error` 且显式含 `error` 时进入此合同；先验证再提取叶子，没有模糊识别额度词、丢弃未知事件或把未知叶子代码重命名为 quota。

合法叶子进入原 `_error` 与 `ChatGPTResponsesError`，原 `stops_inference` 额度集合得到真实代码；Router/Planner 原有立即传播分支因此恢复工作。Application 三阶段新回归均断言只发一次 HTTP、原 ledger 只消费一次；Runtime 无工具、最终答案和 AnswerArtifact，Router/Planner 不降级续发 Runtime。原 flat error、response.failed/incomplete/error 路径未被更改。

畸形嵌套叶子、缺 code、布尔序号或额外输出均在原 ValidationError 路径成为 MALFORMED_STREAM；诊断不包含未经验证 body。未知 SSE tag 仍进入 SDK 判别联合拒绝。metadata 仍只记录安全身份及键，不承担成功或 Usage；成功必须 completed 且 status=completed，并维持 metadata 响应身份检查。工具循环、Reasoning replay、Usage、取消、断流等原回归均通过。新代码不改变 OAuth、TLS、请求重试、预算、工具、终态或质量标准。

错误消息/body 仍通过认证脱敏后进入异常及 Trace；新回归包含注入凭据字符串后的脱敏断言。没有保存原响应中模型 output、encrypted reasoning 或用户正文的新路径。

## Verification

- package scope：`get_context.py --mode packages` 确认为单仓，backend/project；已读取任务 PRD/design/implement、check.jsonl 及受影响规范。
- Lint：`uv run --all-extras ruff check src tests`，通过。
- TypeCheck：`uv run --all-extras mypy src`，128源码文件通过。
- Tests：`uv run --all-extras pytest -q tests/test_chatgpt_responses.py tests/test_chatgpt_query.py tests/test_prompt_screening.py tests/test_completion_transport.py`，77 passed，1.63s。
- `git diff --check`：通过。
- 全量 pytest 及修复后真实额度恢复验证由主 Agent 执行；本记录不把 Mock 通过称为真实额度恢复、真实书籍答案完成或 A/B/C 质量门禁通过。旧失败已隔数小时，不能据该历史 quota 响应推断当前额度状态。

## 边界与发布判断

该修复解决 Provider envelope 解析和既有停止策略失效，未增加恢复分支。用户新预算授权仅改变本地实验上限，不能解除外部订阅额度。真实恢复请求若仍 quota，应正确停止并保留失败，不能继续循环试探或借本次修复替换生产 Prompt。既定人工 blind ReviewPolicy 与此前独立质量/输出合同失败仍须如实保留。
