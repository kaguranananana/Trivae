# Trivae 当前状态

> 核验日期：2026-11-22。这里记录当前能力、验证范围和恢复入口。配置实际生效值取决于当前进程。

## 当前能力

- **数据与查询**：支持 QQChatExporter JSON（V5 / 0.1.0），SQLite 保存规范化消息，FTS5 和 sqlite-vec 提供检索。Web、CLI/TUI 与评测共用查询链路，支持多轮会话、工具调用、来源回读、可观测 JSON 引号容错（[json_repair.py](../src/trivae/query/json_repair.py)）与 Trace。调用链见[系统架构](architecture.md)，模型和预算见[配置指南](configuration.md)。
- **本机自动化**：支持[定时导入](qce-auto-import.md)与[邮件晚报](daily-digest.md)。最近有记录的恢复验证为 [2026-11-05 补采与重发](DEVLOG.md#2026-11-05--补全-11-04-群聊数据与晚报)：核对了 QCE 可查消息的入库覆盖，两个索引更新完成，SMTP 接受重发。该记录不代表当前调度在线或收件箱已收到。
- **正式评测**：Runner 复用应用查询；Suite 在独立 APFS 工作库中运行，结果和 Trace 持久化后清理工作库。当前 864k 冻结快照上保留 `eval@v1`（16 题）与 `eval@v2`（24 题）两套正式题集，命令与生命周期见[评测指南](evaluation.md#本地验证入口)。

## 最近验证与限制

- **2026-11-22 后端回归与 `eval@v2` 端到端闭环 A/B**：新增可观测未转义 JSON 引号修复后，在 864,615 条冻结快照上完成 24×2 同条件对照（回滚 R2+R6+无引号修复 vs 当前 `main`）及 45 份盲评 Judge v2.1：交付率 `22/24→23/24`（`cap1-07` 实测拦截修复 4 处未转义引号），全量任务满足度 ≥ 3 `79.2%→87.5%`，严格配对（`n=21`）中等缺陷 `49→39`（-20.4%），但生成层 `unsupported_assertion` 仍持平（`20→20`）。同日落地三正交维度离线 Judge [`eval-rubric-v3`](eval-rubric-v3.md)（`task_satisfaction` / `evidence_grounding` / `epistemic_calibration`、输入富化与去重缩容 -45.8%、分级 `adjudication_priority`、换位盲比 `eval-pairwise-v1`），干净 Python 3.12 环境全量后端回归 **1425 passed / 1 skipped**，Ruff 与 Mypy（149 文件）通过；对已保存答案完成部分断点可续跑的离线重评（`29/45` v3 + `17/21` pairwise，因 OAuth 额度上限干净暂停）。全部 Judge 评审均为 provisional，未人工全量审定；详见[端到端闭环日志](DEVLOG.md#2026-11-22--json-引号容错与-evalv2-24-题端到端闭环-ab)、[Judge v3 日志](DEVLOG.md#2026-11-22--离线-judge-升级至三正交维度-eval-rubric-v3输入富化与换位盲比)与[面试闭环报告](../interview-docs/Evaluation端到端闭环对照-20261122.md)。
- **2026-11-09 验证入口**：[verify-trivae](../.agents/skills/verify-trivae/SKILL.md) 的 Chrome → Vue → FastAPI → SDK → SQLite 正向场景通过，伪造引用负例按预期失败。该浏览器验证固定模型决策；同日 80 项前端测试、35 项固定回归与 13 个 Seed Case 合同通过。真实模型 Smoke 入口尚未实跑。见[验证记录](DEVLOG.md#2026-11-09--将-verification-skill-改为真实功能验收)。
- **答案质量**：检索受查询范围、分页和预算限制。引用校验可以验证来源身份与范围，语义支持度仍需评审。缺少广泛人工裁决的代表性 Benchmark；[Eval v1](eval-v1.md)、[Prompt A/B](DEVLOG.md#2026-10-29--eval-v1-prompt-ab-正式量化评测) 与 [eval@v2 闭环 A/B](DEVLOG.md#2026-11-22--json-引号容错与-evalv2-24-题端到端闭环-ab)只支持各自实验条件下的结论。
- **部署与输入**：Web 面向本机使用，未提供公网多用户认证或租户隔离。模型调用会把相关输入发给配置的 Provider。媒体保留结构和来源，当前未做 OCR 或语音转写。

恢复上下文时，从 [README](../README.md) 找现行操作入口，按需查 [DEVLOG](DEVLOG.md) 或 [Trellis 历史索引](../.trellis/spec/project/index.md)。Runtime 失败排查和预算研究分别见 [Eval v1 失败记录](EVAL_RUNTIME_FAILURES_20261029.md) 与 [预算扩容实验记录](DEVLOG.md#2026-10-31独立预算扩容实验与默认值核查)；历史待办不自动进入当前计划。
