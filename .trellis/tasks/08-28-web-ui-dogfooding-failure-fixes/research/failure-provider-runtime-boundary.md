# F-RUNTIME-02 — 大 Tool Result 后 Provider 空/不完整 final

## 复现

- 场景：真实 Web UI、资源/GitHub 宽泛问题，全部聊天 Scope。
- 失败 Trace：`trace-2e914390d13046c5a13c97f32f843d52`。
- Retrieval：recent 2699/2699 加 lexical 347/347；projection 分别为 1441 和 347，Tool Result 估算约 189248 tokens。
- 两个 tool call 都成功；Runtime 产生 `provider_compatibility` observation，但没有可见 final text；Runtime 当时以 completed+空字符串返回，Host 随后报 `INVALID_FINAL_OUTPUT`。
- 同一问题重跑 `trace-ceead8dc094d45918bc514498db11f22` 只使用 recent projection（约 127882 tokens）并成功：4 claims、1134 正文、19 citations。
- AQ4 成员查询 `trace-2315d30f87b44a1d81307051afabb767` 也在成员查找后泛取大 recent 窗口并进入 Runtime failure，说明不是单个资源名称特判。

## 修复后真实 Web 重测与 Provider 观测

- AQ3 资源/GitHub 重测 Trace：`trace-11cea2531b6c4984b5c4dc2bf29c5456`。Prompt 明确资源库存优先走
  `lexical_search(github.com)` 后，首个且唯一的 retrieval 返回 93/93 条命中，Tool Result 估算 17,070
  tokens，model-visible projection 为 93 条、0 omitted/truncated；最终 synthesis 输入 21,613 tokens，生成
  7 个 claim、1,999 字符、49 个有效 citation，Web UI 按类别展示了具体项目和链接。
- AQ3 的 Provider 观测均为 HTTP 200、stream completed、`finish_reason=stop`；compatibility repair 前后都有
  非空 assistant message（4,181/4,380 字符），没有空 output、传输异常或 Finalizer/renderer 丢正文。旧失败的
  189,248-token 合并 Tool Result 因此被确认是触发 Provider 方差的输入条件，而不是 Web 投影截断。
- AQ4 成员重测 Trace：`trace-48410dcce379492c81dbcd2566524f14`。`find_members` 后的
  `get_recent_messages` 明确带 `sender_user_ids=["qq:uid:u_TEK4cI3Tl3J_aiMxAL4K_A"]`，返回 52/52 条、无
  truncation；model-visible projection 为 52 条、0 omitted，synthesis 输入 15,262 tokens，最终 5 个
  claim、676 字符、36 个有效 citation，Web UI 完成回答。
- `openai_adapter.py` 现在只向 Trace 投影 Provider response shape、HTTP status、request/response 短标识、
  finish reason、stream 完成状态、usage 和 compatibility repair 前后 shape，不保存 response 正文或 hidden
  reasoning；Runtime failure 另外记录稳定的 `exception_type`。这使下一次空/不完整输出可以区分传输、Provider
  output shape、Runtime 与 Finalizer，而不会依赖猜测。

## 归因

这是“工具选择造成的大输入”叠加“Provider-compatible runtime 方差”的独立 Failure，不是 Answer Depth 的 C：

- 失败发生在 final synthesis 可交付 candidate 之前；没有 `answer.finalization.completed` 的正常正文可比较。
- 同问题一次成功、一次失败；成功运行的输入和 Tool Result 更小，说明 Provider 对大合并输入的行为不稳定，但现有 Trace 没有安全的 finish reason 字段，不能臆测具体服务端错误。
- 把 Tool Result 预算强行降到 128k 的进程级实验仍在第二个工具调用后失败，并且会把 recent projection 从约 12.8 万降到约 3.2 万 tokens，损失大量证据，因此没有把它作为修复。
- AQ3 修复没有降低所有 Tool Result 的全局上限，而是修正了资源库存的检索优先级：URL/资源清单先走有界的
  lexical path，避免为查找链接先把宽泛 recent 窗口放入 synthesis。当前 Trace 证明 evidence 仍完整返回，且
  Provider candidate、Host finalization 与 DOM 均成功。
- AQ4 的根因不是 canonical repository 不支持成员过滤，而是 Agent-facing `get_recent_messages` schema
  原先没有暴露该已有能力，模型只能在 `find_members` 后泛取全体 recent。修复把 canonical sender filter 贯穿
  Input、cursor、Structured query、SDK tool 和 Trace，同时保持 trusted session/time scope。
- 不能让 finalizer 伪造缺失 claim、静默把空 output 当成功、或通过全局压缩证据掩盖 Provider 失败。

## 最小改动

真实失败证明 Runtime 原先允许 `SDK final output == ""` 以 completed 结果流入 Finalizer，导致终态语义混乱。`openai_adapter.py` 现在在 Runtime 层显式返回：

```text
INVALID_FINAL_OUTPUT / empty_final_output
```

这只改善错误透明度，不伪造 Provider 正文；资源查询的实际修复是避免已证实的大合并输入路径，成员查询的实际修复
是暴露并使用已有 canonical sender filter。没有新增无依据 retry、fallback 或降级。

## 后续边界

资源空 final、坏 candidate 和成员大窗口 Runtime failure 的原始 Trace 仍作为回归基线保留；修复后 Trace 已补齐安全的
provider finish/response-shape 观测，并证明当前资源/成员路径不再复现。仍不能凭一次短回答改 temperature 或
max tokens。

## 回归测试

- `test_empty_sdk_final_output_is_an_explicit_runtime_failure`
- `test_provider_response_shape_keeps_empty_text_and_output_kinds`
- `test_provider_stream_observation_keeps_finish_status_and_request_id`
- `test_runtime_event_mapper_drops_delta_and_keeps_model_context` 同时验证 Provider observation 进入 Trace
- 真实 Web：资源查询成功/失败两条 Trace 和进程级 context 实验均已记录。
