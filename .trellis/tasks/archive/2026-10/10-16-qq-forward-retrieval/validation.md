# Validation

## Problem / Motivation

真实 failure：现有 QCE 导出中的内部正文已完整保存，但 FTS 和 semantic 只读取外层 content_text。`messages[6235]` 的「远程连接」及 `[6803]` 的「情感锚点」由此漏检，Evidence 也没有具体内部 occurrence 的定位。该问题属于派生检索和证据投影，不是 QQ 导出失败。

## Decision / Boundary

选择独立 derived occurrence 并复用唯一 FTS / semantic builder / Agent tools。直接拼正文到父消息不能精确归属作者和时间；插入普通 messages 会污染消息数、成员、时间和 canonical 去重，因此不采用。未增加检索工具、模型、降级或自动重试。跨版本增量 embedding 缓存仍不实现；长跑实际中断后，仅对同一次、同版本、同 Canonical 水位的构建增加显式续建。

Canonical JSON 是来源，投影/索引不是真相。scope timestamp 使用外层转发进入当前群的时间，内部原始时间单列展示；同一内部 ID 的不同转发位置各有身份。源群未知时不从昵称或预览推断。

## Measured baseline

- 修改前 `uv run pytest -q`：1006 passed，24.24 s。
- 全库 Canonical messages：765780；目标群：70803。
- 最新指定文件：46709 条外层消息、1636 个展开父、5675 条内部消息、11 个未展开深层节点。
- Canonical 合并所有来源后的目标群：1660 个展开父、5822 条内部消息、同样 11 个未展开节点。全库共 12484 条内部消息、189 个已知空节点。
- baseline FTS「远程连接」只命中 1 条普通群消息，目标父消息未命中；「情感锚点」0 条。
- 旧 semantic 状态：473236 条 Canonical、54267 chunks，v1；已不覆盖当前 765780 条 Canonical。

所有原始机器输出、来源文件 size/mtime、数据清单和聊天正文只在 ignored `data/evaluation/qq-forward-verification-20261016/`；没有变更冻结 Evaluation/GT/历史实验。

## FTS real data

重建耗时 21548.84 ms；FTS 778264 rows = 765780 Canonical + 12484 子 occurrence，源缺失节点 189。

| case | before | after | exact source |
| --- | --- | --- | --- |
| 远程连接 | 1 条普通消息，漏父/子 | 4 条，其中 3 条内部 occurrence | root `7681206893298204617` / child `7681206893298204686` / `content.elements[0].data.messages[10]` / source record 6235 |
| 情感锚点 | 0 | 1 条内部 occurrence | root `7681600793380910005` / child `7681600793380910019` / `content.elements[0].data.messages[6]` / source record 6803 |

以「远程连接」为例，内部原始时间为 2026-06-30 15:48:00 +08:00，转发进入本群为 2026-09-03 15:25:44 +08:00。实际投影和 Citation 快照分别保存两个时间，没有以内部时间替代群聊范围。

续建期间另行通过生产 LexicalRetrieval 核验两个真实 case：以各自外层转发的精确 1 ms 区间查询能命中目标子消息，以内部原始时间的精确区间查询不混入该 occurrence，切换至另一真实群后不会返回原群消息；上下文同样遵守外层时间和群范围。12484 个实际 occurrence ID 全部唯一。当前真实文件中已展开子消息均为第一层，没有已展开的更深层内容；多层展开及相同内部 ID 的重复/跨群转发由递归 fixture 回归验证，不把空节点称为已展开或伪造真实样本。机器结果见本地 `real-forward-scope.json`。

## Targeted actual embedding and Agent

在保持 Canonical root/source/record 不变的本地只读来源复制中，2 个真实父消息包含 44 条子消息。使用实际 `Qwen/Qwen3-Embedding-0.6B`、1024 维、标准 pooling/normalization：11 chunks，44 条内部消息全部计入覆盖，11/11 range 回读成功，向量/metadata 一致。该定向运行不冒充全库验证或质量 Benchmark。

`verify_forward_retrieval.py --run-agent` 的两个真实 case 均通过：模型实际调用 lexical_search、semantic_search 和 get_message_context，引用精确子消息，来源检查重新读取 Canonical JSON。

- 「远程连接」Trace：`trace-8d70ed17488a4bc2a38ce64eea7c070c`。
- 「情感锚点」Trace：`trace-bd66c47e82f1465aa1432e8a3470f815`。
- 新代码读取旧索引：显式 `SEMANTIC_INDEX_STALE`，没有查询 embedding 或静默降级。

## Failures found during verification

1. 历史 prompt 契约回归：SYSTEM_PROMPT 增加转发说明使 3 项固定实验映射失败。修复实现边界，将时间/缺失含义放在工具结果自描述字段中，撤回 prompt 修改；不改历史测试和冻结材料。3 项加转发 Evidence 回归 13/13 通过。
2. 真实媒体 caption 漏检：12484 内部 occurrence 中有 97 条媒体类型包含真实文字；旧 semantic_void 按 image/type 或开头占位符判定，可能丢弃说明。语义代理修复实际正文判断并回归。首次全量构建在 2332 条消息/319 chunks 时由主代理 SIGINT 中断，实际状态记录 `failed / KeyboardInterrupt`，保留 attempt1；旧 active 索引未切换。

caption 修复后的全库只读分块检查：12484 条子 occurrence、2443 parents、4903 chunks、9986 条有效正文、2498 条 semantic void、270 个 void-only chunks。逐条有效正文在实际 embedding input 中完整覆盖，0 uncovered；最大输入 5577 字符，小于 6000 上限。该结果是当前语料的 measured fact，不是未来任意长度正文的无界保证。

3. 长跑进程消失：2026-10-16 21:10 +08:00 再检查时，全量 attempt2 的进程已不在运行，文件仍为 building，水位 169476 / 765780，已存 20104 chunks，最后更新约 18:40 +08:00。日志没有可捕获异常终态，无法确认进程消失的外部原因，不推断为模型或业务错误。Canonical 计数/revision 和 23 个原文件再次核对不变。保留 interrupted-attempt2-state.json，增加同版本显式续建和独立进程日志执行，避免丢弃已有计算；测试及后续结果待补充。

续建修复验证：20104 metadata / 20104 vectors、missing=0、orphans=0。新增 8 项 resume / CLI 回归（含多个子场景），全仓 1046 passed，22.45 s；Ruff/Mypy 全通过。21:22:58 +08:00 以独立进程启动同版本续建，保留原有块并继续写同一 pending 索引；完成后会校验、单次原子替换 active，并执行工具明确查询与未指定工具的自然问法两组真实 Agent 验证。

4. 核验脚本假阳性：独立 review 证明遍历全部 Evidence 会把未绑定正文的候选误记为 Citation。主链路不受影响，修复核验脚本为实际 block → evidence → source 绑定，并保存绑定 ID、核对真实父子快照与双时间；新增回归通过。再次核验原先保存的两项定向真实 Artifact，分别有 4 / 6 条正文 Citation 实际绑定目标子消息。最新全仓 1047 passed（30.04 s），脚本与 src 合并 Mypy 123 文件通过。

## Automated gates / Performance

- 最终修复后 Python：1057 passed，21.67 s；Web：69 tests / 12 files、lint、typecheck、生产 build 全通过（本轮追加修改未涉及 Web）。
- `uv run ruff check src tests scripts/verify_forward_retrieval.py`、`uv run mypy src scripts/verify_forward_retrieval.py`、`git diff --check` 全通过；Mypy 共 123 文件。
- 当前全库 FTS+上下文 12 次顺序查询：首次 11040.65 ms；其余 warm 中位数 761.59 ms，最大 5574.93 ms（与本地模型加载/全量构建/测试并发）。首次包含全库缺失信息清单建立，后续按 revision 缓存。这是本机实测，不承诺跨设备 SLA。
- FTS 后 Canonical/messages/users/memberships/sessions/message_sources/message_variants 数量均与 baseline 相等；23 个原始文件的 size / mtime 均不变，Canonical revision 为 0。

## Full corpus actual build and switch

2026-10-17 02:36 +08:00，全库实际 Qwen v2-forward 构建完成并在校验后原子切换：765780 / 765780 Canonical、12484 / 12484 forwarded；92288 chunks = 87385 native + 4903 forwarded。续建复用 20104 个已保存块，本次实际计算 72184 个向量；本次续建耗时 18783511.51 ms（5 h 13 min），embedding 18419339.11 ms、索引写入 46792.49 ms；索引 556601344 bytes（约 531 MiB）。本机 Apple M4 / 16 GiB，batch=8；耗时不包含中断前已复用部分，不能误称从零全量耗时。

92288 metadata / 92288 vectors、missing=0、orphan=0；抽样 32 个向量的最大 norm 偏差 5.08e-9。4903 / 4903 转发范围逐条从 Canonical JSON 恢复，起止 ID 和消息数全部一致。23 个源文件 size/mtime 及六张 Canonical 表的计数全部保持 baseline，revision=0，`PRAGMA quick_check` 为 `ok`。旧 v1 索引保留为独立本地备份，active 当前为 completed v2；这些结论来自 `full-semantic-build.json`、`full-integrity.json` 和 `source-validation-final.json`。

首次全库查询在 Agent 运行前暴露并保留了失败（`full-e2e-final/`）：远程连接的正确 chunk 原始 dense rank=28 / pool=80，但直接取前 20 个，导致 returned messages 不含目标子消息；情感锚点的正确 chunk rank=19。诊断证明实际正文与向量没有丢失。修复采用池内通用完整 query 字面匹配重排，并保护 Context 与 Host 模型预算中的实际子消息来源；没有改查询词、放宽核验、扩大 K 或重建 embedding。新真实运行在独立目录记录，不覆盖失败记录。

`full-e2e-reranked-v1/` 两个真实 Agent 查询已通过实际 binding 核验，但独立 reviewer 用其中完整的 78 条情感语义结果在生产 Host 默认 16000 预算下重投影，发现目标 source 还在、52 字正文却被缩至 32 字，offset 40 的查询词丢失。主会话继续修复主链路：已确认 literal 的初始有界正文不再参与统一缩短，仍优先省略其他 hit；实际同一结果重投影恢复完整 52 字且预算内。回归使用泛化 52 字/offset 40 正文，不提交私人原文。核验脚本新增真实 semantic-model 投影输出，并要求正确子消息来源中的词面也可见，不能只因 returned messages、handle 或另一来源含关键词而通过。独立审阅及修复前后表见 `ranking-review.md`。

补跑启动器曾将 venv 解释器符号链接解析到环境外，引发显式 `ModuleNotFoundError: trivae`；修正为 `uv` 当前 `sys.executable`，保留启动失败记录。后续核验固定使用全量构建已验证的本地 Qwen 缓存（`HF_HUB_OFFLINE=1`），避免之前实际出现的 Hub HEAD SSL EOF；没有更换模型、修改 embedding 或新增生产重试。

## Final full corpus Agent verification

最终代码在新目录 `full-e2e-reranked-v2/` 和 `full-natural-e2e-reranked-v2/` 完成两组全库真实运行，`post-rerank-status.json` 为 done / completed。两组都先经过实际 Qwen semantic query 与默认 16000 模型预算投影，确认正确子消息中的查询词可见，再执行生产 Agent、检查正文 block → evidence → source binding，并从 Canonical JSON 重新检查具体子消息、父路径、源文件/记录号及双时间。以下均为最终运行，不以定向两父消息快照代替全库结果。

| 模式 / case | FTS 总数 / 内部 | 直接 semantic 恢复 / 模型来源 | 实际 Agent 工具 | Trace |
| --- | --- | --- | --- | --- |
| 两工具 / 远程连接 | 4 / 3 | 指定 `[6235]` 子消息 / `m1-1` | lexical_search、semantic_search、get_message_context | `trace-e9dcbaa121004ba097e8a44e024abccf` |
| 两工具 / 情感锚点 | 1 / 1 | 指定 `[6803]` 子消息 / `m2-1` | lexical_search、semantic_search、get_message_context | `trace-546042d8dfcf4952b285f612ee0bef65` |
| 自然问法 / 远程连接 | 4 / 3 | 同一指定子消息 / `m1-1` | lexical_search、get_message_context | `trace-c7cbccf82c224417b7ffc7e3da6cc309` |
| 自然问法 / 情感锚点 | 1 / 1 | 同一指定子消息 / `m2-1` | lexical_search、get_message_context | `trace-864cca331b1f4c7691c7205a87f43cec` |

四项正文实际引用均包含指定的目标子消息。远程 Case 还能分别追溯另外两条转发中的不同提及；没有按同一个关键词合并来源。手工检查最终答案确认，远程原文由浅仪式于 2026-06-30 15:48:00 +08:00 发送、9 月 3 日进入本群；情感原文由 JoyeBot 于 9 月 4 日 16:54:16 +08:00 发送、16:54:17 转发。答案没有将原始时间当作当前群活动时间，并明确源内容存在缺口。

自然问法为「群里有人讨论过“词语”吗？请说明当时谁说了什么，补充相关上下文并引用原始消息。」未指定工具或转发类型，Agent 自行选择 lexical + context；不将该模式误报为 Agent 同时调用了 semantic。两工具模式中模型可自行改写语义 query；另有直接完整短语的 actual semantic 验证证明指定子消息被恢复且词面确实交给模型，不把不同 query 的结果混称同一次命中。

最终直接 FTS + semantic + Host projection 合计耗时（不含后续 Agent 网络回答）：两工具运行首项 11193.24 ms、第二项 2686.08 ms；自然运行首项 10765.25 ms、第二项 2631.05 ms。首项包含本地模型冷加载，后项复用已加载模型；没有把这些数称为纯 SQL 时延或跨机器 SLA。全量重建是本机一次性长跑，支持显式同版本续建，查询与 rebuild 耗时分开报告。

最终四次 Agent 后又核对六张 Canonical 表、23 个原文件 size/mtime 与 revision，全部保持 baseline / 0，机器结果见 `source-validation-post-agent.json`。原始 JSON、冻结 Evaluation/GT 与历史实验未被修改。

## Completion / Remaining limits

全仓 1057 Python tests、Ruff、Mypy 123 files、Web 69 tests/lint/typecheck/build、独立 review、全库索引与四项真实 Agent 验证均通过。已复现的 candidate 截断、正文裁剪和验证假阳性均修复；没有待修复的 review finding。

目标群 11 个深层节点仍缺少导出正文，全库共 189 个；现有数据不能恢复其内部内容，结果与答案显式保留缺失限制，不从预览推断。当前真实可用消息只有第一层展开，更深已展开树、重复 ID/转发及跨群/容器边界由回归 fixture 验证。语义 ANN 候选池、6000 字 embedding input、1000 字 Host excerpt、600 字初始模型 excerpt 等既有容量上限仍保留，裁剪明确标记；当前真实有效转发正文的 embedding input 已全部完整覆盖。FTS 使用全文，来源查看回读 Canonical 原始内容，不把模型 excerpt 冒充完整原文。
