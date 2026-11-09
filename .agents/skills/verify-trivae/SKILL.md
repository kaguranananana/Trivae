---
name: verify-trivae
description: "Trivae 真实功能验收：需要用户视角、浏览器操作或真实模型工具决策证据时使用。提供隔离 Chrome→Vue→FastAPI→SDK→SQLite 的零 LLM 浏览器 E2E，以及显式付费、有限轮次的真实 Agent Smoke。普通 pytest 由 Codex 按改动选择；原固定回归脚本按需保留。"
---

# Verify Trivae：按需的真实功能验收

**职责不是替 Codex 重跑已有 pytest。** 优先从本次变更识别无法由现有单元/集成测试覆盖的用户行为，再选择下述入口。单 Agent 操作，不并行派发子 Agent；验证失败必须保留证据并报告。代码、测试和运行事实优先于 Feature Map。

## 选择入口（默认不自动运行昂贵流程）

| 任务改动 | 适当验证 | 是否真实 LLM |
| --- | --- | --- |
| 普通后端逻辑、数据库契约 | Codex 自行挑选/补充相关 pytest；必要时全量 pytest、Ruff、Mypy | 否 |
| Vue UI、浏览器状态、流式答案、来源弹窗或前后端集成 | **`verify-web.sh`**：真实 Chrome + 正式静态 Vue + FastAPI HTTP + SQLite + SDK 模型替身 | **否** |
| Prompt、工具描述、Agent 自主决策、模型兼容行为 | **`verify-agent.sh --run`**：仅在用户明确允许真实调用/成本时运行单 Case | **是** |
| 检索、答案质量的量化对照 | 复用既有 Evaluation / Benchmark / 冻结 Snapshot，不由本 Skill 重建 | 视实验而定 |
| 核心查询链路固定回归 | 原 `verify.sh`，按需选择，不代替本次改动的验收 | 否 |

新功能先明确具体可观察的验收结果，缺少对应测试就补最小断言。**固定测试全绿不代表新功能正常，浏览器 E2E 通过也不代表真实模型能自主选择工具。** 改动扩展到新用户入口时，才按需扩展功能地图或脚本；不需要每个修复都修改本 Skill。

## A. 浏览器 E2E（推荐的新增能力）

前提：Mac 装有 Google Chrome；`pnpm -C web install --frozen-lockfile`；已准备 `uv sync --locked --inexact --extra dev`。Playwright 使用 `web` 中锁定的 `playwright-core` 及本机 Chrome，不下载另一套浏览器，也不调用任何 LLM。

在仓库根目录运行：

```bash
.agents/skills/verify-trivae/verify-web.sh
```

脚本自动：创建临时 QQ 导出与独立 SQLite → 用 **真实 Trivae Application、SDK Tool、Finalizer、Trace** 启动本机 FastAPI → 构建 Vue 静态前端 → Chrome 访问真实 HTTP 服务 → 选择「回复实验」群聊、提问 → 验证带来源的回答、弹窗、源消息原文回读与持久化 Trace → 截图、记录 HTTP 及 JS 错误 → 停服务、删除临时数据库。

只替换不可控的**模型决策边界**：`ScriptedModel` 固定词法检索、补读远距离回复和带引用答案，`FixedRouter` 不调用 Router Provider。**不 mock 前端 fetch，不替换后端 API，完全不读取用户真实群聊数据。** 这是浏览器/服务/检索/引用的真实 E2E，不证明真实 LLM 自主使用工具、语义排名质量或浏览器之外的 TUI 行为。

验证断言本身的负例（预期非零退出码）：

```bash
.agents/skills/verify-trivae/verify-web.sh --negative-control
```

负例让隔离 ScriptedModel 提供无效引用，浏览器必须无法找到预期来源，测试失败。**不要让正常模式在负例中“通过”；也不要改产品逻辑来制造失败。** 运行结果保存在 `data/evaluation/verify-trivae/browser.*/`，含 `browser.log`、截图、`network-and-errors.json`、`server.log`、`build.log`。每次先报告实际命令与退出码，不从旧截图推断本次成功。

## B. 真实 Agent Smoke（严格显式、有限费用）

默认执行 `verify-agent.sh` **只输出使用说明，绝不调用 Provider**。必须有用户明确授权费用，并单独传入 API-compatible 模型的配置：

```bash
TRIVAE_VERIFY_ALLOW_SPEND=YES TRIVAE_VERIFY_API_KEY=... TRIVAE_VERIFY_BASE_URL=https://provider.example/v1 TRIVAE_VERIFY_PROVIDER=deepseek TRIVAE_VERIFY_MODEL=example-model .agents/skills/verify-trivae/verify-agent.sh --run
```

该入口只使用本脚本创建的合成群聊，强制 Standard Route，真实模型自行选择检索/补读工具，验证是否引用实际使用反馈原消息；限制 4 个模型轮次、2 个工具轮次、单轮最多 1200 输出 token，Provider SDK 重试禁用。120 秒超时。**这些只是调用量上限，不是金额上限**；输入 Token、Provider 价格按实际产生。结果只记录工具名称、引用的消息 ID、Trace ID 和状态，不记录密钥或私人语料。该 smoke 未在没有许可的情况下实跑，不得声称已验证真实 Provider。

## C. 旧有确定性回归（保留但不作为 Skill 的主要价值）

```bash
.agents/skills/verify-trivae/verify.sh
```

原脚本复用已存在的 35 个 pytest、13 个 Seed Case 格式检查、CLI 探测与清理，结果在 `data/evaluation/verify-trivae/run.*/`。它不会生成新测试，不运行完整 Benchmark 或真实 LLM。改动检索、上下文、引用、Evaluation 合同时可作为额外快速检查；不能据此声称 UI / Agent 效果正常。各功能覆盖详见 [功能地图](features/README.md)。

## 验收与证据原则

1. 先检查本次代码差异、真实入口及具体验收目标；不要只运行固定脚本便宣布完成。
2. 最低成本验证优先：现有单元/集成测试 → 需要时浏览器 E2E → 用户同意后真实模型 E2E → 实验性 Benchmark。
3. 报告哪些真实路径被操作、检查了哪些最终可见结果、运行命令/退出码/截图/Trace、哪些路径仍未验。避免把测试替身说成真实模型。
4. 完整 Browser E2E 和真实 Provider Smoke 都只使用独立的合成数据。不要启动连接真实数据的服务，不要泄漏本机 `.env`，不修改 Benchmark 主库或正式冻结 Snapshot。
5. 不为一次简单任务默认安装多 Agent 框架或触发全部验证；仅在覆盖面确实变化时更新 [功能地图](features/README.md)。
