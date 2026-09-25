# Planner zero-result 回归：`dev-zero-empty-3@v2`

## 真实 Failure Case

冻结执行 commit `f94fffb`、同一 Snapshot 与 Scope 下，主实验和两次 targeted repeat 都是 Standard valid + verified-zero、Planned `INVALID_FINAL_OUTPUT`：两路分别为 3/3 与 0/3。历史 raw/Evaluation/Trace 位于被 Git 忽略的 `data/evaluation/planner-utility/2026-09-25/final/`，版本化索引见 `evaluation/regressions/planner-zero-result-v1.json`。这不是 Planner Provider 失败：三次 plan 均成功。

## 首次偏离与逐层归因

Query/GT 是 `2025-08-26` UTC 全天无消息。Standard 首个且唯一 Tool 是 `get_recent_messages`，返回 canonical store 覆盖 `complete`、`total_hits=0`、`returned_messages=0`、未截断；随后模型输出 `kind=no_result`，Host 成功提交。Planned 多了一次 SoftPlanner 调用；Plan 建议先核时间窗、做 SQL count、再归纳。Runtime 同样先获得完整的零条 `get_recent_messages`，但继续调用 `get_schema` 与 `execute_sql`。三次中的 SQL 都返回聚合统计行；第一次为同窗 `msg_count=0, senders=0`，后两次还包含全局 min/max/count 统计。没有实际消息候选、Retrieval miss 或覆盖不足。

Planned 模型最后也输出 `kind=no_result`。第一次失败发生于 Evidence finalizer 的 `has_verified_zero_result_evidence`：它把每个非 schema SQL row 都当成“存在可引用结果事实”，于是即使完整时间窗检索已证明 0 条，也拒绝了零结果。`INVALID_FINAL_OUTPUT` 是该证据资格拒绝的终态，不是模型 JSON 解析失败。Planner guidance 与额外 SQL 调用有强相关；单次生成和 Provider 随机性下不能声称严格因果，但三次相同方向支持针对性修复。

`dev-zero-empty-1/2` 的部分 Planned 观察从 `get_schema`/SQL 开始，完全没有取得 `get_recent_messages` 的 complete-empty 正证明；它们输出带 SQL row citation 的普通 claims，或在一次 repeat 中虽有完整检索却又被后续 SQL row 拒绝。因此三条 Case 共享“软计划可能诱导多余调查”的风险，**不共享一个充分修复点**。仅放行零计数统计不能让 SQL-only 路自动成为 verified zero。

## 最小修复与边界

`get_recent_messages` 对明确时间窗的完整零条结果仍是正证明。Evidence finalizer 只在该证明存在时允许数值型 SQL 聚合统计行并存；SQL-only、partial/error、实际消息行、非聚合行、同窗正计数冲突继续拒绝。Runtime prompt 明确完整零条时间窗已回答“是否有消息”，软计划建议的额外 SQL 不是必做步骤。Provider SDK 设 `max_retries=0`，使计费请求失败不自动重发。

确定性测试覆盖上述正反边界；真实模型是否仍执行额外 SQL、三次回归是否稳定消失，要以修复后的新配对观察判断。没有放宽 GT、修改旧 run 或重新解释历史结果。生产 Router 继续 shadow。
