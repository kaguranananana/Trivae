# Temporal overview coverage：实现计划与验收记录

## 实现顺序

1. [x] 独立 recent constants 与 typed `RecentMessagesQuery/RecentMessagesCursor`；保留通用 structured 上限。
2. [x] SQLite 统一加入 keyset cursor predicate，补齐 recent retrieval 的 total/remaining/coverage/next cursor 计算。
3. [x] Capability/SDK schema 接入 cursor，继承并校验 resolved window/session scope；更新 recent tool description 和 runtime prompt。
4. [x] ToolEnvelope、Trace、Evidence、model projection 和 budget snapshot 增加 retrieved/projected/omitted/coverage/time-range 事实。
5. [x] Answer Artifact/Conversation/UI codec 携带 Host-owned resolved time range/coverage，并自动保留 execution limitations。
6. [x] 补充单元、集成、Trace、no-result、回归和真实数据库 smoke/performance 验证。

## 测试矩阵

- recent default/hard cap 与通用 structured limit 独立。
- low-density complete、empty-window complete、large-window partial。
- cursor same-timestamp deterministic、无 overlap/无 gap、scope 不可扩大、window 不漂移。
- model projection token truncation：canonical retrieved 与 model projected 数量分离，omitted 可见。
- relative archive_latest：毫秒/UTC 文本/Tool meta/Trace/Artifact/citation 一致。
- existing lexical、semantic、structured、SQL、context、evidence、no-result、runtime、Trace、CLI/TUI/Web 回归。

## 真实数据库验收

基线只读事实：`data/trivae.sqlite3` 的 archive latest 为 `1786847688000`（UTC 2026-08-16 02:34:48），最近两天 half-open window 为 `[1786674888000, 1786847688001)`，count 为 2699，涉及 6 个 session。修复后 Case A-E、100/1000/5000 batch 的实际 retrieved/projected/coverage/latency/Trace payload 结果见同目录 `validation.md`。

## 完成门槛

实现、回归和真实 DB smoke 已全部完成；最终质量门禁与文档检查通过后将任务标记 complete。若后续测试失败，先按失败输出追到主链路，不修改测试来掩盖实现问题。
