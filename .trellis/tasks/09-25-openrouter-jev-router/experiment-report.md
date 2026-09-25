# OpenRouter Jev Router experiment report

## 状态

**实现完成；真实 Provider 实验未运行；不推广。** 本报告不包含线上 accuracy、latency、availability 或 cost 数值。没有用静态/mock 测试数据冒充线上结果。

配置审查时曾意外在工具输出中暴露本地 `OPENROUTER_API_KEY`。之后首次全仓测试没有隔离默认 `shadow` 配置，现有 Application 集成测试尝试调用了 Jev；请求是否被 OpenRouter 接收或计费无法确认。受影响 key 应立即撤销并轮换；密钥值没有写入源码、测试、Trace、Evaluation artifact 或 Git，本报告也不包含其值。正式 `trivae eval router-jev` 配对实验没有运行，因此没有线上评测结果。后续测试已在 fixture 中关闭外部 Router provider，并修复 CLI/Web 在服务 event loop 内关闭 async client 的生命周期。

## 原链路与实验链路

原链路：

```text
确定性 Rule
  ├─ confidence >= 0.8 → 直接选择 standard/planned
  └─ confidence < 0.8 → 现有主模型的 strict-JSON Router completion
       └─ timeout/provider/JSON 失败 → 保留静态 Rule route 并记录 degradation
```

新增实验链路：

```text
确定性 Rule
  ├─ confidence >= 0.8 → 不调用 Provider
  └─ ambiguous
       ├─ existing_llm → 现有主模型 Router completion
       ├─ jev → OpenRouter Decisions Choice
       └─ shadow → LLM 决定唯一主 route；Jev 只写独立 shadow observation
```

`shadow` 下的 Jev route、confidence、probabilities、usage/cost、latency 和 failure code 单独进入 Trace/Evaluation。它们不改变主 route、Planner 是否执行、Answer 或 Runtime path。只有显式启用 `jev` mode 才让 Jev 作为主 Router decision provider；Provider 失败会保留静态 Rule route，并输出稳定错误码与安全的异常类型。

## Provider contract

- Router 专属环境变量：`OPENROUTER_API_KEY`、`TRIVIAE_ROUTER_JEV_ENABLED`、`TRIVIAE_ROUTER_JEV_MODEL`、`TRIVIAE_ROUTER_JEV_ENDPOINT`、`TRIVIAE_ROUTER_JEV_MODE`。
- 默认配置：`true`、`typesafe/jev-1.13`、`https://openrouter.ai/api/alpha/decisions`、`shadow`。
- 不修改 `TRIVIAE_MODEL_PROVIDER` 或 `TRIVIAE_MODEL_*`；Planner、Runtime、Answer Generation 继续使用现有配置。
- 请求使用 Alpha Decisions 的 `model/state/questions` 与 `choice` 类型；`choice` 映射至 Router route，`confidence` 与 winning probability 分开保留，`probabilities` 必须正好对应两个 Trivae Route。
- state 只投影 query、locale、prior model context 和 data snapshot，不包含 trusted scope 或 capability inventory。
- key 缺失、authentication、rate limit、timeout、network、model unavailable、provider unavailable、invalid response 均有独立稳定错误码。Trace 只保留 code 和异常类型，不保存 Provider response/error body。

## Dataset and protocol

Dataset：`evaluation/router-jev/cases-v1.json`，16 条候选诊断 Case。类别包含明确 standard/planned、单关键词误判、隐式时间调查、证据依赖、多轮 context 改变 route、recovery、aggregation boundary、隐式多阶段依赖与不需要 Planner 的比较问题。16 条 provisional hypothesis 全部 `pending_human_adjudication`；确定性 Rule gate 将 13 条送入 Provider，另 3 条由 Rule 直接决定。

`trivae eval router-jev` 对同一不可变 QueryContext 配对运行现有 LLM 与 Jev，每个 repetition 各调用一次；两路都只对 13 个 ambiguous Case 发请求。默认输出只保存 case ID/slice/provenance/adjudication、route/confidence/probabilities、provider/model、usage/cost、latency、degradation 和 aggregate metrics；不保存 query、API key、异常正文或 raw response。Cost 仅汇总 OpenRouter 实际返回的 `usage.cost`；没有 cost 字段时报告 unavailable。结果文件采用 create-only 语义。

本次本地可复核的静态事实：16 个 Case、8 个 standard / 8 个 planned provisional hypothesis、13 个 ambiguous Case、3 个 deterministic Rule Case、16 条待人工 adjudication。它们不代表模型质量或线上运行指标。

## 实际结果与 failure cases

| 项目 | 结果 |
| --- | --- |
| Formal paired OpenRouter Evaluation | **未运行**；首次全仓测试曾从既有集成用例尝试 shadow Jev 请求，服务是否接收/计费未知 |
| Existing LLM vs Jev accuracy / disagreement | 未知；不得从测试 fixture 推算 |
| p50 / p95 latency、availability、timeout/error rate | 未知 |
| OpenRouter token/cost | 未知；不以公开价格估算实际费用 |
| Promotion | `continue_shadow`；不 promote |

自动化测试覆盖缺失 key、无效 Choice、authentication、rate limit、timeout、network、404 model unavailable、502/503 provider unavailable、稳定错误类型 Trace projection、shadow 成功/失败隔离、Rule gate 与 create-only artifact。所有 provider integration tests 使用本地 mock transport，没有发出网络请求。

本地验证结果：全仓 `pytest` 618 项通过；Mypy 对 114 个源码文件无错误；本次涉及的 Python 文件 Ruff 通过；`git diff --check` 与 Trellis task validation 通过。全仓 `ruff check .` 曾报告 62 项既有问题，位置均在本任务范围外的 `.codex/hooks`、`.trellis/scripts` 与归档任务脚本；本任务改动文件单独检查通过。

## 推广建议

保持默认 `shadow`。即使真实配对 run 显示较高 route agreement/accuracy，也不能单独证明 Router 替换改善了 Planner utility。下一阶段需先完成人工 adjudication，扩充代表性数据，并通过同 Case forced-standard / forced-planned 测量 Planner utility；随后审查 planned→standard 错误、真实延迟、可用性与 cost，再决定是否切换到 `jev`。

轮换凭据并确认后运行：

```bash
uv run trivae eval --env-file .env router-jev \
  --cases evaluation/router-jev/cases-v1.json \
  --repeat 3 \
  --output data/evaluation/router-jev/after-key-rotation.json
```

该命令会对 13 个 ambiguous Case 各运行 3 次配对比较。输出目录受 `.gitignore` 排除；不要复制 key 到命令行、源码、测试或产物。
