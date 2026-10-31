# Trivae 当前状态

> 核验日期：2026-10-31。此页是当前状态摘要，不替代源码、测试和受跟踪配置。机器上的 Shell 环境与未跟踪 `.env` 可能改变实际运行值；本页不记录本机密钥或私有数据配置。

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

## R2 / R6 产品修复（2026-10-31）

- 从远端研究分支选择性提取 `e5f53ac4` / `642896de` 的两处产品改动和容量回归测试，未合并整个研究分支。Semantic 展开按完整字面命中、其余检索排名保留核心；Host 延续该优先级，消息与来源仍按原时间顺序展示。Scope、来源与预算错误语义不变。
- 固定 51 个历史 ANN 池的研究结果：rank1 整块丢失 19→0，已知目标出现 8→18；同一修复后 Envelope 的 Host 对照目标可见 10→14。这是证据保留结果，不是答案准确率。4 题小样本没有证明总体答案质量提升。完整原始材料保留在 `research/agent-quality-20261029` 分支，不将 R7 联合检索 Prompt 合入。
- 主分支未引入研究脚本、请求账本、重复研究日志和私有输出；本地原件保留并忽略。未改变产品 Prompt、向量召回、模型配置、消息数量或 Token 默认预算。
- 本次完整验证：1395 passed / 1 skipped（39.81s），相关回归 31 passed，Ruff 和 Mypy（148 源码文件）通过。新增断言同时核验 Host 来源顺序和 canonical record 不变。预算扩容另开独立研究分支，不随修复发布。

## 当前可确认的限制

- **预算扩容研究（2026-10-31）**：独立分支固定51个ANN池，消息100/200/500的已知目标出现18/19/19；固定100条Envelope的条件Host重放，32/64/128K目标可见14/18/18，投影错误3/0/0。三题固定历史工具前缀后真实DeepSeek合成，32/64K均正式交付2/3：32K有控制准入失败，64K有Provider非法JSON失败。5次真实合成315202 Token；小样本没有证明总体答案质量提升。产品消息100与Token预算默认不变；历史32K不是当前统一默认，本机显式200K覆盖也未编辑。完整输入、失败和账本留在独立分支及本机ignored数据；见[预算实验报告](https://github.com/kaguranananana/Trivae/blob/codex/budget-capacity-20261031/research/budget-capacity-20261031/REPORT.md)。Judge仅1份完成，网络失败与6项Codex原文核验均明列，未冒充独立人工裁决。研究分支验证1402 passed / 1 skipped、Ruff、Mypy148通过。

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
