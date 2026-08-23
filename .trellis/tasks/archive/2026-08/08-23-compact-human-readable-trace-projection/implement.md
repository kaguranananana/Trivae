# Implementation plan

## Phase 1 — Baseline and contract

- [x] 固定当前真实日志的行数/字节数、Transcript/Raw 边界与 CLI export 行为：基线 14,922 行 / 898,176 bytes，远端 `main` 为 `7de3c67`。
- [x] 检查现有 text writer、Application facade、CLI parser 和所有测试调用点。
- [x] 更新 quality guideline，明确默认 transcript、显式 raw view 和 delta/full context 语义。

## Phase 2 — Projection implementation

- [x] 在 transcript projection 中加入顶部 Trace Summary。
- [x] 增加 delta/full model context mode，默认 delta，保留 full detail。
- [x] 将默认 `format_trace_text` 收敛为 metadata + summary + transcript；将 raw event formatter 接入显式 raw view。
- [x] 扩展 Application/CLI `trace export` 的 `--view` 与 `--context` 参数，不让 CLI 直接读 SQLite。

## Phase 3 — Regression and real Trace

- [x] 更新/新增 Transcript、text view、CLI parser、Application export 测试。
- [x] 验证 default log 不含 Raw Events，raw view 保留完整 events。
- [x] 验证 delta mode 不重复 system/user，full mode 保留完整 model-visible input。
- [x] 用真实 DeepSeek Trace 重导出并比较大小、关键区块和 failure visibility：默认 2,268 行 / 79,168 bytes，raw 12,339 行 / 803,352 bytes。
- [x] 运行 pytest、ruff、mypy、git diff --check。

## Completion evidence

- [x] 默认 `.log` 在 `[FINAL ANSWER]` 后结束。
- [x] SQLite/trace show 仍能提供 canonical raw events。
- [x] default/full/raw 三种 projection 都来自同一 StoredTrace。
- [x] Branch、commit、base、baseline 和验证结果已记录：`codex/human-readable-execution-transcript` / `baa852e` / `7de3c67`。
