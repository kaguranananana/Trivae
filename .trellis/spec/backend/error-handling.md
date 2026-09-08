# Error Handling

> 错误处理长期原则（源自工程原则第 1、3 节）。
> Stage 1.9 已确认跨层 Error Code ownership 与 Failure Attribution 原则；M6 已落地 Trace failure attribution 与 safe `TRACE.*` diagnostics，完整 user-facing Exception/API mapping 仍待实现。

---

## 核心原则

1. **根因优先**：异常 → 先复现、定位根因、修复主链路；不掩盖问题。
2. **错误显式暴露**：禁止静默吞错（silent error swallowing）；错误必须可见、可定位。
3. **最小修复**：不做超出根因范围的改动，不加无依据的分支。

## 禁止

- `except Exception: pass`（或等价静默吞错）。
- 用 fallback / 兼容分支 / 启发式后处理掩盖主链路问题。
- 针对单个样例的特殊规则。

## 异常包装必须保留根因文本

把底层异常转换为项目错误类型时（`raise ProjectError(...) from exc`），新 message 必须包含原始异常的完整 `str(exc)`，不得只记录 `type(exc).__name__`。原因：Tool Result / Trace 只投影最终 message，丢失原文会让网络瞬态、缓存损坏、配置错误等不同根因在日志中不可区分，只能靠事后复现定位。

- 推荐格式：`f"...: {type(exc).__name__}: {exc}"`；保留 `from exc` 维持异常链。
- 失败路径测试断言注入异常的原始文本出现在转换后 message 中，而非只断言异常类型。
- 参考实现：`src/trivae/retrieval/semantic/embedding.py`（2026-08-27 `SEMANTIC_EMBEDDING_FAILED` 排障教训：trace 中只剩 `ValueError` 类名，根因不可判读）。

## Retry / Fallback（默认不加）

仅当真实 Failure Case 证明存在可恢复的 transient error（外部 API 短暂失败、网络抖动、模型偶发格式错误）时才引入。引入必须说明：

- 触发条件
- 为什么主链路无法直接解决
- 最大次数 / 边界
- 失败后如何暴露错误
- 测试覆盖
- 相关指标

## 架构级错误处理

已确认：

- 首个破坏本层 contract 的组件拥有 Error Code；Wrapper 跨层传播时不得改名覆盖根因。
- Failure Attribution 区分 `origin_stage`、`observed_stage`、handling 与 Query terminal outcome。
- Router / Planner degradation、Tool Contract Error、Runtime Failure、User Abort 与 Budget exhaustion 分开表达。
- 未分类 Tool / Adapter 异常不得转换成 generic model-visible Tool Error 来吞掉实现缺陷。

仍 Pending：

- 具体异常类型体系、完整 Error Code 枚举与 Exception mapping
- user-facing error message 与 API mapping
- 更完整的 user-facing logging/API mapping 与部署级 Trace payload retention policy

## Evaluation closure and provider session contract

### 1. Scope / Trigger

触发条件是 Benchmark Gate 3 收尾、冻结后 holdout 一次运行、dev/holdout 报告合并，或 Judge 暴露
provider/session/budget 根因。该契约只约束 Evaluation 生命周期与 provider 边界，不改变 Query、Retrieval
或指标语义。

### 2. Signatures

```python
async def run_benchmark_async(
    *,
    application: TrivaeApplication,
    database_path: Path,
    manifest_path: Path,
    suite: EvaluationSuite,
    cases_dir: Path,
    variant_paths: tuple[Path, ...],
    output_dir: Path,
    repetitions: int = 1,
    holdout_sealed: bool = False,
) -> dict[str, object]: ...

def capture_final_freeze(...) -> BenchmarkFinalFreezeRecord: ...
def register_holdout(...) -> HoldoutRegistrationRecord: ...
def begin_holdout_run(...) -> tuple[Path, HoldoutRunClaim]: ...
def merge_reports(...) -> dict[str, object]: ...
```

CLI 子命令固定为 `freeze-final`、`seal-holdout`、`run-holdout` 和 `merge-report`；Judge 的 provider
调用必须接收同一 Run 的 `session_id`。

### 3. Contracts

- OpenCode Go 的每个 OpenAI-compatible client 发送稳定 `x-opencode-session` 和
  `User-Agent: trivae/0.1.0`；Judge 发送 Run 级 session，production runtime 与 retrieval annotator
  使用各自稳定的本地 session。
- `BenchmarkFinalFreezeRecord` 固定 benchmark、git commit、Snapshot、lexical/semantic identity、按
  Suite 顺序的完整 Development Case 配置和 Variant fingerprint；`resume-benchmark-v1` 必须包含五个
  Variant。
- `HoldoutRunClaim.status` 只能是 `started`、`completed` 或 `failed`；中断保留 `started`，普通异常记录
  `error_type` 与完整 `error` 文本，不能自动重试或改用另一个 output directory。
- holdout report 只有 `holdout_sealed=true` 才能合并；dev/holdout identity 一致时从 raw records 重新构建
  `full`，不一致时保留两个 split 且 `full` 为 `unavailable`。
- Benchmark CLI 的 `run` / `run-holdout` 必须在创建 Application、写入 claim 或遍历 Case 前调用
  `load_settings()` 做 Provider 配置预检；从冻结 worktree 执行时由 `trivae eval --env-file PATH benchmark ...`
  显式注入配置。默认 dotenv 仍只读取当前目录，不向父目录搜索，也不通过 retry/fallback 掩盖缺配置。
- Judge 的 JSON 输出使用 final output budget（`ModelSettings.max_output_tokens`），不能误用
  Router/Planner 的 `completion_max_tokens`。

### 4. Validation & Error Matrix

| 条件 | 行为 |
| --- | --- |
| Environment、Snapshot、git commit 或 Variant 漂移 | 在首次 provider 请求前抛出 `EvaluationContractError` |
| Case 未人工 adjudicated、split 错误或与 Development 重叠 | freeze/registration 失败 |
| claim 已存在、结果 artifact 已存在或 output directory 被替换 | 显式拒绝，不覆盖原文件 |
| holdout claim 不是 completed 或 report 未 sealed | `merge-report` 失败 |
| dev/holdout report identity 不一致 | split 保留，`full` 标记 `identity_mismatch` |
| provider exception、空 JSON、JSON 截断或证据 Tool error | 当前 Judge item 为 `judge_failed`，保留异常类型与原因；批次 `status=partial`、CLI 非零 |
| 已有 Judge JSON 损坏 | 拒绝读取和覆盖，保留原文件 |

### 5. Good / Base / Bad Cases

- Good：先 Gate 3 freeze，再登记 holdout；第一次请求前创建 `started` claim；完整写出 sealed report 后迁移为
  `completed`，最后才允许 merge。
- Base：dev/holdout 的历史输出可以单独读取；没有 `full` 时报告明确写出 unavailable，不补造指标。
- Bad：用空 evidence 继续 Judge、把 `finish_reason=length` 当成低质量答案、用第二个 output directory 绕过 claim，
  或把不一致的两个聚合百分比平均成 full。

### 6. Tests Required

- closure 单元测试覆盖 freeze round-trip/git drift、holdout registration、claim 重复拒绝、sealed report 检查、
  同身份 full 与异身份 unavailable。
- Judge 回归测试断言证据 Tool error、provider 原文、损坏 JSON、partial exit code、OpenCode Go headers 和
  final output budget。
- CLI help 必须出现四个 closure 子命令；`pytest -q`、`ruff check src tests`、`mypy src` 与 `git diff --check`
  全部通过。

### 7. Wrong vs Correct

Wrong：

```python
try:
    response = await judge_provider(...)
except Exception:
    response = "{}"
```

Correct：

```python
try:
    response = await judge_provider(...)
except OpenAIError as exc:
    raise EvaluationContractError(
        f"benchmark judge provider failed: {type(exc).__name__}: {exc}"
    ) from exc
```
