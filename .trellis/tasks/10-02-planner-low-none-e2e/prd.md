# Planner low vs none targeted E2E

用户授权直接完成有界真实生产实验，无需中途询问。继承 09-28 Planner-only 的 8 个 exposed Development Case，仅改变 Planner reasoning_effort。第一阶段 16 个 logical runs，各 case/treatment 恰好一次，无 retry/补跑；只有胶着或明显随机方差才允许第二阶段再 16 次。

- 不访问 Holdout/Calibration，不改生产 prompt、Router、Tool schema、Retrieval、Answer。
- 复用 EvaluationRunner → TrivaeApplication.query；已有 forced planned override 两侧相同。
- machine preflight 固定 messages、metadata、工具 schema、模型、预算、快照、代码和评测契约。
- 保存全部请求、响应公开字段/usage、attempt、Trace、Evidence、Answer、自动指标和独立盲审。
- usage 缺失用 null；金额 unavailable；不压成总分，不修复实验发现的生产失败。
- 完成 provider-free tests、lint/type check、实验后回归和逐 case 归因报告。

## 验收

- [x] 16 次生产 E2E 与真实请求 ledger 对齐：16 Planner + 47 downstream，共 63 HTTP requests，无重试或补跑。
- [x] 全部 8 组独立 AI 盲审先完成，随后揭盲；原始判断与冻结副本字节相等。
- [x] 分层指标、逐 case 链路、质量/效率判断和最小后续实验沉淀。

结果触发 Gate A：none 臂 2 条实质最终质量回退、3 条改善、3 条相同；停止扩大。单次配对不证明稳定的 Planner 语义因果性。详见 [report.md](experiment/planner_reasoning_ab/e2e/report.md) 与 [validation.md](validation.md)。生产源码与配置未修改。
