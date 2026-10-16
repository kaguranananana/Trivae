# QQ 合并转发检索质量审阅

审阅时间：2026-10-16（Asia/Shanghai）。审阅角色：独立 trellis-check；未派生其他代理，未提交或推送，未写入真实数据库。已有 `.opencode/package.json` 改动不属于本任务。

## Findings (fixed)

- 文件：`chunking.py`、`test_forward_semantic.py`。
- 问题：首次全仓测试复现了转发图片 caption 被忽略：QCE 优先将混合消息分类为 image，原有 `is_semantic_void` 按类型跳过，导致实际文字没有进入 embedding。首次检查结果为 1,037 passed / 1 failed，失败项为 `test_forwarded_media_caption_keeps_its_actual_text`。
- 修复：语义实现代理在同一轮审阅期间修复主链路。转发消息只剥除已知媒体占位符，再按剩余正文判定；普通消息的既有过滤规则保持。定向测试断言 caption 被索引、资源文件名不进入 embedding、canonical citation 仍保留 image 类型。本审阅代理未重复修改该文件。

## Findings (not fixed)

未发现其他需修复的实现缺陷或需要新增产品决策的问题。

- `messages=[]` / 缺少 messages 的 forward 节点属于源文件信息缺失，不能从 preview 补正文；现实现保留缺失路径、coverage gap 与 AnswerArtifact limitation。
- 完整真实 Qwen 索引重建、切换及全库真实 Agent 验证由主代理负责。本审阅的完整自动化检查通过不替代那些真实运行证据。
- `.trellis/spec/` 的长期契约同步由主代理负责：独立 occurrence 边界、外层时间过滤、canonical revision、forward provenance 历史序列化及来源展示需要记录。

## Cross-layer review

- 入口与真相源：QQExportParser 保留完整 `content_json` / `raw_payload_json`。`project_forward_tree` 从 canonical root JSON 递归恢复正文；不修改源导出文件，不向 `messages` / `users` / `memberships` 插入转发内部身份。
- 身份与来源：occurrence 使用 root internal ID 与数组位置组成，重复内部 source ID 和重复正文不会合并；子消息保留内部 source ID、作者身份、直接父、最外层父、JSON path、canonical first-wins 导出文件及 record index。
- FTS：沿用唯一 `messages_fts`，普通消息与 `forwarded_messages` 分支统一参与 MATCH。scope 分别约束各分支；候选正文重新从 canonical JSON 恢复。容器 preview 不进入正文索引。FTS、投影和版本在一个事务切换，解析失败回滚旧索引。
- Semantic：沿用统一 builder/chunker/vector store；普通消息流和转发流共享同一生成链路。session、root、direct parent 和 forward element 切开语义容器；短转发正文允许独立索引。KNN 在 Top-K 前应用群与时间范围，恢复后逐条复核范围，overlap 只按 occurrence 去重。
- 时间：`MessageProjection.timestamp` 一直表示当前群的转发时间；`forward.original_timestamp` 独立表示内部原始时间。检索、context、Citation scope 校验与展示遵循同一语义。
- Context：子消息定位可在派生表删除后从 canonical root 恢复。窗口与 range 不跨 root、直接父或 forward element，也不混入普通群聊邻居。
- 失效检测：FTS projection/tokenizer 版本与 canonical revision/count 明确检查。Semantic chunker identity、canonical revision/count 与 building/failed 状态在 query embedding 前检查；同数量正文变更会 stale，构建期间变更保留 failed 状态。
- Evidence：当前 Tool Result 的可信消息投影携带 forward provenance 和双时间；短 source handle 继续由 Host 解析为真实子消息。Finalizer 从当前 Tool Result hydrate，不能由模型伪造父子来源。
- Source/History：CLI、Web snapshot 和 source context 保留父子路径与双时间。Conversation JSON 保存可信快照，重启回放不重新检索；source inspection 重新读取 canonical 并检查可信 scope。
- 普通消息与冻结材料：普通数量、聚合、membership 和 structured SQL 仍基于 canonical。历史 prompt 固定契约已恢复，相关全仓回归通过。审阅未修改冻结 Evaluation、GT 或历史实验。

## Verification

最终代码检查均在 media caption 修复后重跑：

| 检查 | 结果 |
| --- | --- |
| `uv run ruff check src tests` | pass |
| `uv run mypy src` | pass；122 个源文件 |
| `uv run pytest` | pass；1,038 项，25.35 秒 |
| `git diff --check` | pass |
| Web `npm run lint` | pass |
| Web `npm run typecheck` | pass |
| Web `npm run test` | pass；12 文件、69 项 |
| Web `npm run build` | pass；127 模块 |

回归涵盖真实 Failure Case 文本形态、多层嵌套、空节点不使用预览、重复/跨群转发、两种时间范围、多个 forward elements、canonical JSON 来源恢复、派生重建幂等/回滚、版本/同数量变更失效、semantic scope 先于 Top-K、重叠去重、模型可见 provenance、Citation、production SDK tool loop、source inspection 与历史 round trip。

审阅未发现需额外添加的用例：上述行为已有针对性回归，本轮没有增加无依据防御、fallback 或单例规则。
