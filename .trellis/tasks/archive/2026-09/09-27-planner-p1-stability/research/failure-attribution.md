# P1 completion failure attribution（修改 prompt 前）

## Identity / sources

- 当前起点 `b34cfd2`，祖先为 `68286d5`（P1 实现）和 `12f2f75`（P0 固定源码）。旧 task：`.trellis/tasks/archive/2026-09/09-27-planner-quality-calibration/`。当前分支从旧 P1 HEAD 新建。
- 五组完整 observation、原始 P1/P0 prompt、request、usage、latency、raw response、parse stage、Plan 和 query 均在 `failure-pairs.json`。该文件只是旧 `experiment/runs.jsonl` 的确定性筛选与同 Case/repeat 拼接，未重新调用 Provider。
- Planner completion：DeepSeek `deepseek-flash`，`reasoning_effort=low`，JSON mode，`max_tokens=2048`，system 为固定短句、Planner prompt 为 user message；没有 Tool Loop。正常请求的 `temperature=0` 在该模型 thinking mode 下按官方文档无效，因此重复结果不能视为 deterministic。

## 五次实际失败与配对 P0

| Case / type | repeat | P1 input / output | P1 Provider latency | P1 raw content | P0 same repeat | P0 output |
| --- | ---: | ---: | ---: | --- | --- | ---: |
| `dev-zero-empty-3` / verified zero | 2 | 1249 / 2048 | 9939 ms | 空 | stop，有效 4 Step | 1593 |
| `dev-temporal-30d` / temporal window | 2 | 1236 / 2048 | 10769 ms | 空 | stop，有效 3 Step | 1018 |
| `dev-cite-archify` / direct lookup | 2 | 1243 / 2048 | 9221 ms | 空 | stop，有效 4 Step | 1482 |
| `dev-cite-archify` / direct lookup | 3 | 1243 / 2048 | 10423 ms | 空 | stop，有效 3 Step | 1135 |
| `pu-rank-utc-session` / ranking | 3 | 1254 / 2048 | 9859 ms | 295 字符，第二 Step 中间截断 JSON | length，无有效 Plan | 2048 |

五条 `finish_reason=length`、`parse_stage=provider_response`、`failure_detail_code=provider_length`，不是 JSON parser 首次拒绝。前四条可见正文长度为零，因而“Plan steps/evidence/success criteria 写太长才截断”不能解释其直接形态。第五条有两步 SQL 计划的部分 JSON，不足以判断完整输出最终有几步。P0 同轮前四条有可见完整 JSON；排名两路都截断，说明 2048 ceiling 连 P0 也有随机风险。

旧实验有效 Plan 的输出 token：P0 575–1845（另有若干接近 ceiling），P1 505–2032；可见正文长度 P1 326–1045 字符。P1 有效 Plan 平均 2.16 Step，少于 P0 的 3.71，不支持“P1 主要因 Step 数膨胀失败”。旧 adapter 没保存 `completion_tokens_details.reasoning_tokens`，因此不能从 token 总数精确分离思考与最终 JSON。

## Prompt composition（代表性 dependent Case）

P1 exact prompt 为 5619 字符、Provider 报 `input_tokens=1276`；以下为**字符占比代理**，不是精确 tokenizer 分段。其它 Case prompt 总长 5543–5619 字符、input 约 1236–1276 token，结构相同。P0 约 1490–1566 字符、每次约 424–464 input token。

| Logical section | chars | Approx share |
| --- | ---: | ---: |
| core JSON/schema/soft-plan contract | 804 | 14.3% |
| generic value / entity / relation / tool discipline | 1195 | 21.3% |
| zero-result rule | 299 | 5.3% |
| capability summaries（含字段键/序列化） | 2858 | 50.9% |
| locale/query/history/allowlist/snapshot | 463 | 8.2% |

Summary 内 `purpose` 取 Capability metadata，`planning_guidance` 来自 Planner mapping；原样暴露 7 个 allowlist Tool，未泄漏未开放 Tool。重复证据：semantic purpose 已写“wording differs / lexical exact terms”，guidance 再写 conceptual recall 与不机械双检索；context purpose 已写“known message_id / local context insufficient”，guidance 再写 direct-hit/context；global prompt 又重复 entity anchor、relation、近期浏览、schema/SQL 止步。`find_members` purpose 对 Planner 暴露成员匹配字段细节，`execute_sql` purpose 含 Runtime scope/LIMIT，`get_recent_messages` purpose 含 `sender_user_ids`；这些 canonical 内容有 Registry 用途，但 Planner 选择不需要再次扩展为完整 Tool 文档。

所有八条 Case 均传相同七个 availability 名称；现有过滤只按 QueryContext allowlist，不是按 query 相关性。进一步 deterministic query projection 可能改变 availability 的模型理解，故本轮不做第二 Tool classifier。history 为 `<none>`，snapshot compact 仅 168 字符；它们不是本套实验的主要 prompt 开销。

## Hypotheses / limitations

- **确认事实**：2048 是生成 token 上限，五次 P1 failure 全部用尽；其中四次尚未输出可见 JSON。输入增长与 failure 相关，但旧实验无法证明因果。
- **支持的假设**：thinking mode 的隐藏推理消耗上限。官方 DeepSeek 文档说明 thinking 默认开启、会在可见 `content` 前产生 `reasoning_content`，且 usage 可返回 `completion_tokens_details.reasoning_tokens`。旧运行没有该字段；新实验应投影数值以检验。[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)；[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。
- **仍未确定**：更多 summary、重复规则或特定任务难度是否增加推理 token；Provider cache/时间漂移与随机性影响；2048 对所有合理 Plan 是否偏低。只有交错重复实验可缩小这些不确定性。
- **暂排除为主要模式**：可见 JSON 中 Step 数暴涨、单项 `goal` / `evidence_needed` / `success_criteria` 过长。四条空内容不支持这些解释，第五条部分输出也没有足够证据。

## Change boundary before code

最小缺口在 Planner 提示信息重复与 completion 诊断缺失。拟修改 `planner.py`（压缩通用规则/summary）、`openai_adapter.py`（只投影实际返回的 reasoning token 数）、Planner-only runner（固定三版本与完整实验 artifact）和相关 contract tests。保持 completion 请求、2048、schema、Router、Runtime Tool Loop、Retrieval、Evidence 与 Holdout 不变。若压缩没有带来可靠性改善，记录 negative result，不添加重试或扩架构。
