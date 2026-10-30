# Trivae 当前状态

> 核验日期：2026-10-30。此页是当前状态摘要，不替代源码、测试和受跟踪配置。机器上的 Shell 环境与未跟踪 `.env` 可能改变实际运行值；本页不记录本机密钥或私有数据配置。

## 项目定位

Trivae 将 QQ 群聊导入、检索、Agent 调查和来源回溯接成一个本地使用的系统。产品能力和数据边界见 [README](../README.md)；当前链路见 [系统架构](architecture.md)。

## 当前实现

- **数据与检索**：支持 QQChatExporter JSON（V5 / 0.1.0 字段形态），将消息保存在 SQLite Canonical Store；FTS5 和 sqlite-vec 是派生索引。语义向量使用本地 Qwen3 Embedding。图片、文件等媒体保留结构和来源，不执行 OCR 或语音转写。
- **查询链路**：Web UI / HTTP API、CLI/TUI 和 Evaluation 通过共享 Application/QueryOrchestrator；Router 选择 Standard 或 Planned 路径，Planner 提供软指导，两者共用 Agent Runtime。Runtime 可使用词法、语义、近期消息、上下文、成员与只读 SQL 能力。Finalizer 校验来源和范围，Application 持久化会话与 Trace。各层职责和限制见 [系统架构](architecture.md)。
- **模型配置**：受跟踪默认值见 [`config/models.yaml`](../config/models.yaml)：普通查询 `gpt-plus`（ChatGPT OAuth，`gpt-6.1-sol`，medium）；Evaluation Agent `deepseek-flash`；离线 Judge `gpt-plus`。`TRIVAE_MODELS_CONFIG` 可替换注册表，普通查询可用 `TRIVAE_MODEL_ID` 选择 profile；旧直接配置 `TRIVAE_MODEL_PROVIDER` / `TRIVAE_MODEL_NAME` 仍可覆盖 profile。CLI 从 `.env` 注入未设置的变量，Shell 值优先。实际生效值以当前进程为准，完整顺序见 [配置指南](configuration.md)。
- **正式评测**：`trivae eval run` 接收 master `freeze.json`，校验冻结身份后在同卷创建隔离 APFS 工作库。Canonical 和语义索引会写 WAL/schema，不能共享 master 或其他 Application 工作库。结果与 Trace 持久化后才清理临时副本；Clone 不可用时明确失败。当前命令与生命周期见 [Evaluation 文档](evaluation.md#本地验证入口)。`clone-data` 用于需要长期保留的独立数据副本，不是正式运行入口的前置步骤。

## 当前评测证据

- **Eval v1 历史 Baseline**：2026-10-28 的 16 Case 运行中，Agent 成功 14/16，另有 `AnswerDeltaParseError` 与 `APIStatusError` 两个运行失败。14 个成功答案均完成 Judge v2.1 Review；Review 是模型辅助、未人工裁决，不能当作总体准确率或代表当前普通查询默认模型。详细事实见 [Eval v1 记录](eval-v1.md)。
- **两次运行失败排查**：2026-10-29 重放 Case 03（长任务跨会话进度）的保存正文，确认未转义引号使 JSON 在 Unicode 偏移 40 失败，标准解析器与增量解析器一致；Provider 非法输出尚未通过真实重跑验证解决。Case 14 在检索前发生两阶段 `APIStatusError`，原 HTTP 状态不可恢复。已补齐兼容 Provider 流建立前及 Router/Planner completion 的状态、请求 ID 和错误分类观测；未新增重试、放宽解析或改 Baseline。见[排查记录](EVAL_RUNTIME_FAILURES_20261029.md)。
- **当前主 Prompt**：2026-10-29 用户人工比较回答后，采纳了四行证据强度与来源范围约束。6 Case Candidate/Baseline 对照两侧各完成 6/6；模型辅助 Review 指出 Case 07/12 有局部改善、Case 10 漏掉手机远控 Codex/微信实践、Case 01 仍有范围/因果外推。用户选择采纳不等于六题实验证明总体质量提升；这些结果及取舍均保留在 [开发日志](DEVLOG.md) 与 [Evaluation 说明](evaluation.md)。
- **正式 Prompt A/B 评测（2026-10-29）**：Eval v1 全部16题、A/B各两次，共64个有效 Agent 运行与64份 Judge v2.1 Review；复用22个历史 Run 和22份 Review，新增42个有效 Agent 结果、42次 Judge，另有2次预算耗尽尝试各重跑一次并保留失败 Trace。按固定门槛，任务完成率 A/B 均为9/32（28.1%）；关键事实覆盖率52.8%→45.9%（-6.9个百分点），未验证 Candidate B 带来总体质量提升。Case 14 有局部改善，Case 10/12 有事实遗漏。完整报告及逐项覆盖审定在本机 ignored `data/evaluation/prompt-ab-eval-v1-20261029/REPORT.md`，原始 Run、Trace、Judge 与来源映射也留在该目录。
- **最近一次完整代码验证记录**：本次失败诊断修复后 1393 passed / 1 skipped（38.18s），Ruff、148 个源码文件的 Mypy 与 diff 检查通过；记录见 [运行失败排查](EVAL_RUNTIME_FAILURES_20261029.md)及[开发日志](DEVLOG.md)。该记录是代码验证，不是答案质量评测。

## Agent质量研究续记（2026-10-30，进行中）

- 已恢复Z Code的原R1数据与会话，原8脚本/11JSON保持原位未暂存；累计请求从原0/250、0/32恢复，不把旧Prompt A/B的185请求算成本轮。
- 冻结51次semantic候选池：仅修复100条容量的保留优先序，最高dense排名chunk整块丢失19→0，已知目标按调用出现8→18（+10/-0）。进一步固定同一新Envelope验证Host预算优先序，目标模型可见10→14（+4/-0）；48调用可比较，3两侧都因原控制预算不足不可投影。均不是全库召回率或答案准确率。
- R2真实4题各臂两次，Baseline8份完成、Candidate7份完成，另1份Case10因Provider未转义引号失败并保留；15份v2.1 Review正在补齐。当前不能发布总体答案收益。R6 Host后续真实验证尚未完成。
- 原64Run实际首轮模型输入64/64已有正确查询时间，否定重复注入查询时点的方案；数字区间S3、来源ID采用、辅助复核“人工一致率”和近似token系数均已校正口径。
- 本地研究分支工作，不推送、合并主分支或部署；完整记录与下一步见[研究状态](../research/agent-quality-20261029/STATE.md)。当前新增回归后的全量1398 passed/1 skipped（37.49s）、Ruff与Mypy148源码通过。

## 当前可确认的限制

- 没有广泛人工裁决的代表性质量 Benchmark，也没有穷尽全语料的 Reference；Judge Review 保持 provisional。六题 Prompt 对照和 16 Case Baseline 只支持各自的样本与条件。
- 工具结果与查询范围均受预算和分页边界限制。检索命中不保证全库穷尽；Finalizer 能验证来源身份、可访问范围和结构，但不证明自然语言结论必然被引用语义支持。
- Web 当前面向本机使用，未提供公网多用户认证或租户隔离。模型调用会把问题、上下文和相关工具结果发送到所配置的 Provider；ChatGPT OAuth 路径不自动回退到收费 API key。
- 代码库当前仅承诺已支持的 QQ 导出格式，不承诺任意聊天平台、OCR 或语音转写。
- 2026-10-23 的 Failure Audit、修复清单和前端审查是带日期的诊断/修复记录。它们记录的待办不能直接当作当前 Backlog；本次文档审计没有重新运行其中的生产问题。需要主张仍存在的 Bug 时，应以当前复现、Trace 或源码证据核验。

## 文档入口与优先级

- README：项目首页与能力概览。
- [architecture.md](architecture.md)：当前系统架构。
- [configuration.md](configuration.md)：当前模型、环境变量、索引和运行配置。
- [evaluation.md](evaluation.md)：当前评测实现、方法与质量边界。
- [DEVLOG.md](DEVLOG.md)：按日期追加的开发历史；其中“当前”和“下一步”只适用于记录时点。
- `.trellis/spec/project/`、[evaluation/README.md](../evaluation/README.md) 及日期化审计/实验文档：历史设计、旧工作流与实验材料。可追溯决策，但其中的 Stage 状态、旧命令和旧配置不构成当前实现或待办。当前开发约定以根目录 [AGENTS.md](../AGENTS.md) 为准。

下一项开发工作由新的用户目标和当前代码状态确定；这里不维护一份从旧历史记录自动推导的待办清单。
