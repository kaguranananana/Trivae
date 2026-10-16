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

- 最终修复后 Python：1038 passed，25.35 s；Web：69 tests / 12 files、lint、typecheck、生产 build 全通过。
- `uv run ruff check src tests`、`uv run mypy src`、`git diff --check` 全通过；额外将真实核验脚本与 src 一起 mypy，123 文件通过。
- 当前全库 FTS+上下文 12 次顺序查询：首次 11040.65 ms；其余 warm 中位数 761.59 ms，最大 5574.93 ms（与本地模型加载/全量构建/测试并发）。首次包含全库缺失信息清单建立，后续按 revision 缓存。这是本机实测，不承诺跨设备 SLA。
- FTS 后 Canonical/messages/users/memberships/sessions/message_sources/message_variants 数量均与 baseline 相等；23 个原始文件的 size / mtime 均不变，Canonical revision 为 0。

## Remaining validation

最终全仓检查、全量 Qwen 构建、原始来源/Canonical 不变断言、新旧索引切换、全库真实 Agent 与冷/热时延将在成功后补充。本任务尚未以定向运行声明全部完成。
