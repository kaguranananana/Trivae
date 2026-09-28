# 实验设计

复用 `run_planner_only.py` 中已暴露的 Case loader、compact Snapshot 和 Capability metadata。两侧使用同一生产 `SoftPlanner` 构造 P1 prompt，由同一个 `OpenAIAgentsRuntimeAdapter` 的 completion 方法发送请求。各侧只通过 `reasoning_effort_override` 选择 `low` / `none`；Plan parser、20 秒 timeout、2048 token、temperature 0、JSON mode 与 Provider client 共用。

首次请求前逐 Case 核对生产 prompt 与冻结 P1 fixture 全文相等，核对请求投影除 effort 外完全相等，并确认 Provider/model、预算与七 Tool allowlist。提前保存固定交错 schedule。每次请求前写入 attempt ledger，返回后写原始 record 并 flush；中断后不得续跑或补跑。

全部生成结束后，以固定随机种子为每组打乱 A/B 标记。盲包只含 Case 问题、共同 P1 规划契约及 Plan 内容；单侧失败只显示无有效 Plan。映射在独立文件；reviewer 完成全部判断后再揭盲。

实验记录归属新 Trellis task 的 `experiment/`。现有生产源码、旧实验记录和 Holdout 均不改动。
