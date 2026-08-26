# Reliability Bug Audit

## Audit rule

本审计把“预算不足”“模型输出不符合 Answer contract”“provider 运行失败”和“实验 harness 生命周期错误”分开归因。所有修复都保留显式 Trace/diagnostic；没有用 retry、fallback 或静默吞错把失败改写成成功。

| 现象 | 分类 | 根因 | 本轮处理 | 回归证据 |
|---|---|---|---|---|
| Agent learning dynamic 输出 `limitations` 为 string | BUG（finalization 边界缺少 graceful 路径） | provider 输出形状违反 typed Answer contract，不是 Tool pool 耗尽 | 只在 bounded recovery 中把 string 规范为单条 limitation；答案保留并标记 degraded | `GracefulFinalizationTests.test_string_limitations_are_normalized` |
| GitHub/Skills fixed 的 claim sources 超过 20 | EXPECTED CONTRACT FAILURE / PROVIDER NONDETERMINISM | 模型一次生成超过 `MAX_CLAIM_SOURCES`，与预算错误无关 | 保留 strict failure 归因；不提高全局 contract 上限，不加 prompt 特例 | 历史 Trace `trace-0045abb9ff0f42f3b78800461d4aef19`；strict evidence tests |
| GitHub/Skills fixed 的 Runtime error | PROVIDER NONDETERMINISM | provider/runtime 在某次真实调用失败，未观察到 budget exhaustion | 保留 Runtime terminal failure；不把 provider 错误标为 finalization degraded | 历史 A/B validation；Runtime failure tests |
| 首轮真实 A/B 的 async-close 错误 | TEST HARNESS ISSUE | event loop 内使用同步 close，生命周期调用方式错误 | runner 在 `finally` 中 `await application.aclose()` | archived real runner 与 Application lifecycle tests |
| OpenCode Go 工具回合与 JSON mode 冲突 | BUG（provider compatibility boundary 未隔离） | 真实 provider 不支持 tools + `response_format=json_object` 组合 | 在同一 adapter 只移除工具回合的 JSON mode；最终化回合保留 JSON；compatibility observation 进入 Trace | `test_opencode_go_agent_does_not_combine_tools_with_json_mode` |
| Runtime 始终使用固定 16k，无法获得已验证的大 context | BUG | settings 没有 context metadata，adapter 没把预算传进 projection | 加 verified registry、resolver、dynamic default 和 per-call snapshot | `ToolResultBudgetPolicyTests`、synthetic/archive benchmark |
| 多 Tool call 未共享累计预算 | BUG | 没有 run-local mutable ledger，调用间没有 reserve/settle | 每次 RuntimeContext 新建 policy，先 reserve、按实际 projection settle | `test_dynamic_pool_accounts_actual_projection_not_reserved_ceiling`、multi-call test |
| 非法 projection 结算后 reservation 被提前删除 | BUG | `complete_call()` 先 pop 再校验，失败会泄漏已预留余额 | 校验成功后才消费 reservation，恢复 atomic settlement | `test_invalid_projection_metrics_are_rejected` |
| 局部 citation/source 无效时整条可读答案丢失 | BUG（delivery boundary 过于严格） | strict finalizer 把 local metadata 错误与 trusted provenance failure 混为一类 | 新增 bounded graceful finalization：丢 invalid local metadata/citation，保留 answer，标 degraded | `GracefulFinalizationTests` 全组 |
| 本轮真实 runner 初次出现 36 个 SettingsError | TEST HARNESS ISSUE | variant display label `fixed-16k` 被误传为 typed mode `fixed` | 分离显示标签与 `fixed/dynamic` mode；失败尝试不计入有效 A/B | runner 修复后 preflight；timeboxed retry 输出 |

## Deliberately unchanged

- Runtime/provider failure、empty answer、trusted provenance unavailable、scope violation 和 canonical trust failure 仍是 failed，不会因为“有一段文本”而降级成成功。
- 没有新增二次 LLM repair；OpenCode Go 的既有无工具 JSON compatibility path 仍是同一 provider/runtime 内的一次有界协议修复，不负责修复 Answer contract。
- 未修改 Retrieval candidate hard caps；benchmark 中的 visible token/omission 是 projection 事实，不直接改写质量结论。
