# 修复真实 Trace 的证据答案与交互展示质量

## Goal

修复真实 Trace `trace-68a55539c21f4b7f9b7f9a3bee045068` 暴露的答案提交和产品展示问题，
让“查到了什么、依据是什么、链接在哪里、答案是否真正提交成功”在一次交互中可见、可定位、
可回归。

## Requirements

- 保持 Citation Finalizer 的严格 current-run provenance、scope 和 locator 校验，不添加
  citation repair、静默删除引用、retry 或 fallback。
- 结构化来源允许模型引用当前 Tool Result 中的稳定 source identity/locator，由 Finalizer
  从可信 Tool Result hydrate 精确 `value_snapshot`；旧格式仍支持并继续严格比较显式值。
- 结构化 citation 校验失败必须带有具体 Answer Artifact 字段路径，并在 Trace 中保留该路径，
  方便下一次真实运行直接定位是哪一条引用失败。
- 已验证的 Message Source 必须在 CLI Sources/Evidence 区展示会话、作者、时间、摘录和消息中
  可信提取的 URL；Structured Source 必须展示 locator、值摘要和执行限制。
- 答案层必须展示 claim → evidence → source 的关系、criterion、sufficiency 和 limitations，
  不能只输出一段没有来源的总结。
- 不展示任何 provider reasoning 文本、hidden reasoning、provider scratchpad 或逐 token private
  chain of thought；过程展示只使用真实的 Route、Plan、Tool、Retrieval 和 Evidence facts。
- 流式答案失败时必须保持“未提交”的事实边界，不能把 provisional preview 当成完成答案；错误仍
  显式暴露并保留 Trace/日志身份。
- 对资源/仓库/Skill 类问题，模型提示必须要求在证据中存在 URL 时给出具体链接，并区分“聊天中
  被提及”和“已验证价值”，不能只返回抽象名称或无依据的推荐。
- 检索默认结果上限必须是跨 Scope、Capability、Retrieval、Provider schema 和 Evidence transport
  共享的有界值 100；不能继续在其中一层保留 20 的隐式默认，不能改成无界读取。
- 对仓库/Skill/资源的宽范围清单检索，模型应使用最大可信 limit 和零上下文窗口，使命中数与返回
  的命中消息不被邻近上下文消耗；最终答案必须优先闭合 evidence/citation JSON，再列代表性链接。

## Acceptance Criteria

- [x] 真实 Failure Case 可用 deterministic fixture 重现：结构化引用错误包含具体路径，且
  `QueryResult` 没有 validated AnswerArtifact/Conversation commit。
- [x] 结构化 source identity-only 引用可以在不复制完整 row value 的情况下通过严格 Finalizer，
  最终 Artifact 仍保存来自 Tool Result 的可信 `value_snapshot`；错误 identity 或显式错误值仍失败。
- [x] Message snapshot 能保存 bounded URL 列表；旧 Artifact JSON 无 URL 字段仍可读取，新 Artifact
  能 round-trip URL。
- [x] 成功 CLI 查询显示 Evidence、Sources、claim 绑定、sufficiency/limitations 和 URL；不读取
  SQLite 或重新执行 Query 来拼装展示。
- [x] provider reasoning（即使字段名为 summary）不进入终端；Route、Plan、Tool、Retrieval 和
  Evidence facts 仍按真实事件显示。
- [x] 失败后的 provisional answer 不产生 `query.completed`、Answer commit 或 feedback target，
  且 CLI 显示明确的未提交错误。
- [x] 资源推荐提示覆盖具体链接、观察事实/解释区分和数据时间范围说明。
- [x] 31 条真实命中回归不再被默认 20 截断；真实 provider smoke 返回 31/31 命中并完成 citation
  校验，最终答案包含具体链接和 Sources。
- [x] 原有全量测试、ruff、mypy、compileall、Trellis validation 和 `git diff --check` 通过。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
