# Current Retrieval Budget Audit

## Summary table

| Layer | lexical | semantic | tool result | 当前限制来源 |
| --- | ---: | ---: | ---: | --- |
| Provider schema | default 1000 / max 5000 | default 10 / max 20 | N/A | `openai_tools.py` + `ExecutionScope.max_results` |
| Capability contract | input default 1000 / tool max 5000 | input default 10 / tool max 20 | N/A | `contracts.py` + capability checks |
| Trusted scope | 5000 umbrella | 5000 umbrella, semantic tool still clamps to 20 | N/A | `ExecutionScope.max_results` |
| Retrieval | `LexicalQuery.limit=1000`, hard cap 5000 | result limit 10/20；`dense_top_k=40`；internal pool `max(40, limit*4)` capped 1000 | N/A | `structured.py`、semantic retrieval |
| Context expansion | final messages cap 100 | final messages cap 100 | N/A | ContextExpander / `MAX_CONTEXT_EXPANSION_MESSAGES` |
| Evidence transport | canonical message items 5000；structured/value 100 | canonical message items 5000；structured/value 100 | fixed 16k estimated tokens | `evidence.py` 独立 message/structured bounds |
| Model projection | candidate count 与模型可见 payload 分离 | semantic candidate 与模型可见 payload 分离 | fixed 16k estimated tokens | runtime projection / `DEFAULT_TOOL_RESULT_TOKEN_BUDGET` |

## Shared limits found

旧的统一 `DEFAULT_RESULT_LIMIT=100` 当前直接或间接用于：

- `ExecutionScope.max_results` 默认 trusted ceiling；
- `SearchMessagesInput.limit` 默认；
- `LexicalQuery.limit` 默认；
- canonical Evidence transport 的最大 items；
- context expansion 最大 messages；
- provider-facing schema 的 maximum（经 trusted scope）。

本来独立、不能随 lexical 调大的限制：

- semantic input/query 默认 10；
- semantic `dense_top_k=40`；
- semantic internal candidate pool hard cap 1000；
- Tool Result model projection fixed 16k tokens；
- SQL/member 与 structured result 的小规模限制；
- provider tool rounds/calls 和 citation/source contracts。

## Failure mechanics

旧的多个 20 条限制曾导致 `total_hits=31 / returned_messages=20 / truncated=true`。统一提升到 100 后，真实回归变成 31/31、partial=false、truncated=false、citation unresolved=0。这个修复有效，但也让“100”承担了过多语义。

当前 broad lexical 的主要问题已定位为预算耦合：即使 SQLite 有 >100 命中，默认和 trusted scope 都在 100，模型无法请求更完整 inventory。修复后 semantic 的 provider schema、Capability 和 Retrieval Core 均独立 hard cap 20，不再随 trusted umbrella 放大。

## Context and projection findings

- ContextExpander 现在先判断 direct hits 是否已填满最终容量；已填满时不读取邻居。仍有空间时最多读取前 20 个 source hits，direct hit 始终优先。
- model projection 保持 16k token hard boundary：先去 context，再压缩正文，最后按稳定顺序二分省略尾部 direct hits，并记录 `truncated/omitted_hit_messages`；canonical record 保留完整候选。
- 真实 1000-hit projection 的二次复杂度已复现并修复：`https` 1000 的 projection median 从约 4576ms 降至约 154ms，省略数和可见 provenance 仍显式可审计。
- Trace 已记录 retrieval total/returned/partial/truncated、tool result estimated tokens、projection truncated count、provider usage；扩展时应复用而不是重建观测体系。

## Runtime context-window audit

当前 Runtime 只有 provider/model 配置，没有可靠 `context_window` 属性或模型 registry。固定 16k 对 32k/64k/128k 分别约为 50%/25%/12.5%。因此本任务保留 16k，并明确其临时 fixed-budget 属性，不引入 context-aware registry。
