# Implementation plan

本计划遵循“实现 → 暴露问题 → Trace 定位 → 根因修复 → Evaluation/Regression”的顺序。规划阶段只编辑本任务文档；产品代码要在用户批准规划摘要并执行 `task.py start` 后修改。

## Phase 1 — Freeze evidence and contracts

- [x] 记录当前 `main` base commit、working tree 状态和 SDK 版本。
- [x] 用最小 SDK-style fixtures 固定 `function_call`、`function_call_output`、assistant content block 的实际形状。
- [x] 明确新增 Runtime Event 字段的序列化形状和 hidden item 排除规则，保持 SDK 类型不越过 adapter。

## Phase 2 — Capture actual model-visible execution facts

- [x] 在 `openai_adapter.py` 提取安全的 input item projector，并在 `on_llm_start` 使用已过滤的 `input_items`。
- [x] 在 `on_llm_end` 提取 assistant visible text、function call name/arguments/call identity；忽略 reasoning/hidden SDK item。
- [x] 将 plain projection 加入 Trivae Runtime Event 和 Collector normalized payload；复用 `CapturePolicy` 做统一 redaction/bounds。
- [x] 维持 `content_delta` 不持久化、SDK built-in tracing 关闭、未知异常显式暴露。

## Phase 3 — Build derived transcript projection

- [x] 新增 `observability/transcript.py`，按 StoredTrace sequence 组装 User/Context/Router/Planner/Model Turn/Tool/Retrieval/Evidence/Citation/Final Answer。
- [x] 对 Tool Result 只使用 model turn input 中的 `function_call_output.output`；把 retrieval completeness metadata 作为短摘要。
- [x] 重构 `TraceTextLogWriter` 的完整 export 组合顺序；保持增量 sidecar 和 Raw Events 行为。
- [x] 检查 normal/debug 输出的 limitation 是否可见，避免任何“看似完整”的误导。

## Phase 4 — Tests and Failure Case regression

- [x] 增加第一轮 `system + user` capture test。
- [x] 增加 tool call 后下一轮 assistant action + tool result capture test，并比较 hook input 与 StoredTrace payload。
- [x] 增加 hidden reasoning/SDK internal field exclusion test。
- [x] 增加完整 synthetic Trace Transcript test。
- [x] 增加 `planner.failed` / `executed_without_plan` 可读性 test。
- [x] 增加 20/77/truncated test。
- [x] 增加 normal/debug bounds and redaction regression test。

## Phase 5 — Docs, smoke, quality gate

- [x] 以 amendment 形式更新 Stage 1.9 ADR 和 backend quality guidelines。
- [x] 通过现有 Application/CLI path 执行真实 DeepSeek smoke（有配置时），导出并读取一个实际 `.log`。
- [x] 运行 `pytest`、`ruff check src tests`、`mypy src`；失败时先复现并修复实现根因。
- [x] 用真实生成的 `.log` 做修改前后 Failure Case 对比，记录哪些信息现在可直接定位。
- [x] 创建 `codex/human-readable-execution-transcript` 分支、提交变更并记录 commit/base；在最终报告中只使用文件名或最短相对路径。

## Completion evidence checklist

- [x] `git status --short --branch` clean except intentional task/archive metadata。
- [x] Branch/base/commit 可复现。
- [x] 没有第二个 Trace store、runtime debug writer 或 DB re-query。
- [x] `.log` 同时含 Transcript 与 Raw Events。
- [x] final answer、model-visible tool result、planner failure、retrieval truncation 均可在单个 Debug log 中核对。
- [x] hidden CoT、provider secret、越权数据和 raw SDK object 均未进入 StoredTrace。

## Verification evidence

- Base: `main` / `7de3c67`; working branch: `codex/human-readable-execution-transcript`。
- Local SDK: `openai-agents==0.22.0`; `on_llm_start` input was verified as filtered provider input containing `function_call` and `function_call_output` items.
- Regression: `pytest -q` → `173 passed`; `ruff check src tests` → passed; `mypy src` → passed for 56 files; `git diff --check` → passed.
- Real DeepSeek smoke: trace `trace-12f2784e0bc3405789212fe2d4ad54bd`, completed; complete export contains Transcript, message正文、planner failure and final answer.
- First real smoke invocation intentionally exposed a non-exported `.env` shell issue and failed before provider invocation; rerunning with command-local export completed successfully.
