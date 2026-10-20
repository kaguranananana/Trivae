# Research: 当前 Context / Evidence 链路与历史修复边界

- Query: 历史 context 失败在当前是否已修；自动扩展、显式上下文、预算与回复关系是否存在可复现的最小缺口。
- Scope: internal；只读源码、规范、任务记录，合成 fixture 本地复现；未调用 Provider、未打开生产数据。
- Date: 2026-10-20

## Findings

### 文件与规范

| 文件 | 职责 |
| --- | --- |
| `context.py`（`src/trivae/retrieval/`） | `ContextExpander.expand/expand_ranges`：自动窗口、命中保护、20 个 source-hit 预算和显式截断 |
| `lexical.py` | `LexicalRetrieval.search`：调用 scope-bound context，向 Tool 传播 partial/truncated、source-hit operational metadata |
| `get_message_context.py` | 已知 canonical anchor 的 scope 校验与同 session 显式窗口 |
| `sqlite_read.py` | canonical lookup、按时间/seq/ID 排序的 scope-bound 邻居读取、转发容器边界 |
| `evidence.py` | ToolResultRecord、source handles、slim model projection、预算裁剪与 finalizer |
| `openai_tools.py` | 真实 SDK schema、source_id 到 canonical identity 的转换、Tool/Trace 交接 |
| `qq_export.py` | `_reply_target` 从结构化 reply element 读取真实父消息 ID |
| `test_evidence.py` / `test_context_source_contract.py` / `test_retrieval_budget.py` | 当前可复用的 source、projection、budget 测试 |
| `scripts/run_prompt_screening.py` | 现有成本控制实验入口；支持 static/first-tool/targeted/paired-targeted/candidate-only/freeze-baseline/full-gate |

已读相关规范：`workflow.md`、`backend/index.md`、`project/index.md`、`engineering-principles.md`、`agent-runtime-guidelines.md`、`database-guidelines.md`、`stage-1-8-evidence-citation.md`、`planner-engineering-closure.md`。关键契约：候选不等于 Final Evidence；finalizer 只证明来源与形状，不证明自然语言回复关系；各层预算独立、超限事实应透明；不通过扩大窗口、retry 或 fallback 掩盖失败。

### 历史失败在当前的状态

1. `09-27-planner-retrieval-degradation-v3/design.md`、`validation.md` 明确区分两个根因：dependent 先从具体实体泛化成类别宽搜，所需来源在候选集里已缺失；archify 是 context-anchor 选择不稳定。彼时 100-hit cap 正确披露 partial/truncated，不能据此认定 Retrieval 损坏。当前默认/上限已变化，不能把历史 100 当作当前上限。
2. v3 只修改共享 Runtime prompt，未新增固定调查执行器。archify 两组 Planned 恢复上下文，Standard 未恢复；dependent 两组仍遗漏。历史并没有证明“一条指导彻底修复 context”。
3. `10-02-planner-engineering-closure` 与 `agent-runtime-guidelines.md:815` 以后修复 source_id/message_id 参数说明与真实 SDK schema。当前 `openai_tools.py:604` 接受二者其一；`:632` 以后解析 source handle；错误参数不静默转换。`test_context_source_contract.py:18/38/82` 覆盖 schema、真实调用、raw/normalized Trace ownership。不能再把已修的说明缺失直接认定为当前根因。
4. `10-05-discussion-answer-quality/validation.md` 已证实正式工具能恢复推荐：向后 2/8 无目标，20 有推荐，40 有推荐及补充；40 条投影约 4779 estimated tokens，16k 内无截断。两次候选真实回答调用 context 并使用了推荐。当前 `prompt.py:92-114` 仍有关键提问优先调查、保留实体、邻接不证明直接回复等指导；`openai_tools.py:620` 窗口单位是消息条数，默认 8/8。
5. `evidence.py:1758` 已增加可信 `timestamp_utc`，预算裁剪保留作者/日期/source，轮次提示读取原 state。历史作者、日期、否定结论、穷尽性仍有残余生成错误；这些改动不保证每次模型选对锚点或窗口。

### 确定性候选 A：source-hit 预算省略未传播 truncated

代码：`context.py:160-165` 对自动 context 只读取前 `MAX_AUTOMATIC_CONTEXT_SOURCE_HITS=20` 个命中。`:212-220` 在合并消息未超过结果上限时，只在 **一个 source_hit 都没有读** 时标记 truncated。因此“部分 hits 已扩展、部分因 source cap 未读”会返回 truncated=false。`lexical.py:49-50` 直接继承此值，`evidence.py:_retrieval_limitations` 因而不能产生 retrieval_truncated。

本地合成复现（正式 `ContextExpander`，零 Provider）：21 个命中，每条均有独立后继，after=1，limit=100。实际读取 20 个锚点，返回 41 条，最后命中后继未读；结果 `partial=false, truncated=false`。

预算本身是既有设计，不建议增加读取次数。最小修复是当请求邻居且 source-hit 预算跳过了部分命中时，把这个事实并入截断；保留 partial 对真实命中缺失的既有语义。候选测试放 `test_retrieval_budget.py:176` 附近，扩展现有 source-hit 测试：21 个有真实独立邻居的 hits，断言 reads=20、不扩大预算、all hits 保留、truncated=true；0/0 请求仍不截断。再通过 `LexicalRetrieval → ToolResultRecord → model projection` 确认限制送达。

这是合成契约缺口；尚未声称它导致历史某次回答错误。特别是只有 5 个 direct hits 的 archify，不受 20-source cap 影响。

### 确定性候选 B：已知 reply 父消息结构在 model projection 丢失

`qq_export.py:324-338` 从 reply element 的 referencedMessageId/messageId 取稳定目标。`MessageProjection`（`structured.py:402-424`）保留 source_message_id、reply_to_source_message_id。`build_tool_result_record`（`evidence.py:1654-1664`）保留显式 context 的 canonical messages。但 `_model_message_projection`（`:1758-1798`）对普通消息不投影 source_message_id，也完全不投影 reply target。只有 `message_type="reply"` 和正文保留。

合成复现：一条 parent、一条 reply，reply_to=m1。canonical 和 Host record 均有 m1；正式 `project_tool_result_for_model` 返回 `truncated=false`，reply 的可见 keys 只有 author/content/content_truncated/hit/message_type/session/source_id/timestamp/timestamp_utc/urls，没有任何父消息定位字段。

主会话另行只读验证三个历史 required-context target 均有真实 reply 字段；研究子代理未自行读取其私聊正文。本项因此有真实案例线索，仍应由正式 Baseline Trace 核对该次消息是否实际送达模型，区分“消息未取回”与“消息取回但结构丢失”。正文的回复占位符与 @ 文本不能唯一绑定稳定父消息；相邻并不意味着回复。

最小修复候选：在已有 record 内按 `(session_id, source_message_id)` 索引，将实际 reply target 投影成当前 result 的 `reply_to_source_id` 短 handle；不新增读库、全库反向搜索、递归回复链或固定业务规则。目标不在当前消息里时如实表示未提供目标，不自造 handle。另一更直接的选择是投影原始 source_message_id/reply_to_source_message_id，但会向模型增加原始平台标识；应在设计时明确取舍。

适合测试：`test_evidence.py:349` 之后的 projection 测试、`:363` 的 expanded-messages 测试、`:420` semantic context trimming；`test_context_source_contract.py:38` 的 SDK/source handle 完整链路。覆盖目标实际在同 result、目标不在窗口、不同 session 同名 source ID、预算移除目标后不残留可用但不可见的 source handle。

注意 `_projected_source_ids`（`evidence.py:1989`）递归收集任何名为 source_id 的字段，reply 关系不能通过嵌套 `{"source_id": target}` 意外把被省略消息重新加入 provenance。新增关系字段应根据裁剪后真正可见消息重新检查，避免与目前“model-visible provenance 随 payload 收缩”的契约冲突。无需改变 finalizer 的语义蕴含责任。

### 其他预算与工具边界

- 显式 context 所有消息被 `_message_items(data.messages)` 视为可引用 primary item；它们不是再次 lexical 命中。超大结果仍可能受到 model projection 的正文缩短/尾部消息省略。对历史 40 条、约 4779 tokens 的窗口，已知不存在这一预算截断，不应先扩大预算。
- `project_tool_result_for_model`（`evidence.py:2089` 起）先删自动 context，再缩正文，最后删尾部 primary；同时披露 omitted_context_messages/omitted_hit_messages 并缩 provenance。canonical record 保留完整候选。Trace capture 裁剪不能据此推出 Provider 没见过正文。
- 显式 `get_message_context` 当前能够恢复更大的同会话窗口；没有专用自动遍历回复树能力。semantic SDK 虽保留 source/reply 过滤字段，但这不等于 Runtime 已有一套通过 source handle 获取全部回复的执行协议。
- `run_prompt_screening.py` 是现有 Prompt 比较入口，代码候选应确认基线代码冻结及两侧源代码隔离；不要把只替换 prompt 的模式误称为任意代码 A/B。历史 `real_pair.py` 可作为正式 Application、隔离 store 与同快照配对的参考，复用时应检查其固定常量和私有路径。

### 已运行验证

命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_retrieval_budget.py tests/test_context_source_contract.py tests/test_evidence.py`

结果：**52 passed in 1.55s**。现有测试通过与两个 synthetic reproduction 并存，说明不能将绿测解释为上述契约已覆盖。复现仅在内存构造英文 synthetic message，不输出真实正文/密钥，不修改源码或数据。

## External References

无外部浏览或第三方事实依赖；本研究以当前仓库源码、规范与保留的历史验证文档为依据。未调用 Provider。

## Caveats / Not Found

- 本研究不替代同快照、同 query/scope、同 route/model/budget 的真实 Baseline/Candidate 回归。
- 尚未把 source-cap 标记缺口与某个真实坏答案建立因果连接；优先级应服从 Baseline Trace 的首个偏离点。
- 回复结构送达能消除 Host 已知事实的损失，不能强迫模型使用，也不能自行证明推荐、firsthand use 或回复语义。
- 不建议为本轮新增自动追所有 hit、固定 40 条窗口、全局扩预算、retry、reranker 或独立 Judge。
