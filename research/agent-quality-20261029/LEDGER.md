# 真实模型请求账本（Agent Quality Research 2026-10-29）

## 登记规则

1. **每次真实 DeepSeek Agent HTTP 请求（含失败请求）都必须在此登记一行**——包括成功、超时、4xx/5xx、解析失败等一切发出过的请求；失败请求同样消耗配额，不得遗漏。
2. **每次 ChatGPT OAuth Judge 评审都必须在此登记一行**——无论评审结论如何。
3. 每登记一行，必须**同步扣减 `budget.json`** 中对应的剩余额度（`deepseekRemaining` / `judgeRemaining`），保证账本与预算文件一致。先记账、再扣减，两步在同一次编辑会话内完成。
4. Token 数与已知成本如可得则填写；不可得则写 `n/a`，不得编造数字。
5. `结果/备注` 列记录该请求的 outcome（成功 / HTTP 状态码 / 超时等）与一句关键备注（如对应哪个实验问题 ID）。
6. 本账本与研究状态见 `STATE.md` 的「预算状态」小节；预算耗尽即停止一切真实模型请求。

## 表头

| 时间 | 轮次 | 用途 | 模型 | HTTP 请求数 | Token（如可得） | 已知成本 | 结果/备注 |
| ---- | ---- | ---- | ---- | ----------- | --------------- | -------- | --------- |

## 登记记录

（暂无。今晚第一次真实请求发生后，从此处开始追加行。）

### 2026-10-30 计数器接线修复前的追记（非预扣；如实保留失误）

OpenAI SDK使用httpx2，初版只计httpx；发现后立即SIGINT两侧，保留工作库及partial Trace。按三个完整/部分Trace的Router Usage与已返回工具调用逐请求重建9次；两个未完流也计入，0重试，无只开始未见响应的未知请求。证据request-count-recovery.json及interruption-traces。

| 2026-10-30T10:23:14+08:00 | Codex R2 | recovered-agent-001/baseline/router | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 128, "input_tokens": 352, "output_tokens": 337, "reasoning_tokens": 266, "total_tokens": 689} | n/a | completed; trace-abd175fb11aa4c5a9333472c2e9facd9 sequence 5 |
| 2026-10-30T10:23:15+08:00 | Codex R2 | recovered-agent-002/baseline/agent_stream | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 10368, "input_tokens": 10520, "output_tokens": 232, "requests": 1, "total_tokens": 10752} | n/a | completed; trace-abd175fb11aa4c5a9333472c2e9facd9 sequence 7 |
| 2026-10-30T10:24:07+08:00 | Codex R2 | recovered-agent-003/baseline/agent_stream | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 5632, "input_tokens": 38858, "output_tokens": 2367, "requests": 1, "total_tokens": 41225} | n/a | completed; trace-abd175fb11aa4c5a9333472c2e9facd9 sequence 24 |
| 2026-10-30T10:24:24+08:00 | Codex R2 | recovered-agent-004/baseline/router | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 128, "input_tokens": 352, "output_tokens": 218, "reasoning_tokens": 156, "total_tokens": 570} | n/a | completed; trace-fc49426027274db6be32efaadeb7d4ed sequence 5 |
| 2026-10-30T10:24:24+08:00 | Codex R2 | recovered-agent-005/baseline/agent_stream | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 10368, "input_tokens": 10520, "output_tokens": 543, "requests": 1, "total_tokens": 11063} | n/a | completed; trace-fc49426027274db6be32efaadeb7d4ed sequence 7 |
| 2026-10-30T10:25:13+08:00 | Codex R2 | recovered-agent-006/baseline/agent_stream | DeepSeek deepseek-flash | 1 | unknown（partial stream） | n/a | interrupted_after_streamed_tool_calls; trace-fc49426027274db6be32efaadeb7d4ed sequence 23 |
| 2026-10-30T10:23:15+08:00 | Codex R2 | recovered-agent-007/candidate/router | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 128, "input_tokens": 352, "output_tokens": 359, "reasoning_tokens": 290, "total_tokens": 711} | n/a | completed; trace-46742347d7ed4cc78cbd45472cf8c0aa sequence 5 |
| 2026-10-30T10:23:15+08:00 | Codex R2 | recovered-agent-008/candidate/agent_stream | DeepSeek deepseek-flash | 1 | {"cached_input_tokens": 10368, "input_tokens": 10520, "output_tokens": 255, "requests": 1, "total_tokens": 10775} | n/a | completed; trace-46742347d7ed4cc78cbd45472cf8c0aa sequence 7 |
| 2026-10-30T10:24:08+08:00 | Codex R2 | recovered-agent-009/candidate/agent_stream | DeepSeek deepseek-flash | 1 | unknown（partial stream） | n/a | interrupted_after_streamed_tool_calls; trace-46742347d7ed4cc78cbd45472cf8c0aa sequence 23 |
