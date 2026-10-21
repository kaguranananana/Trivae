# Trivae: lightweight development knowledge

Trellis historical documents are a knowledge archive, not mandatory coding workflow. Choose implementation, planning, delegation and validation appropriate to the task. Do not automatically create Trellis tasks, require PRDs or separate approval turns, enforce Phase ordering, or dispatch fixed Trellis subagents.

## Handoff and memory across agents

- For meaningful work or agent switching, read docs/PROJECT_STATUS.md first, then recent docs/DEVLOG.md entries as needed.
- Historical work: .trellis/workspace/anontokyo/ (journals), .trellis/tasks/ (tasks and experiments), .trellis/spec/ (contracts, architecture decisions and problem records). Read only relevant documents on demand.
- Code, tests and Git are authoritative when progress notes have become stale.
- After substantive implementation, debugging or evaluation, update current status and append a concise factual devlog entry, including actual validation results and next steps.
- Only persist genuinely durable decisions or failure patterns in .trellis/spec/. No prescribed document sections for normal coding.
- No records for casual discussion or trivial edits. Run checks commensurate with the change, without constraining the agent to Trellis's old process.

## 任务完成后自动提交与推送

- 每次任务完成且相关验证通过后，自动提交本任务的改动并推送到当前分支对应的远端；无需再次询问用户是否 commit / push。此规则也适用于未创建 Trellis task 的小任务。
- 用户已长期授权上述操作；若某次任务明确要求暂不提交或暂不推送，以该次要求为准。
- 只暂存本任务负责的改动；保留其他任务或用户已有的未提交改动，禁止直接用 `git add .` 混入无关工作。没有新改动时不创建空提交。
- 工作提交在前，Trellis 归档与 journal 提交在后；完成所有收尾提交后统一推送。提交信息沿用仓库既有风格。
- 已配置 upstream 时执行 `git push`；未配置时，使用已确认的远端为当前分支设置 upstream。禁止 amend 或 force push。
- 验证、提交或推送失败时显式报告具体错误与已完成的步骤；优先定位根因，不得把“已提交但未推送”报告为全部完成。
- 本约定覆盖 Trellis 模板中“提交前再次确认”与“禁止推送”的默认规则；流程细节见 `.trellis/spec/project/workflow.md`。

## 面试文档目录约定

- 所有项目导学、项目面经、面试题库、STAR 口播、简历事实摘要和 Claim 核验材料统一存放在根目录的 `interview-docs/`。
- 新增、删除或重命名面试文档时，同步更新 `interview-docs/README.md` 的文档索引。
