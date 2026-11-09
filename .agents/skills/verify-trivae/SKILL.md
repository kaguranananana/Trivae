---
name: verify-trivae
description: "验证 Trivae 的群聊检索、消息上下文补读、引用来源、Web 查询 API 和 Evaluation 合同。修改这些链路或排查回归时，用既有 pytest、生产 SDK 工具与 trivae CLI 在隔离的合成数据上执行确定性验证。"
---

# 验证 Trivae

Trivae 的用户查询入口有 Web UI / HTTP API 和 `trivae chat`（交互 CLI/TUI）。它们与 Evaluation 共用 Application 查询链路。默认用现有 pytest 驱动真实 SDK 工具、查询链路和 ASGI 路由，并直接运行 Evaluation CLI。按 [功能地图](features/README.md) 核对覆盖范围。

## 日常开发验证

**先验收本次改动，再跑固定回归。** 由单个 Agent 按以下顺序执行，优先使用合成数据和无需模型调用的检查。

1. 先看实际代码与配置差异，确定受影响的用户入口、预期行为和需要守住的边界，再找到对应的测试与断言。
2. 优先复用现有测试。缺少能证明本次行为的断言时，补充最小的针对性测试并实际运行。按验收目标选择能提供证据的最低成本层级。
3. 完成功能验收后运行 `verify.sh`，检查已有核心链路。固定检查通过只证明已覆盖的行为没有回归。新功能的完成结论须有本次改动的验收证据。

新增功能领域或用户入口时，按需把值得重复执行的验证旅程加入 Feature Map。普通改动在既有测试中完成验收即可。

## Launch

在仓库根目录安装锁定的开发依赖。首次安装可能下载 Python 或依赖包。

```bash
uv sync --locked --inexact --extra dev
```

脚本每次创建空的临时目录。pytest fixture 生成 QQ 导出，应用在隔离 SQLite 中初始化 schema、导入消息并按用例构建索引。以 `/api/readiness` 返回数据库 `ready` 和合成查询测试通过核验可用性。Web API 通过进程内 ASGI transport 驱动，无需启动监听端口、构建前端或登录 OAuth。语义用例使用固定向量的 embedding provider 与真实 sqlite-vec，无需安装或下载真实 embedding 模型。

## Doctor

脚本先做只读 CLI 探测。出现启动问题时，在仓库根目录单独运行同一命令。

```bash
uv run --offline --no-sync --no-env-file trivae --help
```

应退出 0 并列出 `chat`、`web`、`eval` 等子命令。它确认当前项目环境能导入 CLI。数据库和应用是否可用由后续 readiness 及查询测试核验。缺少可执行文件时检查上面的依赖安装步骤。

## Drive

验收本次改动后，在仓库根目录执行核心回归。

```bash
.agents/skills/verify-trivae/verify.sh
```

- 用 [功能地图](features/README.md) 定位已有验证入口。脚本运行其中列出的检索、上下文、引用、Evaluation 和 Web API 回归。
- 主查询旅程由 `test_sdk_loop_source_handle_reply_citation_and_trace` 驱动。固定 SDK 模型输出先搜索，再用返回的 `source_id` 补读远距离回复，最后提交带引用的答案。检查最终来源绑定与持久化 Trace。
- Case 校验复用 `trivae eval cases validate`，读取 `evaluation/cases/` 顶层的 Seed Case，验证 Case 格式与合同。

### 验证边界

| 层级 | 能支持的结论 |
| --- | --- |
| 单元测试 | 给定输入下的局部逻辑、边界和错误语义。 |
| 集成测试 | 实际组件之间的行为，例如 SQLite 索引与原文回查，或 ASGI 路由、流协议和会话持久化。固定向量验证索引链路，浏览器和 TUI 交互各需单独验收。 |
| 固定 SDK 查询链路 | 用脚本模型给定工具调用和答案，验证生产 SDK、工具、Finalizer 与 Trace 的连接。模型自主选工具、真实语义排序与答案质量仍需独立证据。 |
| 真实模型 E2E | 验证指定模型、配置、入口和样本上的完整运行，包含真实工具选择与答案。仅在验收依赖真实模型行为时选少量目标用例，结论限于实跑样本。 |
| Benchmark | 在固定 Case、数据快照、Variant 和评审条件下做可比较的质量或性能评估。仅在需要这类对照时执行。 |

涉及真实数据的正式 Suite 与 Benchmark 按 [Evaluation 文档](../../../docs/evaluation.md) 使用隔离工作库。

## Evidence

`verify.sh` 打印本轮证据目录 `data/evaluation/verify-trivae/run.*/`。每条日志包含执行的命令、输出和退出码。

- `doctor.log` 保存 CLI 探测。
- `cases.log` 保存 Case 校验返回的状态与 Case identity。
- `pytest.log` 与 `pytest.xml` 保存用例状态、失败断言及退出结果。核对 Case 清单、真实查询链路的来源 ID、Trace 参数与持久化检查对应的测试结果。

报告时分开列出本次改动的验收证据、固定回归结果和证据目录。若有未覆盖的验收项，明确列出缺口。

## Cleanup

脚本退出时删除本次临时目录及其中的 SQLite 文件，证据目录留存且已被 Git 忽略。确认输出中有 `Removed scratch`，临时目录已消失，并检查证据文件仍在。各次运行使用独立目录，不共享运行状态；无需停止本机已有的 Trivae 进程。

## Helpers

从仓库根目录运行 `.agents/skills/verify-trivae/verify.sh`。脚本只编排已有 CLI 和 pytest，并透传失败退出码。验证失败时先查看对应日志，再用功能地图中的测试节点复现。
