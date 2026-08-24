# Implementation and Validation Plan

## Planning gate

- [x] 已检查 AGENTS.md、Trellis workflow、project/backend spec index 和相关共享 guides。
- [x] 已阅读 architecture、Stage 1.4/1.5/1.6/1.7/1.9/1.10 confirmed design。
- [x] 已检查目标 branch、working tree、最近 semantic retrieval commits、现有 tests 和
  当前依赖状态。
- [x] 用户确认 planning summary 后，运行 `task.py start` 进入 implementation phase。

## Common setup and evidence rules

1. 启动 task 后先检查依赖、`PYTHONPATH=src` 测试入口、SQLite snapshot、semantic index 和
   已验证的 Provider 配置；只在项目环境中补齐必要依赖。
2. 所有新增代码加入简体中文注释；关键逻辑逐行说明，保持现有项目风格和显式错误语义。
3. 不提交真实聊天正文、secret、hidden chain-of-thought 或超 scope 数据。Smoke 只保存 query
   元数据、tool sequence、round/count、trace id、answer/citation 状态、latency/usage 和
   failure category。
4. 每个阶段的验证输出和 failure case 放在 task validation 记录中；若修复产品代码，重新跑
   该阶段完整验证，不修改测试来掩盖实现错误。

## Stage A checklist — Dual Retrieval Agent Surface

### Implementation

- [x] 将正常 `QueryRequest` 编译到 Runtime 的 Interactive CLI 路径默认 visible capabilities
  改为 `lexical_search` + `semantic_search`；低层 legacy `AgentRunRequest` 显式兼容边界不改写。
- [x] 保持 `search_messages` legacy registry、显式 caller 和已有 tests/Evaluation 可用。
- [x] 统一两个 canonical retrieval Tool 的 model-visible description，说明 selection guidance
  和 result/error semantics；删除 prompt/docs 中会误导 canonical/legacy 的混用。
- [x] 确认 multi-tool calls 使用同一个 Runtime、Trace、Evidence/Citation 链路。
- [x] 保持 semantic unavailable/stale 显式 failure，禁止 silent lexical fallback。
- [x] 在既有 EvaluationRunner/Store 体系加入 Agent Tool Selection / Retrieval Behavior
  diagnostic cases；保留 paired lexical-vs-semantic benchmark 与 provisional labels。
- [x] 更新 Trellis validation 和 interview-defense，只记录已实际验证的事实。

### Validation gate

- [x] A1 exact lexical：repo/URL/code/error/nickname/exact phrase。
- [x] A2 semantic paraphrase：原文不要求包含用户 exact wording。
- [x] A3 weak-result continuation：同一 Runtime 内 lexical↔semantic 多 Tool Call。
- [x] A4 no-result/weak-result：无编造证据、无静默数据源变化。
- [x] A5 semantic unavailable/stale：显式失败行为保持。
- [x] Unit tests、integration tests、ruff、mypy、full test suite。
- [x] 真实 Provider smoke：lexical-dominant、semantic-dominant、multi-search、no-result。
- [x] Trace 检查能解释 visible tools、selection、arguments、result、second call、Evidence、
  answer、error/empty/stale。
- [x] Evaluation 产出可复核的行为记录；不夸大 provisional evidence。
- [x] 记录发现的 Failure Case 及根因分类；修复并回归验证。
- [x] Checkpoint A commit：`da405dc feat: default dual retrieval agent surface`；随后以独立修复
  commit 收敛真实 Provider smoke contract、semantic transport bound 和 Agent selection guidance。

## Stage B checklist — Context and Member Tools

> Stage A/B checkpoint 已完成；当前执行 Stage C，Checkpoint C 必须独立提交。

### Implementation

- [x] 复用 canonical bounded context/read capability，实现并注册 `get_message_context`。
- [x] 复用 identity/membership capability，实现并注册 `find_members`，返回候选和匹配依据。
- [x] 接入现有 Runtime/Tool Envelope/Trace/Evidence，不创建 candidate state。
- [x] 扩展 Agent-facing Evaluation 与 Trellis/interview-defense。

### Validation gate

- [x] search → context、invalid message id、scope boundary、truncation、conversation boundary。
- [x] context 已足够时不机械调用的 Agent 行为检查。
- [x] unique member、same nickname candidates、alias、multiple sessions、unknown、scope restricted。
- [x] Trace 区分 search auto-context 与 explicit context deepening。
- [x] Unit/integration/full tests、ruff、mypy、真实综合 Provider smoke、Evaluation、Failure Case。
- [x] Checkpoint B commit：`feat: add context and member agent tools`。

## Stage C checklist — Structured SQL Tools

### Implementation

- [x] 复用 canonical SQLite schema/access path，实现受边界控制的 `get_schema`。
- [x] 实现 `execute_sql` read-only contract、结构化 SQL validation、hard scope enforcement、
  bounded result/truncation 和显式错误。
- [x] 接入现有 Runtime/Trace/Evidence/Evaluation；不添加 Analysis View。

### Validation gate

- [x] COUNT、GROUP BY、time range、sender/session aggregation、合理 JOIN、no rows。
- [x] malformed SQL、write SQL、DDL、scope escape、large result truncation。
- [x] schema inspect → execute_sql；citation/evidence policy 与现有设计一致。
- [x] Unit/integration/full tests、ruff、mypy、真实 SQL Provider smoke、Trace、Evaluation、
  Failure Case。
- [x] Checkpoint C commit：`feat: add structured sql agent tools`。

## Final synthesis checklist

- [x] 六个 canonical tools 的最终 Agent surface 和 `search_messages` compatibility boundary。
- [x] 14 类综合 diagnostic query：exact lexical、semantic、deep context、member ambiguity、
  member→retrieval、count、aggregation、mixed task、no-result、ambiguous、time-bounded、
  cross-tool。
- [x] 汇总 tool sequence、unnecessary calls、success/failure category、Evidence/Citation、
  latency、usage、rounds；不把 provisional evidence 写成确定结论。
- [x] 完整 tests、ruff、mypy、compileall、Trellis validation 可复核，interview-defense 更新。
- [ ] working tree clean，提交 task bookkeeping，不 push、不 amend。
