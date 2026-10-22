# 2026-10-22 · 回复补查真实模型终端验收

使用当前 ChatGPT Plan / gpt-6.1-sol / medium 跑完三条原始 Development 问题与一条合成控制，共 **12 次真实推理请求**，均 `response.completed`。四条查询均 completed，模型均自主开启 `include_replies`；合成控制成功恢复并引用远距离真实回复。三条原题仍未把旧固定目标回复送达模型，因此不能把上一轮离线修复解释为端到端质量提升。

## 条件与计数

- 复用已授权的本机 Plan OAuth，不创建或读取 API key 正文，不改变模型档位。账号模型目录预检通过；目录请求不冒充推理请求。
- 原三题分别为 Archify、Matt-1、Matt-2，问题、scope、GT 保持 10-20 Case 原样。使用同一份 811,892 条消息快照和已完成的现有语义索引，macOS 文件克隆到独立实验目录；不改原实验数据库、不重建真实索引、不读取 Holdout。
- 生产 Prompt/工具 schema 包含上一轮回复补查修复。Standard 路径、七种生产工具、3 工具轮/8 模型回合、原 16k Tool Result 池；没有向模型注入 GT、目标 anchor 或 `include_replies` 使用指令。独立 Jev shadow 仍关闭，不调用 Router/Planner 模型。
- 三题预先冻结，每题一次。独立账本上限 24 次/每 Case 8 次；真实 HTTP 发送前预扣并 fsync，失败也计入，无自动重试、补跑或 Judge。
- 三题之后单独登记合成控制，共用原账本剩余额度，不覆盖三题协议和结果。实际总用 12 次，0 次门禁阻断。停止因为验收已完成，并非额度耗尽。
- 12 个响应的 Usage 均完整：输入 **167,113**、输出 **3,377**、合计 **170,490** Token。这里是多次输入的累计 Usage，不是单次 Tool Result 池大小；未调用独立付费 Provider。

## 三条真实原题

| Case | HTTP / 工具轮 / Tool Call | 主动补查 | 固定 GT：Host → 模型 → 最终 Evidence | 预算与交付 |
| --- | --- | --- | --- | --- |
| Archify | 3 / 2 / 4 | 模型声明 3 次 `include_replies=true` | 1/2 → 1/2 → 0/2 | 首轮 14,699 Token；两个预算错误；completed、4 组 Citation |
| Matt-1 | 3 / 2 / 2 | 1 次 `include_replies=true` | 1/2 → 1/2 → 1/2 | 两个工具正常返回；completed、4 组 Citation |
| Matt-2 | 3 / 2 / 4 | 模型声明 3 次 `include_replies=true` | 2/2 → 1/2 → 0/2 | 一个预算错误；completed、4 组 Citation |

三题全部是分享 anchor 可见、旧 required reply 不可见。所有实际完成的关系查询，其 `returned_replies` 为 0：模型选中其他消息作为补查 anchor，没有选中这些固定目标的 anchor；因此不能把调用了新参数当成已经恢复了目标回复。

- **Archify**：首轮占约 92% 的 16k 池；第一次 context 投影 647 Token，只保留 1/13 条消息；另外两次 SDK context 返回明确预算错误。最终投影共 15,742。答案引用其他已取得的正负反馈，包含具体使用场景、运行成本及信息保真限制，没有证明新关系检索带来质量收益。
- **Matt-1**：先取得 28 条 direct hit，投影省略 72 条自动邻居；再对另一条评价消息以 before=10/after=25 补查，返回 36 条消息、0 条该 anchor 的明确回复，未触发预算退出。答案提供 `/teach`、使用方法与其他正面话语，并区分未体验过的建议和机器人说明。但旧目标“这个好用”的直接回复未送达。
- **Matt-2**：原 required reply 存在于完整 Host 结果中，却未进入模型投影。两次 context 返回后，另一调用因预算失败；总投影 15,713。答案仍引用其他短评价及流程讨论，不能根据旧 GT 0/2 机械判整题错误，也不能据此宣布目标恢复完成。

三题确定性检查合计 **42 passed / 3 not_applicable / 0 failed**，引用绑定均通过、限制保留。它们验证协议、来源和交付，**不等同于答案事实充分或新功能有效提升质量**。本轮没有修改生产预算、检索排序或为特定案例新增 Prompt 规则，也没有为得到成功结果重复原题。

## 合成群聊 + 真实模型控制

前三题没有真正取回一条属于所选 anchor 的直接回复，因此另建一份明确标记为 synthetic 的 145 条消息数据：

- 原问题提到虚构项目 NebulaKit；143 条中间消息均无关。
- 唯一体验回复不含项目名，通过导出回复边指向原问题，内容为“已经在测试项目跑过，图结构清楚，但导出偶尔缺节点”。
- 只开放 lexical_search/get_message_context，创建独立合成 FTS，不使用真实聊天语义索引。未向模型提示目标位置、回复 ID 或补查参数。

模型自行执行 lexical_search，然后对返回的 source handle 调用 `get_message_context(context_before=0, context_after=40, include_replies=true)`。目标回复远在 after=40 之外，通过关系查询额外恢复；返回 `returned_replies=1`，目标进入模型输入与最终 Citation。

3 HTTP / 2 工具轮，查询 completed，1 组 Citation，来源包含原问题与目标回复。真实最终答案同时保留“图结构清楚”和“导出偶尔缺节点”，并明确仅是测试项目反馈、不能推为适合生产。这证明真实模型能使用新参数并消费关系查询找回的消息；**不替代真实群聊质量对照**。

## 终端工件与复核

运行入口是终端 Python 模块 → EvaluationRunner → 生产 Application.query → 真实 Responses/SDK → Tool/Finalizer；不是完整交互 TUI 会话。合成控制另调用生产 plain CLI 渲染函数。

首次按文件路径启动实验脚本因 `scripts` 包导入失败，发生在推理前；随后改用 `python -m` 正确启动，没有因此补跑任何已发送的 Query。合成控制首次调用 CLI 渲染器漏传 source summaries，原 `terminal.txt` 因而未展示来源索引；已修正实验脚本，从同一持久化 Artifact 零 HTTP 再渲染 `terminal-with-sources.txt`，确认同时存在 anchor 和 reply 来源。原模型结果及首次终端输出均保留，未修改产品渲染器或重跑模型。

```sh
uv run python -m scripts.run_reply_context_live prepare
uv run python -m scripts.run_reply_context_live archify
uv run python -m scripts.run_reply_context_live matt1
uv run python -m scripts.run_reply_context_live matt2
uv run python -m scripts.run_reply_context_control
uv run python -m scripts.analyze_reply_context_live
```

上述运行已完成，不应为复核再次发送请求；各目录与 Case 有一次性门禁。原始 Trace/正文、协议、执行脚本冻结副本、账本和快照保留在 ignored `data/evaluation/reply-context-live-20261022/`。三题初始分析在 `analysis.json`，包含合成控制与最终 12 次计数的汇总在 `final-summary.json`；终端补渲染记录在 `control/terminal-render-verification.json`。

新增三个实验/分析脚本，未修改产品代码。Ruff `src tests scripts`、mypy `src`（129 文件）、`git diff --check` 通过；相关回复回归及账本测试 **15 passed**。本轮没有重新跑完整产品测试；上一轮产品修复的完整回归为 1,241 passed / 1 skipped。

下一步更有证据支持的实验是控制首轮结果对后续预算的占用，并验证模型对有价值 anchor 的选择；继续扩大工具轮次缺乏本轮证据。已有离线修复有效、真实模型能用新能力，但真实问题中的收益仍受这两个瓶颈限制。

后续零模型分层重放进一步区分了三题原因：Matt-2已取得的回复被搜索投影整批删除；Matt-1改正确anchor即可在原额度恢复；Archify改正确anchor后仍受704Token单次额度限制。完整证据见 [遗漏原因诊断](miss-diagnosis.md)，不能把三题统一归因为总预算不足。
