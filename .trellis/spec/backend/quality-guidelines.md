# Quality Guidelines

> 质量与测试长期原则（源自工程原则第 2、5、6、7 节）。
> lint / type-check / 测试工具链将在业务实现任务启动前确定（当前仍不安装业务依赖）。

---

## 测试要求

- 关键行为必须有测试；测试失败优先检查实现。禁止仅为让错误实现通过而修改测试或增加特殊分支；若需求、接口契约或正式架构发生变化，或测试本身存在错误，可以同步更新测试，并记录原因。
- 重要修复：保存 Failure Case → 加入测试集 → Regression Test。
- Evaluation 优先用真实指标（Recall@K、Task Success Rate 等），避免仅凭主观感觉。
- 固定 Evaluation Set 逐步建立；不制造无意义指标。
- 每个实现任务完成时，按项目级 [Interview Defense Evidence](../project/interview-defense.md) 留下事实证据索引；不得虚构 Failure Case、性能数字或未验证的设计过程。

## 禁止模式

- 为「看起来工程化」增加无实际价值的抽象与基础设施。
- 针对单个样例的特殊规则 / 兼容分支。
- 静默吞错（见 error-handling.md）。

## 质量闭环（关键模块）

实现 → 暴露问题 → 保存 Failure Case → 复现 → 定位 → Root Cause → 候选方案
→ 最小合理修改 → Test / Evaluation → 验证改善 → Regression Test → 文档沉淀

## CLI / Application Read Contract：Interactive Chat

### 1. Scope / Trigger

新增交互式 Query 入口或 Application read facade 时，必须复用生产 Query path；触发条件包括新增 CLI command、跨越接口/Application/Canonical Read 三层，或新增 session metadata 读取。

### 2. Signatures

- `trivae chat [--database PATH] [--verbose] [--env-file PATH]`：默认数据库为 `data/trivae.sqlite3`；未指定 `--env-file` 时读取当前工作目录下存在的 `.env`；verbose 选择可信本地 debug Trace profile，并扩大终端诊断投影。
- `TrivaeApplication.list_sessions() -> tuple[ChatSession, ...]`：由 Application 暴露 session metadata read facade。
- `SQLiteCanonicalReadRepository.list_sessions() -> tuple[ChatSession, ...]`：只读 `chat_sessions` canonical 表，并按 `name COLLATE NOCASE ASC, session_id ASC` 稳定排序。
- 普通输入必须构造 `QueryRequest(query=..., scope=..., conversation_id=..., trace_profile=...)` 并调用 `await application.query(request, on_event=renderer.handle)`；仍只进入一次同一 Application Query 主链路。

### 3. Contracts

- 选择具体 session 后，CLI 生命周期内固定 `ExecutionScope(allowed_session_ids=(selected_session_id,))`。
- 选择 `0. All chats` 时使用 `ExecutionScope(allowed_session_ids=None)`；不得创建 `ALL`、`*` 等伪 session ID。
- `conversation_id` 是独立于 scope 的 CLI 状态：首轮为 `None`，后续使用上一次 `QueryResult.conversation_id`，`/new` 只清空它。
- 成功 Query 实时展示 `QueryStreamEvent` 投影，并在没有 answer delta 时使用 `QueryResult.final_answer` 补齐正式答案；已经 streamed 的正文不得重复打印，`runtime_answer` 不是用户答案 fallback。
- normal 显示 Route、Plan、Tool/Retrieval 摘要、Answer streaming 与 terminal error；verbose 额外显示 bounded diagnostics、usage、timing 和 normalized source metadata。两者都不能 dump 巨大 Tool Result、secret、raw event identity 或越权数据。
- Runtime adapter 仍只把 Provider 实际 reasoning delta 归一化为同一 stream event；CLI 可以消费该 event 维持顺序，但 normal/verbose 都不把 hidden CoT 渲染到终端，也不得按 stage 伪造 reasoning。
- Renderer 在 Tool/status/terminal/interrupt 前关闭开放 thinking/answer 行；Streaming delta 只作展示，Conversation Store 仍一次提交完整 validated Assistant Answer。
- Provider 继续使用 `load_settings()` 的 `DEEPSEEK_API_KEY`、`TRIVAE_MODEL_PROVIDER`、`TRIVAE_MODEL_NAME` 和 `DEEPSEEK_BASE_URL` contract，不在 CLI 创建 client。CLI 只在创建 Application 前加载可选 dotenv；进程环境优先，`load_settings()` 不自动读取文件。
- dotenv 缺失的默认 `.env` 不改变原有环境变量启动语义；显式路径缺失或格式非法时显示分类错误并返回非零状态，错误投影不得包含密钥值。
- CLI 启动和 `/status` 只能通过 `TrivaeApplication.readiness()` 读取 database/semantic/provider 状态；不在接口层拼接 SQLite、触发 semantic rebuild 或执行网络健康检查。
- `/source n`、`/history`、`/resume n`、`/good`、`/bad [note]`、`/feedback` 只能调用 Application facade；scope switch 清空 conversation/source/feedback binding，legacy scope 缺失时明确拒绝 resume。

### 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| session 列表为空 | 展示可读信息并返回非零状态 |
| 选择序号非法或越界 | 展示 `Invalid selection.`，保留 picker，不改变 scope |
| `SettingsError` / Query / Scope 等已分类错误 | 展示 `Error: ...`，必要时带 Trace ID，返回非零状态 |
| EOF / Ctrl+C | 展示短退出提示并返回零状态 |
| Provider 无 reasoning / 空 delta | 不显示 Thinking；其余事件与 Answer 正常 |
| Tool / Retrieval failure | 关闭开放文本段并显示真实 normalized error；Agent 可恢复时继续后续事件 |
| Provider stream failure | 显示 terminal error、恢复完整终端行；不产生正式 answer completion/commit |
| 未知编程异常 | 不用 catch-all 静默吞掉，保留可诊断 traceback |
| semantic missing/stale/failed/partial | 保留原状态，不自动 rebuild 或 lexical fallback |
| legacy conversation 无 scope | 可列出但不可 resume，不猜测当前 scope |

### 5. Good / Base / Bad Cases

- Good：选择 `1` 后每轮 Request 的 scope 都是该 session；第二轮只有 conversation ID 变化。
- Base：选择 `0` 后每轮 Request 的 `allowed_session_ids` 都是 `None`。
- Bad：CLI 直接调用 Runtime、Capability、Retrieval、SQLite，或把模型 prompt 中的文字当作 scope enforcement。

### 6. Tests Required

- Parser 默认值与显式数据库参数；原有 import/trace/eval parser 回归。
- Application read facade 返回真实 session 且顺序稳定。
- 单 session scope、unrestricted scope、Query 调用、首轮/后续 conversation ID、`/new` 不改变 scope。
- `final_answer` / Trace projection、无 final answer 时不展示 runtime 原文。
- reasoning/content normalization、Renderer fragment 顺序、provider without reasoning、multi-tool、0 result、Tool/Provider failure 与 verbose metadata。
- Streaming 与 non-streaming 的 Conversation Assistant Answer 完整内容一致；Trace 保留 M6 事件且不持久化 reasoning/token delta。
- `/exit`、`/quit`、EOF、Ctrl+C 和已分类 Settings 错误。
- changed source 的 lint/type check 与完整测试集。
- Source summary/index、scope snapshot/mismatch、readiness、独立 feedback upsert、history/resume 与 product failure regression。

### 7. Wrong vs Correct

Wrong：`cli.py` 直接 `sqlite3.connect(...)` 或 `application.run_agent(...)`，再用 “只能查询某群” 的 prompt 约束模型。

Correct：`application.list_sessions()` 读取 metadata；CLI 构造可信 `ExecutionScope`，普通文本只构造 `QueryRequest` 并进入 `application.query()`，Capability 层继续执行 scope enforcement。

## Trace Text Log Export Contract

### 1. Scope / Trigger

Trace 需要被人工直接打开查看，或需要为既有 SQLite Trace 生成本地诊断文件时，新增文本日志必须是 canonical Trace 的 derived projection，不得创建第二套观测事件链路。

### 2. Signatures

- `TrivaeApplication.export_trace_log(trace_id: str, *, output_path: Path | None = None, view: Literal["transcript", "raw"] = "transcript", context_mode: Literal["delta", "full"] = "delta") -> Path`：读取 `StoredTrace` 并返回已写入日志的绝对路径。
- `trivae trace export <trace_id> [--database PATH] [--output PATH] [--view transcript|raw] [--context delta|full]`：导出既有 Trace；`--context` 只影响 transcript view。
- 默认输出：`<database_path.parent>/traces/<trace_id>.log`。
- `TraceTextLogWriter`：负责 UTF-8 文本格式、增量 sidecar 和完整重导出。

### 3. Contracts

- SQLite `traces` / `trace_events` 仍是 Trace source of truth；文本文件可删除、重建和覆盖，不参与 Query 事实读取。
- 文本内容只能来自已经经过 `CapturePolicy` 的 `NormalizedQueryEvent` / `StoredTrace`，保留 metadata、sequence、stage、operation、phase、outcome、duration、payload、limitations 和 failure。
- 默认完整导出的 `.log` 必须按 `Trace Metadata -> Trace Summary -> EXECUTION TRANSCRIPT` 排列，并在 `[FINAL ANSWER]` 后结束；Raw Events 不默认复制到 human-readable log。
- `trivae trace export --view raw` 才导出 `RAW TRACE EVENTS`；SQLite Trace 与 `trace show` 仍是 canonical raw event 的主要读取路径。
- Transcript 默认使用 `context_mode="delta"`：第一轮显示完整已捕获 model-visible input，后续只显示相对上一轮稳定前缀新增的 items；`--context full` 显示每轮完整已捕获 context，供需要核对 Provider request 的 Debug 排查使用。
- Summary、Transcript 和 Raw view 都必须是同一 `StoredTrace` 的纯 projection，不能查询 Conversation Store、Retrieval 或 Runtime 重新补内容。
- Debug Transcript 必须尽可能显示本轮实际 model input、assistant visible output、Tool Call arguments 和下一轮 input 中的 `function_call_output.output`；Tool Result 正文以模型实际看到的 output 为准，检索完整性 metadata 单独显示。
- `function_call` / `function_call_output` 以及 message content blocks 必须在 SDK adapter 内转换为 Trivae-owned plain data；禁止 `repr(item)`、无界 SDK dump、hidden reasoning、provider internal reasoning 或 SDK scratchpad 进入 Trace。
- 当前 CapturePolicy 上限为 Normal `512` 字符/`16` 个集合项/深度 `6`、Debug `20,000` 字符/`128` 个集合项/深度 `10`；截断必须保留 limitation，Debug 不是 Data Access Scope 或 secret policy 的旁路。
- `trivae chat` 在执行中流式展示正式答案 preview，Query 完成后展示 Trace ID 和日志路径；日志导出失败必须显式输出 `[trace log unavailable: ...]`，不能伪装成成功。
- 默认日志文件名拒绝路径分隔符；自定义 `--output` 仅表示用户明确指定的输出路径。

### 3.1 Human-readable Execution Transcript amendment

Debug Trace 的人工阅读目标是回答“这一轮模型实际看到了什么”，而不是推测模型可能看到过什么。`on_llm_start` 已完成 SDK input filtering 后的 `input_items` 是 model-visible input 的事实边界；Transcript 只能投影该字段和已经 normalized 的 execution facts。

当 SDK 将结构化 Tool Result 转成超长字符串且 bounded capture 在字典中间截断时，adapter 可以在同一 model input 字符串上生成 `output_projection`。该字段只是 Trivae-owned 的同源结构化投影，不能来自数据库重查或 Tool Result 重建；Transcript 仍以 `output` 原文为事实，并在可用时用该 projection 阅读正文，同时保留 truncation limitation。

完整 model-visible execution facts 不等于 hidden Chain-of-Thought。允许展示 Router reason、Planner output/failure、Tool selection/arguments、Retrieval diagnostics、Evidence/Citation diagnostics 和 finalization reason；禁止展示 provider hidden reasoning、SDK reasoning item、scratchpad 或未向应用层暴露的内部推理 token。

默认 human-readable log 是面向人工排障的紧凑主线，不通过删除 canonical facts 来实现体积控制：Raw Events 由 SQLite / `trace show` 保留，完整 model-visible context 由 `--context full` 显式查看。Delta presentation 只消除已确认的稳定前缀重复；无法确认前缀时必须显示完整已捕获 input 和 context note，不能猜测增量。

Normal 仍以 bounded/redacted execution facts 为主，不承诺完整 Transcript；Debug 才承担 Failure Case 的近完整 model input、Tool Result、assistant visible output 和 Final Answer snapshot。两者都必须复用同一个 CapturePolicy，Formatter 不重新实现 secret filter。

### 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| 新 Trace 的 SQLite event 写入成功 | 追加同一 event 的文本 projection |
| 既有 Trace 执行 `trace export` | 从 `StoredTrace` 完整重写文本文件 |
| Trace 不存在或 SQLite 读取失败 | 返回 `TraceStoreError`，CLI 输出 JSON error 并返回非零 |
| 文本目录、文件或 payload 写入失败 | Trace Store 记录 degradation；Application/CLI 显式展示导出失败 |
| Trace ID 含路径分隔符 | 拒绝默认文件名，不把 identity 当成目录 |

### 5. Good / Base / Bad Cases

- Good：默认 `trace export` 打开后从 Summary 顺着 Transcript 读到完整 Final Answer，且不出现 Raw Events；需要事件细节时 `--view raw` 与 `trace show` 仍能定位同一 sequence。
- Base：sidecar 丢失时再次执行 `trace export` 可以重建，不需要重新 Query、Retrieval 或调用 Provider。
- Bad：CLI 直接读 SQLite、从 runtime answer 重新拼日志，或把文本日志当作新的 Trace source of truth。

### 6. Tests Required

- `SQLiteTraceStore` 增量日志包含 event operation 和 terminal outcome。
- `TrivaeApplication.export_trace_log()` 支持 transcript/raw、delta/full 和自定义输出路径。
- `trace export` parser 接受 trace ID、database、output、view 和 context 参数；现有 `trace show` 保持可用。
- 默认 transcript 不含 `RAW TRACE EVENTS` 且在 Final Answer 后结束；raw view 保留完整 event projection；delta/full 都只读取 StoredTrace。
- Chat 输出 `[trace: ...]` 与 `[log: ...]`，导出失败时保留答案并显示诊断。
- 完整 `pytest`、`ruff check src tests` 和 `mypy src`。

### 7. Wrong vs Correct

Wrong：在 `cli.py` 里重新连接 SQLite、拼装 Trace 事件或直接读取 provider/runtime 原始结果生成日志。

Correct：`TrivaeApplication.export_trace_log()` 读取 `StoredTrace`，交给 `TraceTextLogWriter` 投影文本；CLI 只显示返回路径。

## Planner Utility 配对运行契约

### 1. Scope / Trigger

测量 `SoftPlanner` 是否改善 production Query 结果时，使用同一 Development Suite 的 forced standard / forced planned Variant；Router Provider 不作为处理变量。Router 诊断标签不能充当答案 GT。

### 2. Signatures

- `trivae eval --env-file PATH benchmark run --paired-by-case --database DB --evaluation-database NEW_DB --manifest ENV --suite SUITE --cases-dir CASES --variant STANDARD --variant PLANNED --output-dir NEW_DIR`：按 Case 顺序执行两路，默认 benchmark 顺序仍按 Variant 整批执行。
- `operational_measurements["planner"]`：由 normal Trace 的 `planner.started` 与 terminal event 投影 `called/status/latency_ms/provider/model/usage/step_count/suggested_tools/failure_category/failure_detail_code`；Trace 不可用时 `called=None`。

### 3. Contracts

- `forced_route` 由 QueryOrchestrator 绕过 Router decision；planned 调用现有 Planner 一次，两路使用同一个 Agent Runtime、Tool surface 与 finalization contract。
- benchmark run 在 Application 创建前拒绝已存在的 output directory 或 Evaluation SQLite；Provider settings 与 Environment gate 也必须在第一条 Case 前通过。从冻结 worktree 执行时显式给主仓库 `.env` 绝对路径。
- Paired run 的 `suite_id/version` 保留原 Suite 身份；`--paired-by-case` 仅改变运行顺序，不改 Case/GT、Provider、Retriever 或计划语义。smoke 与 targeted repeat 使用独立目录，不并入正式分母。
- Planner usage/cost 只读取 Provider 实际返回字段；`called=true` 与 Plan 被 Runtime 采用、答案改善是不同事实。

### 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| output 或 Evaluation DB 已存在 | 首个 Case 前报 `EvaluationContractError`；不覆盖旧产物 |
| Provider 缺配置或 Environment 漂移 | 首个 Case 前失败；不产生逐 Case 配置错误 |
| standard 无 Planner event | `called=false/status=not_called` |
| planned 有 started + completed/failed | 分别记录成功或失败、实测 duration 和可用 Provider metadata |
| Trace 缺失或 started 无 terminal | 标 `trace_unavailable` / `missing_terminal`，不伪造成功 |
| 单 Case Provider 异常 | 保留 Evaluation/Trace failure 和原始分母；不重试覆盖 |

### 5. Good / Base / Bad Cases

- Good：同一 Case 的 standard→planned 相邻执行，两个 Variant diff 只有 forced route，Trace 可证实 Planner 只在 planned 调用。
- Base：两路质量指标相同，但 planned usage/latency 增加；报告为已观测 overhead，不宣称答案语义完全相同。
- Bad：用 Jev route accuracy、Planner step 数、Tool sequence 改变或未校准 Judge 分数代替 answer-level utility。

### 6. Tests Required

- 单元测试断言配对顺序和 Suite identity；Planner Trace 成功、失败、未调用投影；create-only 入口在创建 Application 前拒绝旧目录/库。
- 真实运行核对 `raw/Evaluation/Trace` 数量、forced route、Planner invocation、Provider/Model、Snapshot/Environment；正式 denominator 与 repeat 分开。全仓 pytest、Ruff、mypy 和 Trellis validate 保持真实结果记录。

### 7. Wrong vs Correct

Wrong：Variant A 整批跑完后遇 Provider 故障，直接把 Variant B 的 failure 解释为 Planner regression；或覆盖旧结果重试直到成功。

Correct：使用 Case 邻接配对缩短时间漂移，保留 Provider failure attribution 与原始记录；只对有相同 GT 指标且可比较的 Case 判断质量方向。

## 代码评审

- 检查是否遵守本层各指南与工程原则。
- 检查是否涉及 Pending 架构事项（architecture.md）而未经授权自行决定。

## Pending architecture specification

- Evaluation 的具体实现框架、Case / Dataset Schema、runner、Review workflow、数值指标口径与 threshold；Stage 1.10 的 Case Bundle、Reference、Suite、Baseline、paired comparison 与 Review 治理语义已确认
- Stage 1.11 的 create_application / create_http_app 具体实现、QueryRequest 最终 Schema、CLI / API wire contract、Evaluation runner 与具体 package 文件；Application Boundary、Composition Root、统一 execution core、factory/lifecycle ownership、trusted context 与 package ownership 已确认
- 工具链具体选型（formatter / linter / test runner 版本与配置）

## 多来源 Evaluation Snapshot 与 CJK 字面 Oracle（2026-10-20）

### 1. Scope / Trigger

真实80来源快照暴露结构化身份超过4000字符；真实聊天NUL暴露LIKE不适合作完整正文Oracle。用于后续Snapshot序列化或字面检索实验。

### 2. Signatures

`DatasetSnapshot.from_database(path)`、`DatasetSnapshot.from_dict(value)`、`EvaluationCaseBundle.from_dict(value)`保持原接口；`source_identity`、`canonical_database_identity`、`deterministic_fingerprint`仍为完整字符串身份。

### 3. Contracts

结构化身份不能套用正文展示的4000字符上限，也不能截断后比较。普通snapshot_id等短标识继续使用原长度契约；字段类型与非空要求不变。Snapshot/Case的from_dict应让各字段及嵌套contract执行其所属校验。完整正文的ASCII大小写不敏感字面Oracle采用`instr(lower(content_text), lower(?)) > 0`，不把FTS的token/分隔符匹配声称为任意子串匹配。

### 4. Validation & Error Matrix

- 80个合法来源导致身份增长：成功构造并无损round-trip；身份字段不是正文。
- 非字符串/空身份：继续显式EvaluationContractError；普通snapshot_id超限仍报错。
- 文本含NUL：LIKE可能漏掉NUL后段，不能作为该正文的穷举真值；应单独冻结修正版Oracle，保留旧证据。
- 无人工审核：保持非human_verified；来源存在不代表答案语义与引用正确。

### 5. Good / Base / Bad Cases

Good：同一个快照、Query和Scope下先冻结完整正文Reference，再运行A/B及生产parity。Base：无NUL的字面匹配保持原口径。Bad：看到Candidate额外命中就全部标错、改题，或截短Snapshot身份绕过构造错误。

### 6. Tests Required

`test_cjk_benchmark.py`覆盖80来源真实构造和Case round-trip、普通标识超限、NUL后的完整字面串、mixed空格额外匹配、空Reference分母、forward Scope/preview排除及实验A不伪造生产metadata。

### 7. Wrong vs Correct

Wrong：将`LIKE '%词%'`无条件视为完整正文穷举，或把索引hit数称为Agent准确率。Correct：检验Oracle适用范围；同一Query分别报告top10、全深度字面覆盖、误匹配、真实Agent与审核状态。完整证据见[实验报告](../../../evaluation/experiments/cjk-bigram-v1/report.md)。

## 历史失败驱动的当前快照配对实验（2026-10-20）

### 1. Scope / Trigger

重放历史Case时，代码、Provider或数据已有变化；需要明确当前Baseline与单一treatment，不把历史分数直接当修复前值。

### 2. Signatures

`evaluation_quality_experiment.py --database DB --semantic-index INDEX --cases-dir DIR --case ID --arm baseline|candidate --output NEW_DIR --budget-ledger LEDGER`复用生产Application与EvaluationRunner。`--prompt-treatment`须同时指定candidate与`--baseline-dir`。`evaluation_quality_report.py --root PRIVATE_DIR [--public-output SUMMARY]`只读原始产物并生成既有Tier1与ReviewPacket。

### 3. Contracts

- Snapshot变化创建独立Case身份，保留历史provenance；新快照适用性未人工审核时保持pending。
- 固定七工具、Standard override、生产预算与官方Flash；实验CLI不覆写Prompt或增加重试。
- 全局HTTP账本在实际httpx2单次发送前持久化debit，包含失败和SDK尝试，120封顶；不能换批次清零。
- 默认所有条件严格相等，仅arm/执行commit不同；显式Prompt实验只允许基础Prompt前缀变化，动态instructions后缀及工具/模型/Case/索引/预算仍相等。保存真实diff。
- 从实际import的源码工作树记录commit；独立验证使用冻结A/B源码。临时worktree放仓库外，避免pytest递归收集第二份tests。
- 统计分母先固定；未跑/失败不剔除。来源可解析率、目标Evidence覆盖、必要事实与claim引用支持分别报告，未审核维度不默认pass。
- 历史Prompt删减候选和行号矩阵对照其冻结源码fixture；不得为匹配新生产Prompt而改写历史实验产物。

### 4. Validation & Error Matrix

| 条件 | 结果 |
|---|---|
| Snapshot/非treatment条件漂移 | 首次发送前失败 |
| 未声明Prompt treatment但基础文本改变 | 拒绝 |
| 声明Prompt treatment但动态后缀/工具预算改变 | 拒绝 |
| 已有output或总账本上限改变 | 拒绝覆盖/重置 |
| 传输失败/预算耗尽 | 保留发送事实、失败或not_run_budget，不重试补齐成功 |
| Trace导出失败 | 单列artifact_capture_error，不覆盖已完成Query事实 |

### 5. Good / Base / Bad

Good：历史失败定位→新快照Baseline→单变量Candidate→冻结后调参外验证；Base：全部完成但目标仍遗漏，保留负结果并拒绝Candidate；Bad：仅凭更多链接、合法引用或某条旧target命中便声称质量提升。

### 6. Tests Required

`test_evaluation_quality_experiment.py`覆盖真实Application/Runner装配、请求发送边界、失败debit、共享上限、条件前缀与动态后缀差异。真实实验核对raw/Evaluation/Trace/Artifact/HTTP身份；报告脚本复用原生指标与ReviewPacket，不用模拟运行替代真实质量结论。

### 7. Wrong vs Correct

Wrong：对已冻结的历史候选继续与可变`SYSTEM_PROMPT`逐字比较，或把引用存在等同支持。

Correct：对原实验源码fixture保持同样逐字断言；新实验另行冻结，按实际附带来源核验必要事实与引用，并保留pending。
