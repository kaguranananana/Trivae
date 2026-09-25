# OpenRouter Jev Router experiment report

## 1. 实验结论

**真实配对实验已完成；下一步建议 `ready_for_human_adjudication`；生产 Router 仍保持 `shadow`。** 本报告中的质量比较全部是 `provisional diagnostic metrics`：16 个 route hypothesis 仍为 `pending_human_adjudication`，不能称为 ground-truth accuracy，也不能据此切换生产 Router。

- 日期：2026-09-25
- Jev configured：`typesafe/jev-1.13`；Provider resolved model：`typesafe/jev-1.13-20260917`，OpenRouter Decisions API
- Existing LLM：`deepseek/deepseek-flash`
- Artifact：`data/evaluation/router-jev/paired-v1-2026-09-25.json`（本地文件，受 `.gitignore` 排除）
- Artifact 的 runner 字段仍给出 `continue_shadow`；本报告建议推进到人工 adjudication，意为整理样本交由人裁决，不表示生产升级。运行配置继续保持 `shadow`。

## 2. Execution integrity

| 检查项 | 结果 |
| --- | ---: |
| 唯一 Case | 16 |
| Provisional hypothesis 分布 | standard 8 / planned 8 |
| Repetition | 3 |
| Artifact decision projection | 48 条 |
| Deterministic Rule Case | 3（每路 9 条投影，不调用 Provider） |
| Ambiguous Case | 13 |
| Existing LLM Provider 调用 | 39 次，39 成功 |
| Jev Provider 调用 | 39 次，39 成功 |
| Deterministic Rule 意外 Provider 调用 | 0 |
| Create-only | 成功；运行前目标文件不存在，写入后保留独立文件 |
| Git 忽略 | 是；artifact 没有进入源码改动 |

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

| Case | Repeat | Provisional expected | Existing LLM route / confidence | Jev route / confidence | Jev probabilities（standard / planned） |
| --- | ---: | --- | --- | --- | --- |
| RJV-008 | 1 | standard | planned / 0.78 | standard / 0.79 | 0.89 / 0.11 |
| RJV-008 | 2 | standard | planned / 0.85 | standard / 0.78 | 0.89 / 0.11 |
| RJV-008 | 3 | standard | planned / 0.86 | standard / 0.80 | 0.90 / 0.10 |
| RJV-013 | 1 | standard | planned / 0.80 | standard / 0.99 | 0.99 / 0.01 |
| RJV-013 | 2 | standard | planned / 0.78 | standard / 0.99 | 0.99 / 0.01 |
| RJV-013 | 3 | standard | planned / 0.82 | standard / 0.99 | 0.99 / 0.01 |

没有出现 Jev 选 planned、Existing LLM 选 standard 的相反分歧。

## 5. Provisional route metrics

以下全部标记为 **provisional diagnostic metrics**。矩阵以 expected route 为行、predicted route 为列，计数包含 3 次 repetition。

### Existing LLM

- All 16 Case projections：39/48 = **81.25%** provisional diagnostic accuracy；去重 Case 为 13/16。
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

- All 16 Case projections：45/48 = **93.75%** provisional diagnostic accuracy；去重 Case 为 15/16。
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

以上 48 条投影包含重复观测和 deterministic Rule 输出。样本只有 16 个未裁决 Case，不能包装为正式 accuracy、benchmark accuracy 或 ground-truth accuracy。

## 6. Repeat stability

两路均为 **0/16 route-instability Cases**：每个 Case 的 run1/run2/run3 route 完全相同。RJV-004 虽然两路都稳定地偏离 provisional label，仍属于稳定的 route 错误，不是重复间抖动。部分 confidence 数值有变化，但 route 没有变化。

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

| Provider | Confidence observations | Mean | Range | Provisional-correct mean | Provisional-error mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing LLM | 39 | 0.8872 | 0.78–0.96 | 0.9050（30 次，范围 0.78–0.96） | 0.8278（9 次，范围 0.78–0.88） |
| Jev | 39 | 0.7538 | 0.21–0.99 | 0.7953（36 次，范围 0.32–0.99） | 0.2567（3 次，范围 0.21–0.28） |

- Existing LLM 有 7 次 provisional error 的 confidence ≥ 0.80：RJV-004 三次、RJV-008 的 repeats 2/3、RJV-013 的 repeats 1/3。没有 confidence < 0.50 的 provisional-correct observation。
- Jev 没有 confidence ≥ 0.80 的 provisional error。6 次 provisional-correct Jev decision 的 confidence < 0.50，来自 RJV-011（0.42/0.49/0.48）和 RJV-014（0.37/0.32/0.34）。这些描述不构成 calibration 结论。
- RJV-004 中 Jev 选择 planned 的 winning probability 是 0.60–0.64，但 `confidence` 只有 0.21–0.28；这两个字段不能混读成同一个概率。

## 10. Failure case analysis

本次没有 Provider failure、route instability 或 deterministic Rule 越界调用。观察到的 provisional route errors 如下：

| Case | Observed result | 更可能的归因 | 下一步 |
| --- | --- | --- | --- |
| RJV-004 | LLM 与 Jev 三轮都选 planned；hypothesis 为 standard。LLM confidence 0.82/0.86/0.88；Jev confidence 0.28/0.28/0.21，planned probability 0.64/0.64/0.60。 | Dataset/label ambiguity 与 Router taxonomy boundary 最值得核查：该 Case 以长时间跨度和趋势措辞为主要诊断信号，正好处在“时间跨度/趋势本身是否足够进入 Planner”的边界。稳定一致说明不是 provider instability；两路也可能都对该表述中的隐含分析复杂度作了相同判断。 | 优先人工 adjudication；不基于一个 Case 改 taxonomy 或写 heuristic。 |
| RJV-008 | Existing LLM 三轮均选 planned；Jev 三轮均选 standard；hypothesis 为 standard。 | Multi-turn context handling / Existing LLM interpretation 是主要线索。前序 context 已将任务限定为概括一条给定理由，follow-up 的 standalone “why/later” 容易被过度解读为依赖调查。Jev 在相同投影下稳定选 standard，但 hypothesis 仍需人裁决。 | 与上下文相反的 RJV-007 一起人工 adjudicate，确认 route 是否确由 prior context 改变。 |
| RJV-013 | Existing LLM 三轮均选 planned；Jev 三轮均选 standard；hypothesis 为 standard。 | Existing LLM 对“分析”措辞可能有 lexical over-trigger；更像 prompt/provider 对任务复杂度的解读差异，而不是 missing context。该 Case 用于确认“单一语义解释”仍属 standard 的 taxonomy 边界。 | 人工确认标签；先不改 baseline prompt 或 Router 规则。 |

按 provisional hypothesis，Existing LLM 的 9 个错误观测来自上述三个 standard Case；Jev 的 3 个错误观测全部来自 RJV-004。没有证据支持本轮失败属于网络、服务、模型不可用或无效响应。

## 11. Planned → standard 风险

本次 8 个 provisional planned Case 共 24 次重复中，Existing LLM 与 Jev 都是 **0 次 `planned_execution → standard_execution`**。因此本轮没有观察到用户特别关注的方向性错误；小样本且标签待裁决，不能据此声称风险已消除。需要人工先确认 planned 标签，并在更大、更具代表性的样本上复测。

## 12. 当前证据支持与不支持

**支持：** Decisions API 在本次 39 次调用中均返回可用结果；Jev route 三轮稳定；Jev measured route-call latency 低于本次 Existing LLM；OpenRouter 返回了真实 token 和 cost；RJV-008/RJV-013 是可供下一轮 adjudication 的明确分歧样本。

**不支持：** Jev 在真实 ground truth 上优于 Existing LLM、confidence 已校准、这些结果能泛化到生产流量、Jev 提升 Planner utility，或 `planned_execution → standard_execution` 风险不存在。没有做 forced-path Planner utility 实验。

## 13. Rollout 建议

**`ready_for_human_adjudication`。** 先由人裁决 16 个 provisional label，重点审查 RJV-004、RJV-008、RJV-013 以及 RJV-007 的多轮上下文对照。生产 Router 继续保持 `shadow`；没有 human-adjudicated labels 和 Planner utility 证据前，不切换到 `jev`。

## 执行入口修复与验证

原定命令最初无法启动：`pyproject.toml` 声明了 `project.scripts.trivae` 和 `src/` 布局，但未声明 build system 或启用 uv package，`uv` 因而跳过本地项目安装及 CLI entry point。已在 `pyproject.toml` 加入 `[tool.uv] package = true`，`uv.lock` 相应记录本地项目为 editable source；只修复命令打包/集成，不改变 Router 或主模型行为。之后真实执行了 `uv run trivae --help`，并运行 `uv run --extra dev pytest tests/test_cli.py -q`：**28 passed**。首次 uv 同步时，uv 自动删除并重建了本地 `.venv`，随后从 lockfile 同步并安装测试 extra。

实现阶段的既有验证记录为全仓 `pytest` 618 项通过、Mypy 对 114 个源码文件无错误、任务涉及的 Python 文件 Ruff 通过，且 Trellis task validation 通过。全仓 Ruff 当时发现 62 项既有问题，位于本任务范围外。本轮针对新增 CLI packaging 修复重新运行了 28 项 CLI 测试和真实 CLI 入口。

这次发现的可复用约定已补入 `.trellis/spec/project/workflow.md`；本 ADR 与本报告已更新为真实运行结果。该细节属于 CLI packaging contract，无需扩展为新的跨层 API spec。
