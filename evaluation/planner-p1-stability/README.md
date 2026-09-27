# Planner P1 stability experiment

本目录仅对八条已暴露 Development Case 调用 Planner completion。P0 prompt 固定于 `12f2f75`；P1 prompt 从上一轮实际请求冻结在 `frozen-p1-prompts.json`，来源提交 `68286d569025718c88029b66bc028e89a5a10c72`。两条对照保留 `reasoning_effort=low`。P1-B 使用压缩后的当前 Planner prompt 与 `low`，仅用于区分 prompt 压缩的影响；P2 使用同一压缩 prompt 与 `reasoning_effort=none`，检验隐藏推理消耗。四路均保留 JSON mode、同一 parser、同一 2048 completion ceiling、同一七 Tool allowlist 和输入 Snapshot。所有调用只生成 Plan，不运行 Router、Tool Loop 或回答。

运行前先核对 `run-config.json` 的 Provider/model。一次独立调用无重试，失败同样进入正式分母。每个 Case/repeat 的四路顺序轮换，八 Case 使各版本处于各位置的次数相同。

```bash
.venv/bin/python evaluation/planner-p1-stability/run_planner_only.py \
  --output-dir .trellis/tasks/09-27-planner-p1-stability/experiment \
  --repeats 3
```

Runner 在调用前保存 run config，每次 response 后立即写入 `runs.jsonl`；完成后由原始记录派生 `metrics.json` 和三路 `blind-review-packet.md`。盲包只展示 P0/P1/P2 的 A/B/C 随机标签，`blind-key.json` 单独保存映射。P1-B 是归因消融，不参加候选质量盲审；其有效 Plan 仍可用于诊断。盲审应按旧任务的八轴 rubric 审核，先看盲包、后揭映射。assistant 的 provisional review 必须与 human adjudication 区分，不能直接变成生产 gate。

`reasoning_tokens` 只在 Provider usage 实际返回时记录，缺失不推断为零。金额成本若 Provider 未提供则为 `unavailable`。本实验不访问 Holdout，不执行三路 E2E。
