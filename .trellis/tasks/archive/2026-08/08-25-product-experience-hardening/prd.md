# Product Experience Hardening

## Goal

把现有已经具备六个 Agent-facing Tools、统一 Query/Application 链路、同源流式事件、
Trace、Evidence/Citation 和 Conversation persistence 的 Trivae，收敛成可以每天打开
`trivae chat` 查询真实群聊的 CLI 产品体验。

用户应能在一次 CLI 生命周期内完成：启动 readiness 检查、选择/切换群聊范围、提问、
查看真实流式进度、核查引用原消息、标记体验反馈、查看历史并恢复安全的会话。

## Confirmed repository baseline

- 当前代码基线为 `main` 上六工具 checkpoint 完成后的实现；旧的
  `agent-facing-tool-surface` Trellis task 已归档。
- 当前测试基线：`pytest 275 passed`、`ruff check src tests` 通过、`mypy src` 通过、
  `python -m compileall -q src tests` 通过。
- 真实 Canonical Store 有 7 个 sessions、473,236 条 messages；当前 semantic index
  状态为 `completed`，索引 473,236 条 canonical messages、54,267 chunks。
- `TrivaeApplication` 已提供 `list_sessions()`、`semantic_index_status()`、
  `create/read_conversation()`、`read_trace()` 和统一 `query()` facade；CLI 当前只在
  启动时选择一次 scope，支持 `/new`、`/exit`、`/quit`。
- `CliEventRenderer` 已消费同一次 Query 的 normalized/runtime live events；Trace Store
  不是实时队列，normal/debug capture 不保存 reasoning 或 token delta。
- `AnswerArtifact` 已包含稳定 `MessageSource` / `StructuredSource`、trusted
  `MessageDisplaySnapshot`、current-run provenance 和 scope 校验；Conversation 当前
  没有持久化 scope identity，也没有 conversation listing/title contract。
- 当前 `Settings` 只从进程环境读取 provider 配置，且 runtime lazy-create；CLI 尚未在
  启动时投影 provider readiness。`.env` 自动加载不在本任务默认范围内。

## Requirements

### R1. Citation / Source drill-down

1. 成功 Query 结束后，CLI 从 finalized/hydrated `AnswerArtifact` 确定性地生成 bounded
   `Sources` 区块；source metadata、excerpt、session、author、time 只能来自 trusted
   `MessageDisplaySnapshot`，不得从模型文本重新生成。
2. Message source 以稳定顺序编号并支持 `/source <n>`；命令通过 Application read
   facade 读取同一 `session_id` 内 bounded local context，target message 必须高亮，
   严格服从当前 `ExecutionScope`，不得越过 session/time/conversation boundary。
3. `/source` 对越界、无效编号、缺失 source、context 不可恢复都显式报错。
4. `StructuredSource` 不得伪装成消息上下文；`/source <n>` 只展示 bounded read-only
   result summary（locator/value/scope/limitations）。
5. 不新增 Evidence 数据模型，不重新执行 Agent、Retrieval 或 Provider 请求。

### R2. Scope management

1. 保留启动时的 session/All chats picker，增加 `/scope` 只读显示当前 scope 和
   `/chats` 显示可用 sessions 并允许重新选择。
2. scope 选择仍在 CLI/Application 边界编译为 trusted `ExecutionScope`，不能由
   prompt guidance 或模型参数代替授权边界。
3. 选择不同 scope 后，后续 Query 必须使用新的 Conversation；旧 Conversation、旧
   answer source、旧 feedback 不得污染新 scope，并明确提示 scope 与新会话已切换。
4. `/new` 只创建同 scope 的新 Conversation；不改变 scope。

### R3. Startup readiness and `/status`

1. `trivae chat` 在第一次提问前通过 Application formal status facade 输出简短状态：
   Canonical Store 是否可用及 message count、semantic index 的现有状态/identity、
   Provider safe readiness/model。
2. `/status` 在生命周期内重新显示上述状态，并附带当前 scope、当前 conversation。
3. 必须保留已有 semantic status 语义：`missing`、`building`、`failed`、`stale`、
   `partial` 不得被误报为 ready；状态检查不自动 rebuild、不执行昂贵扫描、不启用
   silent lexical fallback。
4. Provider status 表示“配置足够发起 Query”，不伪造网络健康检查；secret 不进入输出。

### R4. Normal/verbose streaming UX

1. 不改变已有 Runtime/Trace/Query streaming architecture，只调整默认 renderer 的
   产品投影。normal 展示真实 thinking（若 provider/SDK 实际提供）、route/plan 的
   bounded 摘要、tool/retrieval 的可读阶段、answer delta、失败和完成。
2. normal 不展示 raw RuntimeEvent/JSON、tool_call_id、operation id、scope repr、raw
   AnswerArtifact、大段 Tool Result、provider-specific 字段或 hidden reasoning；不得
   根据 Agent 阶段伪造 thinking。
3. verbose 继续复用同一次真实事件流和 `trace_profile="debug"`，增加 bounded/redacted
   route/plan/args/count/timing/usage/trace metadata，但不突破 secret、聊天正文、hidden
   CoT 边界。
4. 0 result、partial/truncated、Tool failure 后恢复、provider/finalizer failure、部分
   answer 后失败、Ctrl+C/EOF、Unicode 和行边界均需给用户明确状态；0 result 不等于异常。

### R5. Experiential feedback

1. 增加 `/good`、`/bad`、`/bad <note>` 和 `/feedback`；只绑定最近一个已完成 Query，
   没有可绑定的 completed run 时显式拒绝。
2. 持久化 feedback identity、timestamp、conversation_id、trace_id、runtime run_id、
   trusted scope snapshot、`good|bad` rating 和 bounded optional note。
3. 反馈使用独立轻量 persistence boundary，不写入 Canonical Message Store，也不把
   feedback 作为 Trace event 或 Evaluation human label。
4. 多次对同一 completed run 的反馈策略为 upsert：保留一个当前体验反馈，后一次命令
   更新 rating/note，并通过 `/feedback` 可见；该记录的语义明确为 user experiential
   feedback，不等于 relevance label、ground truth 或 exhaustive annotation。

### R6. Conversation history / resume

1. 增加 `/history`，按 `updated_at DESC`、稳定 identity 次序展示 bounded 最近会话；
   title 使用持久化 metadata（若没有则使用首条 user query 的 deterministic bounded
   projection），不调用 LLM。
2. 为新 Conversation 持久化完整 `ExecutionScope` snapshot，并对旧 schema 做显式、
   可回滚的最小 migration；无法恢复 scope 的 legacy Conversation 只能列出，不能猜测
   scope 继续 Query。
3. `/resume <n>` 必须验证 conversation 存在、scope metadata 完整且可恢复；若恢复会
   改变当前 scope，明确输出恢复的 scope。不得在不同 scope 下把旧 Conversation history
   注入新 Query。
4. `/new` 回归保持同 scope；resume 不执行 Retrieval、Provider 或隐式标题生成调用。

### R7. Friendly failure UX

1. known contract errors 映射为简短、人类可理解的提示，并保留 error code/Trace identity
   供诊断；semantic stale/missing、no reliable evidence、provider/finalizer/commit
   failure 都不能伪装成成功。
2. unknown errors 不 silent catch；normal 交互不打印无意义长 traceback，verbose/debug
   保留 bounded 可诊断信息，且 Trace/log identity 可用于进一步定位。
3. 仅当 Agent 后续真实继续执行时，Tool failure 才显示“失败但继续”；不新增 application
   retry、fallback、第二套 Query/Runtime 或特殊 query 分支。

### R8. Documentation, checkpoints and evidence

1. 以四个可独立回滚 checkpoint 交付：A Source、B Scope/Startup、C Feedback/Resume、
   D Renderer/Failure；每个 checkpoint 经过 focused tests、integration/regression、
   CLI smoke 和 git commit 后再进入下一个。
2. 更新 architecture、Application/CLI boundary、Evidence/Citation、Conversation、
   Trace live/persisted projection 和 interview-defense 文档；只记录真实实现和验证
   事实，不夸大质量/延迟指标。
3. 真实 smoke 使用当前 Canonical DB、semantic index 和当前 provider；只记录 query
   category、scope、tool sequence、source count、feedback result、trace identity、
   latency/usage、failure category 和完成状态，不提交聊天正文、secret、reasoning 或
   hidden CoT。

## Out of scope

- Retrieval 算法、ranking、fixed hybrid/RRF/reranker/query rewrite/multi-query expansion、
  embedding model/dimension/chunk 参数。
- Router/Planner 决策策略、六个 canonical Tool 的语义、Capability 权限边界、Evidence/
  Citation Finalizer 的验证规则、Evaluation runner 的质量语义。
- 第二套 Query pipeline、第二套 Agent Runtime、Trace Store polling 实时流、UI/TUI
  framework 大重写、Web UI、HTTP Product Interaction。
- 自动 semantic rebuild、silent lexical fallback、application-level retry、自动 citation
  repair、隐式扩大 scope。
- 读取或提交真实聊天正文、`.env`、provider secret、hidden reasoning/CoT。

## Acceptance Criteria

- [x] `trivae chat` 启动后在首次提问前显示 database/semantic/provider readiness；`/status`
      同时显示当前 scope 和 conversation，状态语义与现有 facade 一致。
- [x] 成功回答显示 bounded Sources；`/source n` 能在 scope 内展示真实 target message 和
      bounded local context；structured source 明确展示 summary 而非伪造 message。
- [x] `/scope`、`/chats`、`/new` 满足 scope hard boundary、new Conversation 和 history
      隔离；切换后旧 source/feedback/history 不污染后续 Query。
- [x] `/good`、`/bad`、`/bad note`、`/feedback` 持久化并绑定正确
      conversation/trace/run/scope；重复反馈 upsert，不能被 Evaluation 当作 ground truth。
- [x] `/history` 排序稳定；`/resume` 对新 scope metadata 安全恢复，对缺失 scope 的
      legacy conversation 明确拒绝猜测；不会跨 scope 注入历史。
- [x] normal/verbose 事件来自同一次 Query；normal 无内部 JSON/ID/hidden CoT，verbose
      仍 bounded/redacted；0 result、partial、known failure、partial answer failure、
      Ctrl+C、Unicode、行边界有回归测试。
- [x] Query production path、Evidence/Citation Finalizer、Conversation atomic commit、
      Trace semantic contract、六 canonical tools、`search_messages` compatibility 和
      Evaluation runner 的既有测试全部保持通过。
- [x] 完成仓库可用的 pytest、ruff、mypy、compileall、Trellis validation，并完成真实
      provider/database smoke；真实 smoke 若因外部配置/网络失败，必须按 failure category
      记录，不以 mock 成功替代。

## Known risks / deferred items

- 旧 Conversation 缺少 scope，是本轮唯一需要 schema contract extension 的已确认缺口；
  如果 migration 发现现有数据无法可靠保留，则保留 history-only 行为并把 blocker 写入
  validation，不猜测旧 scope。
- 真实 provider 是否返回 reasoning、工具选择序列和延迟不是稳定产品契约，只如实记录
  smoke 观察，不为单个 query 添加 renderer 特判。
- 当前 `.env` 不由 Settings 自动加载；本轮 status 只如实报告当前进程配置，真实 smoke
  使用现有显式环境配置约定。
