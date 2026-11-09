# Trivae: lightweight development knowledge

Trellis historical documents are a knowledge archive, not mandatory coding workflow. Choose implementation, planning, delegation and validation appropriate to the task. Do not automatically create Trellis tasks, require PRDs or separate approval turns, enforce Phase ordering, or dispatch fixed Trellis subagents.

## 以源码理解当前实现

- 解释当前代码、架构、设计或调用链，必须核对当前分支的相关源码和测试；说明关键文件、类或函数及实际调用关系。默认值查源码和受跟踪配置，生效值还要考虑 Shell 与本机 `.env`。README 链接到现行架构、配置、评测和状态入口。
- 源码说明实际实现，测试和运行结果只证明各自覆盖的行为。文档或注释与实现不一致时，指出差异，再结合需求、测试和运行证据判断哪一方需要修正。设计文档、ADR、DEVLOG 和 Trellis 任务、Spec、Journal 按需查阅，用于解释当时的意图和结果；旧 Stage、默认值和待办不代表现状。
- 优先用命名、类型、数据结构和测试表达意图。注释保留必要的业务约束、非显而易见的原因和权衡，避免复述代码。

## Handoff and memory across agents

- For meaningful work or agent switching, read docs/PROJECT_STATUS.md first, then recent docs/DEVLOG.md entries as needed.
- After substantive implementation, debugging or evaluation, append a concise factual devlog entry with actual validation results and next steps. Update the status page when its summary changes; update the relevant existing guide only when its contract or instructions change.
- No records for casual discussion or trivial edits. Run checks commensurate with the change, without constraining the agent to Trellis's old process.

## 任务完成后自动提交与推送

- 每次任务完成且相关验证通过后，自动提交本任务的改动并推送到当前分支对应的远端；无需再次询问用户是否 commit / push。此规则也适用于未创建 Trellis task 的小任务。
- 用户已长期授权上述操作；若某次任务明确要求暂不提交或暂不推送，以该次要求为准。
- 只暂存本任务负责的改动；保留其他任务或用户已有的未提交改动，禁止直接用 `git add .` 混入无关工作。没有新改动时不创建空提交。
- 工作提交在前，Trellis 归档与 journal 提交在后；完成所有收尾提交后统一推送。提交信息沿用仓库既有风格。
- 已配置 upstream 时执行 `git push`；未配置时，使用已确认的远端为当前分支设置 upstream。禁止 amend 或 force push。
- 验证、提交或推送失败时显式报告具体错误与已完成的步骤；优先定位根因，不得把“已提交但未推送”报告为全部完成。

## 面试文档目录约定

- 所有项目导学、项目面经、面试题库、STAR 口播、简历事实摘要和 Claim 核验材料统一存放在根目录的 `interview-docs/`。
- 新增、删除或重命名面试文档时，同步更新 `interview-docs/README.md` 的文档索引。

## 评测数据库生命周期

- 正式 Suite 评测使用 `trivae eval run --record-dir ... --freeze-manifest <master>/freeze.json`。该入口校验冻结身份后，为每次运行创建独立 APFS 写时复制工作库；不要先用 SQLite backup 生成长期工作副本再运行。
- `create_application` 初始化会写 Canonical WAL/schema、semantic WAL/schema、Conversation、Trace 和 Evaluation 表。评测不能共享 master 或另一个实验的工作库；Application 关闭且 Run、Result、Trace 和实验清单已持久化后才能清理工作库。
- 手写实验脚本需要 Application 时，复用 `trivae.evaluation.workspace.EvaluationWorkspace` 并在结果持久化后调用 `mark_results_persisted()`。Clone 不可用时明确失败，不退回普通整库复制。
- Run 配置、结果、Trace、评分及 freeze/snapshot/index 身份写入实验记录目录或其独立 Evaluation DB。调试时可显式传 `--keep-workspace`；过期副本由 `trivae eval cleanup-workspaces --manifest <master>/freeze.json` 回收。不得清理 master freeze、线上库或历史结果。
