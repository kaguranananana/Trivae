---
name: verify-trivae
description: "验证 Trivae 的群聊检索、消息上下文补读、引用来源、Web 查询 API 和 Evaluation 合同。修改这些链路或排查回归时，用既有 pytest、生产 SDK 工具与 trivae CLI 在隔离的合成数据上执行确定性验证。"
---

# 验证 Trivae

Trivae 的用户查询入口有 Web UI / HTTP API 和 `trivae chat`（交互 CLI/TUI）。它们与 Evaluation 共用 Application 查询链路。默认用现有 pytest 驱动真实 SDK 工具、查询链路和 ASGI 路由，并直接运行 Evaluation CLI。按 [功能地图](features/README.md) 核对覆盖范围。

## Launch

在仓库根目录安装锁定的开发依赖。首次安装可能下载 Python 或依赖包。

```bash
uv sync --locked --inexact --extra dev
.agents/skills/verify-trivae/verify.sh
```

脚本每次创建空的临时目录。pytest fixture 生成 QQ 导出，应用在隔离 SQLite 中初始化 schema、导入消息并按用例构建索引。以 `/api/readiness` 返回数据库 `ready` 和合成查询测试通过核验可用性。Web API 通过进程内 ASGI transport 驱动，无需启动监听端口、构建前端或登录 OAuth。语义用例使用固定向量的 embedding provider 与真实 sqlite-vec，无需安装或下载真实 embedding 模型。

## Doctor

脚本先做只读 CLI 探测。出现启动问题时，在仓库根目录单独运行同一命令。

```bash
uv run --offline --no-sync --no-env-file trivae --help
```

应退出 0 并列出 `chat`、`web`、`eval` 等子命令。它确认当前项目环境能导入 CLI。数据库和应用是否可用由后续 readiness 及查询测试核验。缺少可执行文件时检查上面的依赖安装步骤。

## Drive

- 用 [功能地图](features/README.md) 定位验证入口。默认脚本运行其中列出的检索、上下文、引用、Evaluation 和 Web API 回归。
- 主查询旅程由 `test_sdk_loop_source_handle_reply_citation_and_trace` 驱动。固定 SDK 模型输出先搜索，再用返回的 `source_id` 补读远距离回复，最后提交带引用的答案。检查最终来源绑定与持久化 Trace。
- Case 校验复用 `trivae eval cases validate`，读取 `evaluation/cases/` 顶层的 Seed Case。固定模型和固定向量只替换现有模型边界。
- 正式 Suite 和 Benchmark 使用冻结数据及 Variant。需要单独验证真实模型或真实数据时，遵循 [Evaluation 文档](../../../docs/evaluation.md) 的隔离工作库流程。默认检查不需要生产数据库、master freeze、Holdout 或 Judge。

## Evidence

`verify.sh` 打印本轮证据目录 `data/evaluation/verify-trivae/run.*/`。每条日志包含执行的命令、输出和退出码。

- `doctor.log` 保存 CLI 探测。
- `cases.log` 保存 Case 校验返回的状态与 Case identity。
- `pytest.log` 与 `pytest.xml` 保存用例状态、失败断言及退出结果。核对 Case 清单、真实查询链路的来源 ID、Trace 参数与持久化检查对应的测试结果。

报告时列出实际入口、通过或失败的用例和证据目录。Web API 回归只覆盖 ASGI 路由与流协议。模型选择、真实向量召回、答案语义质量、浏览器渲染和交互 TUI 需要各自的验证入口。

## Cleanup

脚本退出时删除本次临时目录及其中的 SQLite 文件，证据目录留存且已被 Git 忽略。确认输出中有 `Removed scratch`，临时目录已消失，并检查证据文件仍在。各次运行使用独立目录，不共享运行状态；无需停止本机已有的 Trivae 进程。

## Helpers

从仓库根目录运行 `.agents/skills/verify-trivae/verify.sh`。脚本只编排已有 CLI 和 pytest，并透传失败退出码。验证失败时先查看对应日志，再用功能地图中的测试节点复现。
