# 2026-10-17 正式调度启用验证

用户在 main 合并后明确要求启动调度，覆盖最初暂不启用约束。开发继续使用独立 worktree / codex/qce-enable-schedule，主工作区已有无关改动保持原样。

## 启用前验证

- `uv run --with tqdm pytest -q --tb=short`：1104 passed、1 skipped，23.45s；唯一 skip 为 opt-in 真实 launchd smoke（原独立阶段已通过）。
- `uv run ruff check src tests scripts/macos/launchd_import.py`：通过。
- `uv run mypy src`：128 source files，通过。
- 定向 47 passed、1 skipped：真实 FTS/语义构建器至 Agent 工具、转发内部正文、无变更/纯重复不构建、embedding 部分提交失败后的同快照续建、新水位重建、提交后队列确认恢复、CLI 显式更新与只读状态。
- 新测试首轮发现的两处测试自身错误已修正：正式 readiness 的完成值为 completed；mock 必须先保存原 rebuild，避免 side_effect 引用 mock 自身。真实构建器及状态契约未作特殊分支修改。

## 生产基线（只读）

2026-10-17 10:57 +08：40 个 raw JSON，Canonical 765,780 条，FTS 转发投影 12,484 条，semantic completed / revision 0 / chunk 92,288。尚无 auto_import 状态表；正式服务此前未安装也未加载。

## 索引成本与验收边界

仅新增已提交批次产生工作，每种索引一轮合并调用一次现有 builder；不是每次日历执行全量构建。现有 API 不提供跨水位局部向量增量，本轮不改写底层算法。历史本机续建 72,184 个向量曾耗时约 5h13m；本轮若触发全量构建可能长期 building，不据 loaded 或 Canonical 完成宣称语义已可检索。

实际安装、运行和生产工具结论在启用后补记。物理重启/休眠没有在共享机器强行执行。
