# 2026-10-22 · 搜索回复送达修复与真实模型验收

原来三条 Development 问题都未把固定目标回复送达模型。本轮修复搜索自动上下文和模型投影后，**三条目标回复全部首轮送达，全部被真实模型最终回答引用**。完整回归 1,246 passed / 1 skipped；真实 Plan Medium 共 7 次推理，三题各运行一次，全部 completed / finalization valid。

## 根因与最小修复

1. 搜索只对前 20 个命中扩展局部邻居；关键词不在回复正文中、回复距离远、原消息排在第 20 名之后时，即使原消息已命中，也可能取不到回复。模型还要从大量原消息中自行挑补查锚点，第二轮未必有足够预算。
2. 搜索结果投影一旦超额，原实现会一次删掉全部非 hit context。Matt-2 的正确回复已在 Host 结果，却与 72 条普通邻居一起删除，留下大量可用额度。

现在搜索请求 before/after 上下文且命中未占满容量时，批量取得全部已返回 hit 的明确直接回复，再用剩余容量填普通邻居。仍保留所有直接命中，回复不伪装成关键词 hit；0/0 不自动查回复，普通邻居仍限前 20 个锚点。普通消息按同 session/time 读取，转发另限同直接 parent/container；不递归展开线程，不增加消息 limit。

投影先从普通邻居尾部省略刚好需要的数量，优先保留关联到 hit 的回复；仍不足时按既有规则缩短正文、再省略尾部 hit。省略 hit 时同步移除其附属回复，公开省略计数，provenance 与关系 handle 随可见来源同步。没有追加重试或针对 Archify/Matt 的产品分支。

批查以一次普通消息索引连接和每个转发 root 一次解析完成；新增 `idx_messages_session_reply` 支持按会话及回复目标读取。应用初始化创建该访问索引，不修改 canonical 消息或 revision，不重建 FTS/语义向量。

工作代码提交 `366f290`，后续离线引用/来源编号核验脚本提交 `7a7bdde`。

## 固定旧输入的零模型重放

保留原失败工件；从其 Trace 取首轮实际工具参数及单次 15,801 Token 额度，在独立克隆上运行当前生产检索与投影。只允许自动 context 改变，断言直接命中身份及顺序与旧运行完全一致；同时核对两目标可见、回复 handle 指向正确原消息、总条数未越原 limit。

| Case | 直接命中 | Host / 模型可见消息 | 省略普通 context | 旧 → 新模型目标覆盖 | 新投影 Token |
| --- | ---: | ---: | ---: | --- | ---: |
| Archify | 67，不变 | 100 / 100 | 0 | 1/2 → 2/2 | 15,262 |
| Matt-1 | 28，不变 | 100 / 95 | 5 | 1/2 → 2/2 | 15,762 |
| Matt-2 | 28，不变 | 100 / 95 | 5 | 1/2 → 2/2 | 15,727 |

三题均无 hit 被投影省略，三条目标回复关系正确解析。上述是固定参数的根因核验，不冒充模型自主检索；真实验收见下节。

## 三条原题的真实模型结果

复用本机 ChatGPT Plan OAuth / gpt-6.1-sol / medium，原 10-20 问题、scope、GT、811,892 条消息快照及既有语义索引。Standard 路径、生产 Prompt 与七种工具、3 工具轮 / 8 回合 / 16k Tool Result 池保持；无目标提示、Judge、独立 Jev、Holdout 或索引重建。

预先冻结到独立协议/账本，每题只执行一次，HTTP 发送前持久化计数，失败也计入；没有推理重试或为结果补跑。账本上限 24 / 每题 8，实际 **7 次，0 门禁阻断，7 个 response.completed，Usage 完整**。模型自行选择参数，因此真实搜索窗口可不同；上一节固定旧参数重放用于区分代码效果与模型策略变化。

| Case | HTTP / 工具轮 | Host → 模型 → 最终 Evidence 固定目标覆盖 | 目标回复引用 | 来源编号 | 首轮投影 Token |
| --- | --- | --- | --- | ---: | ---: |
| Archify | 3 / 2 | 2/2 → 2/2 → 1/2 | 是 | 9 | 15,256 |
| Matt-1 | 2 / 1 | 2/2 → 2/2 → 2/2 | 是 | 7 | 15,762 |
| Matt-2 | 2 / 1 | 2/2 → 2/2 → 2/2 | 是 | 6 | 15,728 |

Archify 最终没有引用固定分享 anchor，但引用了其正确回复，因此 Evidence 是 1/2；不能写成所有目标均最终引用。三个“目标回复引用”都由持久化 Artifact 的真实 source identity、Evidence 和 content block binding 验证。

实际答案的变化：

- **Archify** 明确提到有人直接回复项目分享说“好用”，引用新恢复的目标回复；同时采用关联回复中“流程/时序细节缩减”的负面反馈，区分渲染建议与问题已经解决的证明。旧目标回复从未送达，现已进入答案事实与引用。
- **Matt-1** 明确说明有人直接回复“下载 skill 后使用 `/teach`”的建议，说“这个好用”；也包含“teach 一般”的反面意见，并提示短评不能代表完整项目验证。
- **Matt-2** 引用原分享对应的“这个真好用吧”，区分仓库好评、`/teach` 的争议和仍需人工审批的流程评价。目标来源均可追溯。

最终有 5 / 4 / 5 组 Citation binding，确定性检查合计 **42 passed / 3 not_applicable / 0 failed**。累计 Usage 输入 **110,808**、输出 **3,397**、合计 **114,205**；这是累计模型输入，不是工具池大小。两道 Matt 本次一轮搜索即结束，不能由单次观察断言稳定省请求。

## 边界与仍存在的预算限制

Archify 首轮保留了目标回复，但后续两次补查仍明确返回 `TOOL_RESULT_BUDGET_EXHAUSTED`，最后综合已有材料，限制进入最终 Artifact。Matt 首轮接近工具池上限，Runtime 随后进入无工具综合。此次没有解决“首轮给后续调查保留多少额度”的一般策略问题，也没有以扩大池来掩盖它。

本轮确认的是原三题回复丢失与引用链修复，不是所有问题的质量提升统计。两道 Matt 使用同一主题资料，不能视为独立大样本；未检验缺少导出回复边、超出容量或未命中原消息的情况必然恢复。Semantic range 保持原检索语义，未自动增加关系扩展。预算裁剪、未展开转发等覆盖限制仍公开。

## 终端、网络与本地 Web

首次真实验收在 OAuth 刷新阶段报 `AUTH_NETWORK`，尚未发送推理。复现发现终端直连 DNS 超时；macOS 已配置的 `127.0.0.1:7892` 代理可完成认证与模型目录预检。保留初次失败工件，随后仅为本次进程设置 HTTP/HTTPS 代理及 localhost 例外。没有修改全局网络、认证流程或模型配置。

真实执行链为终端模块 → EvaluationRunner → 生产 Application.query → Responses/SDK → Tool/Finalizer。另从同次运行 Conversation Store 的已提交 Artifact 零 HTTP 还原，用生产 CLI Evidence/Sources 组件生成 `terminal.txt`，不是再调用模型或编辑答案。核对目标回复 Sources 编号 9 / 7 / 6 均存在，分别绑定到最终结论。

Web 从旧 PID 31153 重启为 40113，使用同一现有代理；`/api/readiness` 的数据库与 Plan/Sol 均 ready，当前本地库 827,614 消息，回复访问索引已创建。该库与实验冻结的 811,892 条快照明确区分；Web 健康检查没有推理请求。GitHub SSH 443 经同一代理连接成功，普通 push 已将远端 main 从9539aec更新至a4e7fbb，包含此前网络阻塞的提交；未强推或更改全局 SSH。

## 验证与工件

- 原最小复现：2 个搜索投影失败、2 个自动关系扩展失败；修复后通过。新增 5 项回归覆盖已取回回复被裁掉、仅省略必要邻居、远距离回复、20 锚点外原消息，以及混合普通/转发 scope。
- 完整 pytest **1,246 passed / 1 skipped / 0 failed（30.49s）**；Ruff `src tests scripts`、mypy `src`（129 文件）、`git diff --check` 通过。最后新增的是离线验收脚本与文档，没有再次修改已验收的产品逻辑。
- 旧失败与旧诊断保持原样；新协议、账本、快照、完整 Trace/正文、Usage、重放和引用核验在 ignored `data/evaluation/reply-repair-20261022/`。`repair-replay.json` 验证固定旧输入，`analysis.json` 验证真实送达，`answer-verification.json` 验证最终引用与来源编号。

本轮已执行命令如下；prepare、逐题运行及工件写入有一次性约束，复核时读取现存工件，不应重复发送推理：

```sh
uv run python -m scripts.run_reply_context_live prepare --root data/evaluation/reply-repair-20261022
uv run python -m scripts.verify_reply_repair --root data/evaluation/reply-repair-20261022
# 三个真实 Case 使用上文说明的现有进程代理，分别只运行一次。
uv run python -m scripts.run_reply_context_live archify --root data/evaluation/reply-repair-20261022
uv run python -m scripts.run_reply_context_live matt1 --root data/evaluation/reply-repair-20261022
uv run python -m scripts.run_reply_context_live matt2 --root data/evaluation/reply-repair-20261022
uv run python -m scripts.analyze_reply_context_live --root data/evaluation/reply-repair-20261022
uv run python -m scripts.verify_reply_answers --root data/evaluation/reply-repair-20261022
```
