# F-RUNTIME-02 — 大 Tool Result 后 Provider 空/不完整 final

## 复现

- 场景：真实 Web UI、资源/GitHub 宽泛问题，全部聊天 Scope。
- 失败 Trace：`trace-2e914390d13046c5a13c97f32f843d52`。
- Retrieval：recent 2699/2699 加 lexical 347/347；projection 分别为 1441 和 347，Tool Result 估算约 189248 tokens。
- 两个 tool call 都成功；Runtime 产生 `provider_compatibility` observation，但没有可见 final text；Runtime 当时以 completed+空字符串返回，Host 随后报 `INVALID_FINAL_OUTPUT`。
- 同一问题重跑 `trace-ceead8dc094d45918bc514498db11f22` 只使用 recent projection（约 127882 tokens）并成功：4 claims、1134 正文、19 citations。
- AQ4 成员查询 `trace-2315d30f87b44a1d81307051afabb767` 也在成员查找后泛取大 recent 窗口并进入 Runtime failure，说明不是单个资源名称特判。

## 归因

这是独立的 G/Provider-compatible runtime 边界，不是 Answer Depth 的 C：

- 失败发生在 final synthesis 可交付 candidate 之前；没有 `answer.finalization.completed` 的正常正文可比较。
- 同问题一次成功、一次失败；成功运行的输入和 Tool Result 更小，说明 Provider 对大合并输入的行为不稳定，但现有 Trace 没有安全的 finish reason 字段，不能臆测具体服务端错误。
- 把 Tool Result 预算强行降到 128k 的进程级实验仍在第二个工具调用后失败，并且会把 recent projection 从约 12.8 万降到约 3.2 万 tokens，损失大量证据，因此没有把它作为修复。
- 不能让 finalizer 伪造缺失 claim、静默把空 output 当成功、或通过全局压缩证据掩盖 Provider 失败。

## 最小改动

真实失败证明 Runtime 原先允许 `SDK final output == ""` 以 completed 结果流入 Finalizer，导致终态语义混乱。`openai_adapter.py` 现在在 Runtime 层显式返回：

```text
INVALID_FINAL_OUTPUT / empty_final_output
```

这只改善错误透明度，不声称已经修复 Provider 的空输出本身；没有新增无依据 retry、fallback 或降级。

## 后续边界

资源空 final、坏 candidate 和成员大窗口 Runtime failure 仍作为 Provider/工具选择观察项保留。下一步若继续处理，应先补齐安全的 provider finish/response-shape Trace，再决定是修正已验证的模型能力 metadata、工具调用策略还是 Provider 配置；不能凭一次短回答改 temperature 或 max tokens。

## 回归测试

- `test_empty_sdk_final_output_is_an_explicit_runtime_failure`
- 真实 Web：资源查询成功/失败两条 Trace 和进程级 context 实验均已记录。
