# 验证与交付

任务实验与分析已完成；本次交付把 runner、测试、报告和原始实验工件一并纳入 Git。任务目录保留原位、未归档，避免改变报告中的工件位置。manifest 中的 execution commit 与 dirty state 仍记录真实执行时身份，不改写成之后的交付提交。

## 工程检查

- 正式请求前：相关 Evaluation/Query/Evidence/Application 回归、新增 9 个 provider-free runner tests、Ruff、mypy 和 diff check 通过。
- 正式请求后：全量 provider-free pytest **641 passed（15.84s）**；Ruff 检查 src/tests/runner/analyzer/finalizer 全部通过；mypy src **115 files** 通过；git diff --check 通过。
- 分析重算：依次执行 analyze_e2e.py 与 finalize_analysis.py，16 unique pairs、8 组实际 Planner body 隔离检查、完整冻结盲审合并通过，不产生 Provider 请求。
- 生产 src、pyproject.toml 与 uv.lock 无改动；规范补充只记录本轮发现的实验契约。
- task.py validate 通过；提示既有 agent-runtime-guidelines.md 超过 32768 字节的自动注入上限。本轮已直接读取相关契约并核对新增章节，不依赖截断的注入内容。

## 工件验收

| 契约 | 结果 |
| --- | --- |
| Logical attempts / results | 16 / 16，每 case/treatment 一次 |
| HTTP requests / responses | 63 / 63（Planner 16，downstream 47） |
| Retry / timeout / 替换失败 | 0 / 0 / 0 |
| Evaluation runs / results / terminal traces | 16 / 16 / 16，700 events |
| Blind pairs | 8，全部完成后揭盲，判断与冻结副本字节相等 |
| 实际序列化隔离 | 每组唯一差异 reasoning_effort；首个 downstream 非 messages 参数/schema 相等 |
| 代码与数据身份 | 执行前后 frozen 副本逐字相等；未使用哈希 |
| 阶段判断 | Gate A：两条 none 臂事实/引用回退，停止扩大 |

证据边界：盲审是独立 AI 判断，非人工裁决；请求了 Luna/max，但工具未返回 resolved model，不声称实际模型验证。单次配对不能证明 Planner 语义差异稳定导致质量回退。none reasoning usage 缺失保持 null/unknown，金额 unavailable。Provider cache 的顺序影响只能 counterbalance，不能声称完全消除。

完整业务分析、具体失败与下一步局部因果实验见 [report.md](experiment/planner_reasoning_ab/e2e/report.md)。
