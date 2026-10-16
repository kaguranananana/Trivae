# 全库候选排序与证据容量最小修复审阅

## 范围

本次审阅实际全量索引通过后追加的候选重排、Context core 容量保留和 Host 模型来源排序。读取当前 `design.md`、`check.jsonl`、backend quality/database/forwarded-message/error-handling 契约及相关代码、测试和已落盘真实结果。

Reviewer 仅写本报告；未修改生产代码、索引生成、identity、SystemPrompt、冻结 Evaluation 或原始聊天文件，未运行真实模型、重建/切换索引或 commit/push。已保存的真实结果只在内存中还原和重投影。

## Findings (fixed)

### P2：真实「情感锚点」在默认模型预算下丢失字面正文（已由主会话修复，reviewer 独立复核通过）

- 位置：`evidence.py` 的 `project_tool_result_for_model()` 第二阶段正文裁剪，审阅时约第 2093–2105 行。
- 根因：排序修复已经将真实 literal 子消息提升为第一个来源，但第二阶段仍对所有 hit 一律按 `(512, 384, 256, 192, 128, 96, 64, 32)` 缩短前缀。保留 source handle 不等于保留查询内容；同源可信 Citation 仍能生成，但模型看不到触发该命中的正文词面。
- **真实全库结果复现**：只读 `full-e2e-reranked-v1/2-semantic.json`，按领域契约恢复其中全部 78 条 expanded messages（28 条 forwarded），使用生产 `build_tool_result_record()` 和 `project_tool_result_for_model()` 在内存重投影。没有重新检索、调用 embedding 或模型。
- 目标原文长度为 52 字符，`情感锚点` 从 offset 40 开始；默认 `token_budget=16000` 后目标 handle `m1-1` 仍可见，正文只有 32 字符，`literal_visible=False`，且本次 `omitted_hit_messages=0`。所以问题已出现在当前真实返回集合和默认预算，不能仅归为极低预算的假设边界。
- 同一真实结果在 8000 / 3000 预算下也保留 handle、丢失词面；「远程连接」的真实子消息只有 25 字符，offset 15，默认及上述预算均完整保留词面。
- 最初新回归中的 `Exact Query` 或 `_child()` 正文把 query 放在开头，只能证明来源优先，没有覆盖该实际正文位置。主会话已替换为泛化的 52 字、offset 40 中文正文，并在 16000 / 1500 两档合成预算下断言完整正文、关键词、来源路径和双时间。
- 最小修复建议：在现有 Host 预算裁剪内，保护已确认 literal slot 的查询内容，例如对这类短正文保留完整初始有界正文，或保留包含 query 的真实有界片段，必要时继续按既有稳定优先序省略较低优先级 hit。保留 `content_truncated` 和模型预算事实，不修改 Retrieval/索引/冻结实验，不添加 FTS、fallback、扩池或关键词特例。
- 修复：主会话复用 `_semantic_literal_ids()` 统一 record 和预算裁剪优先序；第二阶段不再继续缩短已确认 literal source 的初始有界正文，其他 hit 保持既有缩短和尾部省略流程。初始 `MAX_MODEL_MESSAGE_CHARS=600` 上限、索引/查询池/来源身份不变。
- 修复后 reviewer 对同一个真实全库结果重新执行生产 Host 投影，确认完整 52 字正文和关键词可见，同时满足原预算。另以重排后的实际短 handle 调用生产 `finalize_answer()`，两个 case 的 internal identity、ForwardProvenance、外层 timestamp 和原始时间都与具体目标一致，均有 1 条正文 citation binding；没有错引。
- 本 reviewer 没有修改生产代码。报告不把真实 Agent 通过 lexical 或额外 context 获得目标，误写成 semantic 工具已经完整提供了该词面；上述修复结论由相同真实语义结果的 Host 重投影直接证明。

修复前复现结果（不提交聊天正文）：

| 真实 case | expanded / forwarded | token budget | 目标 visible chars | query 可见 | omitted hits |
| --- | --- | --- | --- | --- | --- |
| 远程连接 | 100 / 21 | 16000 | 25 | 是 | 1 |
| 远程连接 | 100 / 21 | 8000 | 25 | 是 | 41 |
| 远程连接 | 100 / 21 | 3000 | 25 | 是 | 90 |
| 情感锚点 | 78 / 28 | 16000 | 32 | 否 | 0 |
| 情感锚点 | 78 / 28 | 8000 | 32 | 否 | 32 |
| 情感锚点 | 78 / 28 | 3000 | 32 | 否 | 68 |

在真实全库结果生成前，另用同一真实子消息和 99 条合成 forwarded core 复现了同一边界；上述表格只统计后来完整真实结果的内存重投影，不把合成竞争者冒充真实语料。

修复后同一真实结果的复核：

| 真实 case | token budget | 目标 visible chars | query 可见 | 预算内 | omitted hits |
| --- | --- | --- | --- | --- | --- |
| 远程连接 | 16000 | 25 | 是 | 是 | 1 |
| 远程连接 | 8000 | 25 | 是 | 是 | 41 |
| 远程连接 | 3000 | 25 | 是 | 是 | 90 |
| 情感锚点 | 16000 | 52 | 是 | 是 | 0 |
| 情感锚点 | 8000 | 52 | 是 | 是 | 32 |
| 情感锚点 | 3000 | 52 | 是 | 是 | 68 |

两个完整真实 envelope 在 1500 预算下均因不可裁 metadata 基线仍过大而显式返回 `ToolResultProjectionError`，没有静默截掉来源后报成功。本次新增合成 1500 回归证明的是较小 metadata 的有效预算形态，不能冒充完整真实 envelope 也能装入该预算；无需为此扩改预算体系。初始 600 字模型 excerpt 的既有上限仍保留，本次不声称任意长正文的词面都能无界保留。

## Findings (not fixed)

无。本轮复现的实际缺陷已由主会话修复并独立验证；没有发现须继续修改的 scope、去重或引用身份问题。

## 其余已确认边界

- Retrieval 仍只调用同一个 provider 与 store，候选池仍为既有 `min(max(dense_top_k, limit * 4), 1000)`；没有 FTS 依赖、扩 K、新模型或 fallback。
- 现有池内先恢复 Canonical range，先核对群聊和转发时间，再对 sender/type/source/reply 等字段确定合格命中；只有这些合格消息包含完整 casefold query 时才提升候选。过滤掉的子消息词面不会给同块其他发送者虚增优先级。
- 重排只改变选取顺序；原 cosine score、dense rank 和 chunk 来源保持不变。`ranking_strategy` 和 literal candidate 数公开；具体 `literal_message_ids` 留在 Host metadata，不进入模型投影。
- overlap 以 occurrence ID 去重；同文跨父转发仍保留不同 occurrence。新回归覆盖了重叠块和重复转发，不会按正文或 source message ID 合并来源。
- Context 的 preferred IDs 只选择实际 core，不引入其他消息；超过 100 条时优先保留已确认 literal，最终 Canonical 展示继续按时间排序。无 literal 时保留旧有顺序。
- Host 使用同一条 record 顺序生成短 handle、模型正文和裁剪 slots；通过 internal ID 查找 ToolMessageItem，不把重排数组下标误当为另一条消息来源。现有回归未发现错引或越权。
- 候选池外仍属于 ANN 有界召回限制。literal 多于消息/模型预算时也只能保持优先序与明确截断，不宣称穷举。本轮没有为未被当前 Failure Case 证明的极端情况增加防御或测试。

## Verification

| 命令 / 检查 | 本次实际结果 |
| --- | --- |
| `uv run ruff check src tests scripts/verify_forward_retrieval.py` | pass |
| `uv run mypy src scripts/verify_forward_retrieval.py` | pass；123 files |
| `uv run pytest -q tests/test_semantic_literal_ranking.py tests/test_forward_evidence.py tests/test_forward_semantic.py tests/test_semantic_retrieval.py` | 初次 pass；46 tests，1.47 s；修复后 pass；47 tests，1.30 s |
| 真实全库已保存 Tool Result 的默认及 8000 / 3000 预算重投影 | 修复前复现词面丢失；修复后两项正文完整、词面可见且预算内 |
| 实际重排 handle → 生产 `finalize_answer()` | 两项来源身份、forward、双时间一致；均有 1 条 binding |
| `git diff --check` | pass |

主会话另行执行全仓测试、真实 Agent 与索引检查；本 reviewer 不将其结果计作自己执行的验证。
