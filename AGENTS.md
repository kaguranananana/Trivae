<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

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
