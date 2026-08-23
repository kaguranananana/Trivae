# 执行计划：DeepSeek Tool Calling 与 Provenance

## Phase 1：证据与基线

- [x] 记录当前分支、工作树和既有 deterministic gate。
- [x] 用临时 DB + 真实 raw 数据运行 debug Trace smoke。
- [x] 获取每个 SDK tool call 的安全参数投影、round、接受/拒绝阶段和 contract 字段。
- [x] 获取模型最终 source locator 与 current-run provenance 的字段级 diff。
- [x] 确认 expanded messages 是否已具备可引用 provenance。

## Phase 2：最小修复

- [x] 根据已证实根因选择 schema/description、prompt 或 provider adapter 的最小修改点。
- [x] 确认无需修改 M5 citation contract，保留 compatibility/rollback 边界。
- [x] 增加 deterministic regression tests，确保非法参数仍透明失败、合法 source 能 hydrate、未知 source 不能 commit。
- [x] 生成代码加入简体中文注释，关键逻辑逐行说明。

## Phase 3：真实验证

- [x] 运行简单关键词、带 filter/context、无结果或 partial 的真实 DeepSeek smoke。
- [x] 记录 provider/model/trace/termination/tool/retrieval/finalization/commit 安全摘要。
- [x] 执行了多 Evidence/partial 观察；不把一次成功当作长期质量 baseline。
- [x] 对失败按 Trace 证据归因，未新增无依据 fallback/retry。

## Phase 4：质量与交付

- [x] `PYTHONPATH=src ./.venv/bin/pytest -q`（136 passed）
- [x] `./.venv/bin/ruff check src tests`
- [x] `./.venv/bin/mypy`（47 source files）
- [x] `git diff --check`
- [x] 更新 Failure Case / validation 文档与 project Problem Record。
- [x] `trellis-check` 等价质量检查通过后提交、推送当前分支并确认工作树 clean。
