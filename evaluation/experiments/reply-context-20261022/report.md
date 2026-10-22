# 2026-10-22 · 关键回复恢复审计与修复

已确认并修复两处独立缺口：局部邻居窗口无法恢复远距离直接回复；模型消息投影丢失明确回复关系。另修正自动扩展只处理前 20 个锚点时的截断披露。本轮模型请求 **0 次**，结论限于确定性回复恢复、模型可见关系和来源绑定，不宣称真实模型答案质量提升。

## 复现与根因

先新增 `tests/test_reply_context.py`，运行 `uv run pytest -q tests/test_reply_context.py`，得到 **2 failed**：

- 经真实导入 → SDK → Capability → 模型投影，原分享与评价之间隔 143 条噪声时，只返回分享，没有返回明确回复它的评价。
- 单独读到评价后，模型投影缺少 `reply_to_source_message_id`。

第一个失败来自仅按时间相邻消息取窗口，没有面向已知 anchor 的确定性关系补查入口；第二个失败来自 Host canonical message 有回复字段、slim projection 却没有携带。历史 Archify/Matt 的目标回复在工具返回前就已缺失，因此单补字段无法修复召回。

## 产品改动

- 复用现有 `get_message_context`，增加显式 `include_replies: bool = False`。默认仍只读邻居；开启后按 anchor 的平台消息 ID 查直接回复，不递归展开讨论树。
- 普通消息通过 SQL 同时限定 anchor session 与 trusted 时间范围；转发消息限定同 root、直接 parent/container，沿用外层转发时间。没有 anchor 平台 ID 时显式报错，不制造零回复结论。
- anchor、直接回复与邻居共用原结果容量，anchor/回复优先。多读相对于回复槽位的一条哨兵，通过 `returned_replies`、`has_more_replies` 和 `truncated` 公开边界；候选合并计数明确是已观察并集，不伪称全部回复总数。
- 模型只对真实回复增加原始 `reply_to_source_message_id`；目标在当前结果内且唯一时，增加对应的 `reply_to_source_id`。普通非回复消息不增加冗余平台 ID。预算裁掉目标时同步撤掉关系 handle，原始回复事实仍保留。
- 投影预算省略时，显式请求的 anchor/回复排在普通邻居前。沿用现有 Token 上限、裁剪与预算错误协议，不扩大 16k 池或工具轮次。
- 修复自动扩展的披露：requested context 只扩展前 20 个 direct hit 时，即使最终列表没有超容量，仍标记 `truncated=true`。这是边界披露修复，不能单独计为答案收益。
- SDK schema、Capability metadata、工具请求/结果 Trace 与 Evidence query snapshot 同步携带新语义；Prompt 只补新参数、回复标识和结论边界说明。

## 真实 Development 快照对照

使用 10-20 已保存的 canonical 快照及明确指定的三个 Development targets 文件；只读连接，不加载 Holdout、不修改 GT、不重建索引。快照文件大小/mtime 审计前后相同。固定目标文件中的已知 anchor，使用生产 SDK 和独立原 16k 工具结果预算池，不调用模型。

| Case | 邻居 2/2：模型可见目标 | 相同 2/2，仅开启回复补查 | 邻居 3/5 | 仅 anchor + 直接回复 | 关系与目标 Citation |
| --- | --- | --- | --- | --- | --- |
| Archify | 1/2，5 条消息 | 2/2，7 条消息 | 1/2，9 条消息 | 2/2，3 条消息 | 通过 |
| Matt-1 | 1/2，5 条消息 | 2/2，7 条消息 | 1/2，9 条消息 | 2/2，3 条消息 | 通过 |
| Matt-2 | 2/2，5 条消息 | 2/2，5 条消息 | 2/2，9 条消息 | 2/2，2 条消息 | 通过 |

2/2 与“相同 2/2 + 回复补查”只改变 `include_replies`，用于隔离关系获取效果；3/5 与仅关系结果是额外读取方式对照。仅关系结果的完整投影估算分别约 918 / 976 / 807 Token，均无模型投影省略。数字是 Host transport 估算，包含实测耗时元数据，不是 Provider Usage。

目标回复均进入 canonical 返回及模型可见消息，原始关系与当前结果内的短 handle 关联一致；手工构造的绑定候选通过真实 Host Finalizer，来源指向真实目标回复。该候选只验证绑定能力，不是模型生成的最终答案。

复核命令：

```sh
uv run python scripts/audit_reply_context.py \
  --database data/evaluation/quality-optimization-20261020/trivae.sqlite3 \
  --targets \
    data/evaluation/quality-optimization-20261020/cases/quality-dev-context-archify.targets.json \
    data/evaluation/quality-optimization-20261020/cases/quality-dev-context-mattpocock-1.targets.json \
    data/evaluation/quality-optimization-20261020/cases/quality-dev-context-mattpocock-2.targets.json \
  --output data/evaluation/reply-context-new-audit
```

输出目录必须尚不存在；结果包含私有定位，保留在 ignored `data/evaluation/`。本轮最终配对工件为 `data/evaluation/reply-context-20261022/paired/summary.json`，先前分阶段审计也保留，不覆盖历史输出。目标、关系或 Citation 未恢复时脚本保存结果后非零退出。

## 验证与边界

- 新增 12 项确定性回归：远距离回复送达、独立关系投影、默认局部行为、容量 1/2 与哨兵披露、半开时间/跨群隔离、跨转发/嵌套容器隔离、缺少平台 ID 显式错误、预算下回复优先、生产 SDK loop 的搜索 handle → 关系补查 → Citation/Trace、20 锚点披露、目标裁剪后无悬空关系 handle。
- 完整 pytest：**1,241 passed / 1 skipped / 0 failed（29.42 秒）**。Ruff `src tests scripts`、mypy `src`（129 文件）、`git diff --check` 通过。
- 保持原预算、现有自动窗口与锚点数量；不引入重试、检索失败切换或针对案例名称的产品分支。没有新增模型请求、Provider/Judge 成本、历史压缩或 Semantic 参数调整。
- 本实验人为固定正确 anchor，证明其后补查路径已打通；不证明 Agent 会自主选中 rank 43 的 anchor、会正确开启参数，或会在原 16k 池耗尽前完成补查。真实模型的自主选择与最终答案收益仍待独立对照。
- 只追踪导出数据中的明确直接回复；无回复标记的反馈、递归回复链、超过容量的更多回复，以及未导出的内容仍不保证覆盖。不能从固定 GT 恢复推出全库完整性，也不能从 GT 未命中直接判整题错误。
