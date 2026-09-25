# OpenRouter Jev Router experiment report

## 1. 实验结论

**真实配对实验与 16 Case 人工裁决均已完成；生产 Router 继续保持 `shadow`。** 用户按 Stage 1.5 Router ADR 的 Planner 增益标准裁决，16/16 个原 route hypothesis 均成立（8 standard / 8 planned），没有改标签。以下是这组人工裁决诊断集上的观测结果；它们不证明结果可泛化，也不能单独证明 Jev 带来 Planner utility 或支持生产切换。

- 日期：2026-09-25
- Jev configured：`typesafe/jev-1.13`；Provider resolved model：`typesafe/jev-1.13-20260917`，OpenRouter Decisions API
- Existing LLM：`deepseek/deepseek-flash`
- Artifact：`data/evaluation/router-jev/paired-v1-2026-09-25.json`（本地文件，受 `.gitignore` 排除）
- 初次运行时，case manifest 和原始 artifact 按当时状态记录为 provisional；人工裁决单独保存在 `evaluation/router-jev/adjudication-v1.json`。原始输入和运行 artifact 保持不变。由于 16 个标签全部确认且无一变更，基于最终标签的指标计数与原 provisional 计数相同。
- Artifact runner 字段为 `continue_shadow`；运行配置继续保持 `shadow`。人工裁决完成不代表生产升级。

## 2. Execution integrity

| 检查项 | 结果 |
| --- | ---: |
| 唯一 Case | 16 |
| 最终人工裁决标签 | standard 8 / planned 8；16/16 原假设确认，0 项变更 |
| Repetition | 3 |
| Artifact decision projection | 48 条 |
| Deterministic Rule Case | 3（每路 9 条投影，不调用 Provider） |
| Ambiguous Case | 13 |
| Existing LLM Provider 调用 | 39 次，39 成功 |
| Jev Provider 调用 | 39 次，39 成功 |
| Deterministic Rule 意外 Provider 调用 | 0 |
| Create-only | 成功；运行前目标文件不存在，写入后保留独立文件 |
| Git 忽略 | 是；artifact 没有进入源码改动 |

最终逐 Case 裁决与理由见 `evaluation/router-jev/adjudication-v1.json`。裁决只判断请求是否值得在 Agent Runtime 前额外调用 Planner，不以时间跨度、数据量、Tool Call 数量或“分析/总结/比较”等词作为单独信号。

两种 Provider 都只对 13 个 ambiguous Case 每轮调用一次，共 78 次真实决策请求。Runner 固定每个 ambiguous entry 配对调用两个 provider；adapter 的 SDK retries 为 0。3 个 deterministic case 始终由相同 Rule 决定，artifact 中两路来源均为 `rule`。

Privacy 检查：artifact 中没有 query 或 prior context 文本；没有 API-key 字段或当前 `.env` key 值；没有 request/response body、raw Provider response 或 error body 字段。Artifact 只保留 ID、provenance、route、confidence、probabilities、usage/cost、latency 和 degradation projection。本轮命令先移除进程继承的 OpenRouter/Router 专属变量，再由 `--env-file .env` 加载；脱敏检查确认 Router key 已配置、Jev model/endpoint/mode 正确，且主模型仍为 DeepSeek。没有输出或写入 key。

> 历史说明：实现阶段的旧记录曾报告本地 key 意外出现在早先工具输出中，并建议轮换。本次按用户当前明确指示使用现有 `.env` key、未轮换；本次运行没有再次输出 key，artifact 扫描也确认其不在产物中。

## 3. Provider availability

| Provider | 成功 / 尝试 | 失败 | Timeout | Authentication | Rate limit | Network | Model unavailable | Provider unavailable | Invalid response | 其他 degradation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Existing LLM | 39/39 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Jev | 39/39 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

本次观测到的 availability 均为 100%。这是这 39 次/Provider 的一次短实验记录，不代表长期 SLA。

## 4. Router decision comparison

- 全部 48 个投影（包含 9 个 deterministic Rule 投影）：一致 42/48，agreement **87.5%**。
- Ambiguous Provider decisions：一致 33/39，agreement **84.6%**；分歧 6 次，集中在两个 Case，且方向全部是 Existing LLM 选 `planned_execution`、Jev 选 `standard_execution`。

| Case | Repeat | Adjudicated expected | Existing LLM route / confidence | Jev route / confidence | Jev probabilities（standard / planned） |
| --- | ---: | --- | --- | --- | --- |
| RJV-008 | 1 | standard | planned / 0.78 | standard / 0.79 | 0.89 / 0.11 |
| RJV-008 | 2 | standard | planned / 0.85 | standard / 0.78 | 0.89 / 0.11 |
| RJV-008 | 3 | standard | planned / 0.86 | standard / 0.80 | 0.90 / 0.10 |
| RJV-013 | 1 | standard | planned / 0.80 | standard / 0.99 | 0.99 / 0.01 |
| RJV-013 | 2 | standard | planned / 0.78 | standard / 0.99 | 0.99 / 0.01 |
| RJV-013 | 3 | standard | planned / 0.82 | standard / 0.99 | 0.99 / 0.01 |

没有出现 Jev 选 planned、Existing LLM 选 standard 的相反分歧。

## 5. Human-adjudicated route metrics

以下是按最终人工裁决标签计算的诊断集观测指标。矩阵以 adjudicated route 为行、predicted route 为列，计数包含 3 次 repetition。

### Existing LLM

- All 16 Case projections：39/48 = **81.25%** adjudicated-label accuracy；去重 Case 为 13/16。
- 13 ambiguous Cases：30/39 = **76.92%**；去重为 10/13。
- Confusion matrix：

| Expected \ Predicted | standard | planned |
| --- | ---: | ---: |
| standard | 15 | 9 |
| planned | 0 | 24 |

- 全部投影：standard precision/recall = **1.00 / 0.625**；planned precision/recall = **0.7273 / 1.00**。
- Ambiguous-only：standard precision/recall = **1.00 / 0.5714**；planned precision/recall = **0.6667 / 1.00**。
- `standard_execution → planned_execution`：9 次（RJV-004、RJV-008、RJV-013 各 3 次）。
- `planned_execution → standard_execution`：0/24。

### Jev

- All 16 Case projections：45/48 = **93.75%** adjudicated-label accuracy；去重 Case 为 15/16。
- 13 ambiguous Cases：36/39 = **92.31%**；去重为 12/13。
- Confusion matrix：

| Expected \ Predicted | standard | planned |
| --- | ---: | ---: |
| standard | 21 | 3 |
| planned | 0 | 24 |

- 全部投影：standard precision/recall = **1.00 / 0.875**；planned precision/recall = **0.8889 / 1.00**。
- Ambiguous-only：standard precision/recall = **1.00 / 0.8571**；planned precision/recall = **0.8571 / 1.00**。
- `standard_execution → planned_execution`：3 次，均为 RJV-004。
- `planned_execution → standard_execution`：0/24。

以上 48 条投影包含重复观测和 deterministic Rule 输出；唯一 Case 数为 16。它们是人工裁决后的诊断集结果，不是代表性生产 benchmark，也不能证明跨分布泛化或 Planner utility。

## 6. Repeat stability

两路均为 **0/16 route-instability Cases**：每个 Case 的 run1/run2/run3 route 完全相同。RJV-004 两路都稳定地偏离最终 standard 标签，属于稳定的过度路由，不是重复间抖动。部分 confidence 数值有变化，但 route 没有变化。

## 7. Latency

指标口径是 ambiguous Case 的本地 monotonic `primary route call` latency，不是完整 Query/Runtime latency；p50/p95 使用 nearest-rank。

| Provider | Mean (ms) | Median / p50 (ms) | p95 (ms) | Min (ms) | Max (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing LLM | 2164.128 | 1841.732 | 4333.200 | 1104.972 | 6941.998 |
| Jev | 278.893 | 254.564 | 512.359 | 208.622 | 628.876 |

Jev / Existing LLM latency：mean **0.1289×**（低约 **87.1%**），p50 **0.1382×**，p95 **0.1182×**。这是本次实测值，不以公开延迟代替。

## 8. Usage / Cost

只汇总 Provider 实际响应字段；未用公开价格估算。

| Provider | Input tokens | Output tokens | Total tokens | Actual cost | Mean cost / decision |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing LLM | 7,029 | 13,850 | 20,879 | unavailable | unavailable |
| Jev | 17,781 | 1,446 | 19,227（input + output；API 未单独给 total_tokens） | 0.000746802 USD | 0.000019148769 USD |

Existing LLM 的实际 cost 没有可比较的 Provider 返回字段，因此为 unavailable。Jev cost 只来自这 39 次 OpenRouter `usage.cost`。

## 9. Confidence

`confidence` 与 `probabilities` 中 winning-option probability 是两个不同字段，未互相替代。

| Provider | Confidence observations | Mean | Range | Adjudicated-correct mean | Adjudicated-error mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing LLM | 39 | 0.8872 | 0.78–0.96 | 0.9050（30 次，范围 0.78–0.96） | 0.8278（9 次，范围 0.78–0.88） |
| Jev | 39 | 0.7538 | 0.21–0.99 | 0.7953（36 次，范围 0.32–0.99） | 0.2567（3 次，范围 0.21–0.28） |

- Existing LLM 有 7 次 adjudicated error 的 confidence ≥ 0.80：RJV-004 三次、RJV-008 的 repeats 2/3、RJV-013 的 repeat 1/3。没有 confidence < 0.50 的 adjudicated-correct observation。
- Jev 没有 confidence ≥ 0.80 的 adjudicated error。6 次 adjudicated-correct Jev decision 的 confidence < 0.50，来自 RJV-011（0.42/0.49/0.48）和 RJV-014（0.37/0.32/0.34）。这些描述不构成 calibration 结论。
- RJV-004 中 Jev 选择 planned 的 winning probability 是 0.60–0.64，但 `confidence` 只有 0.21–0.28；这两个字段不能混读成同一个概率。

## 10. Failure case analysis

本次没有 Provider failure、route instability 或 deterministic Rule 越界调用。相对最终人工标签，观察到的 route errors 如下：

| Case | Observed result | 更可能的归因 | 下一步 |
| --- | --- | --- | --- |
| RJV-004 | LLM 与 Jev 三轮都选 planned；最终标签为 standard。LLM confidence 0.82/0.86/0.88；Jev confidence 0.28/0.28/0.21，planned probability 0.64/0.64/0.60。 | 人工裁决确认这里只要求按长时间范围归纳趋势，没有 turning point、原因链或依赖前序结果的后续调查。两路将“过去半年/趋势”本身当成规划信号，构成一致的 over-route。 | 保留 standard 标签。若请求明确要求找出态度转变的关键时间点并解释哪些使用反馈促成转变，才有充分的 planned 信号。 |
| RJV-008 | Existing LLM 三轮均选 planned；Jev 三轮均选 standard；最终标签为 standard。 | Prior context 已限定为概括一条给定理由，并明确不调查其他讨论。Jev 读取上下文后选 standard，Existing LLM 将 follow-up 中的“后来/为什么”过度解释为调查依赖。 | 与上下文要求完整决策追踪的 RJV-007 对照，说明 prior context 会改变 Planner 是否有价值。标签维持 standard。 |
| RJV-013 | Existing LLM 三轮均选 planned；Jev 三轮均选 standard；最终标签为 standard。 | 请求只解释一条消息中的一个名词；“分析”是措辞，不构成 Planning signal。Existing LLM 出现词面 over-trigger，Jev 三轮均符合裁决。 | 标签维持 standard；不据此增加关键词规则。 |

Existing LLM 的 9 个错误观测来自上述三个 standard Case；Jev 的 3 个错误观测全部来自 RJV-004。没有证据支持本轮失败属于网络、服务、模型不可用或无效响应。

## 11. Planned → standard 风险

本次 8 个 adjudicated planned Case 共 24 次重复中，Existing LLM 与 Jev 都是 **0 次 `planned_execution → standard_execution`**。本诊断集没有观察到漏掉 Planner 的方向性错误；16 个 Case 的规模仍不足以声称该风险已消除，需在更多代表性样本中复测。

## 12. 当前证据支持与不支持

**支持：** 16/16 route labels 已按 Stage 1.5 Planner 增益标准人工裁决，原假设全部确认；在这组诊断集上 Existing LLM 为 39/48，Jev 为 45/48，Jev 在 RJV-008/RJV-013 符合最终标签；Decisions API 在本次 39 次调用中均返回可用结果；Jev route 三轮稳定，measured route-call latency 低于本次 Existing LLM，且 OpenRouter 返回了真实 token 和 cost。

**不支持：** 这组小型诊断集足以证明 Jev 普遍优于 Existing LLM、confidence 已校准、结果能泛化到生产流量、Jev 提升 Planner utility，或 `planned_execution → standard_execution` 风险不存在。没有做 forced-path Planner utility 实验。

## 13. Rollout 建议

**人工裁决已完成；下一步评估 Planner utility。** 使用 forced-standard / forced-planned 对照，判断额外 Planner 调用是否改善最终结果，再结合更大且具代表性的已裁决样本评估 Router。生产 Router 继续保持 `shadow`；仅凭这组路由分类结果，不切换到 `jev`。

## 执行入口修复与验证

原定命令最初无法启动：`pyproject.toml` 声明了 `project.scripts.trivae` 和 `src/` 布局，但未声明 build system 或启用 uv package，`uv` 因而跳过本地项目安装及 CLI entry point。已在 `pyproject.toml` 加入 `[tool.uv] package = true`，`uv.lock` 相应记录本地项目为 editable source；只修复命令打包/集成，不改变 Router 或主模型行为。之后真实执行了 `uv run trivae --help`，并运行 `uv run --extra dev pytest tests/test_cli.py -q`：**28 passed**。首次 uv 同步时，uv 自动删除并重建了本地 `.venv`，随后从 lockfile 同步并安装测试 extra。

实现阶段的既有验证记录为全仓 `pytest` 618 项通过、Mypy 对 114 个源码文件无错误、任务涉及的 Python 文件 Ruff 通过，且 Trellis task validation 通过。全仓 Ruff 当时发现 62 项既有问题，位于本任务范围外。本轮针对新增 CLI packaging 修复重新运行了 28 项 CLI 测试和真实 CLI 入口。

这次发现的可复用约定已补入 `.trellis/spec/project/workflow.md`；本 ADR 与本报告已更新为真实运行结果。该细节属于 CLI packaging contract，无需扩展为新的跨层 API spec。
