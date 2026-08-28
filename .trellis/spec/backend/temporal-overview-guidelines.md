# Temporal Overview Retrieval Guidelines

`get_recent_messages` 是 broad temporal browsing 的实现级 contract。它只负责在
Host 解析的时间窗口内读取 canonical message candidate；主题归纳、价值判断和语义
正确性仍由 Agent / Evaluation 边界负责。

## Scenario: bounded temporal browsing

### 1. Scope / Trigger

- Trigger：真实 Trace `trace-3ca9975108534180b73ce7f518d7c1c4` 在两天窗口内统计到
  `2699` 条消息，但旧实现只返回 `100` 条并把尾部样本当成全窗口概览。
- Scope：`capabilities`、`retrieval`、SQLite read adapter、Tool Result projection、
  Evidence/Answer Artifact、Runtime、Trace、Conversation codec 与 CLI/Web projection。
- Explicit non-scope：不提高通用 structured/semantic 上限，不取消 Tool Result token budget，
  不把模型正文当作时间事实，不新增 retry/fallback 或独立 Workflow executor。

### 2. Signatures

```python
@dataclass(frozen=True)
class GetRecentMessagesInput:
    time_range: RelativeTimeRange | Mapping[str, object] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    session_ids: tuple[str, ...] | None = None
    limit: int = 1_000
    cursor: RecentMessagesCursor | Mapping[str, object] | None = None

class RecentMessagesCapability:
    def execute(
        self, request: GetRecentMessagesInput, scope: ExecutionScope
    ) -> StructuredMessageResult: ...
```

- `DEFAULT_RECENT_MESSAGES_LIMIT = 1000`，`MAX_RECENT_MESSAGES_LIMIT = 5000`。
- 通用 `MessageQuery` 继续使用 structured `100` 上限；lexical/semantic 预算不因本 contract 改变。
- Tool Result token budget 是独立边界，当前默认 estimate 为 `16000`；它不改变 canonical
  retrieval 的 `total_hits`。
- continuation cursor 的排序键为
  `(timestamp ASC, present-seq ASC, missing-seq-after-present, seq ASC, internal_message_id ASC)`。

### 3. Contracts

#### Request

- 无时间参数等价于 `relative 2 day, anchor=archive_latest`；`archive_latest` 必须从当前
  trusted session/time scope 的 canonical store 求得，不使用 machine current time。
- `time_range` 与 absolute `start_timestamp/end_timestamp` 互斥；cursor 与新的相对时间范围互斥。
- cursor 只能原样回传；它携带上一页的 absolute half-open window、session scope 和排序位置。
- 所有 timestamp 均为 canonical integer milliseconds；时间比较为 `[start, end)`。
- `limit` 必须为正整数且不超过 `5000`；同时受 trusted `ExecutionScope.max_results` 硬约束，超出时显式报错，不静默裁剪。

#### Response / Artifact

- `StructuredMessageResult` 必须提供 `total_hits`、`returned_count`、`coverage`、`partial`、
  `truncated`、`has_more` 和 `next_cursor`（后四项进入 metadata/envelope）。
- `coverage.status=partial` 当且仅当当前 scope 仍有可继续读取的消息；完整页为 `complete`。
- `coverage` 的 `covered_units/eligible_units/unit=message` 与 `retrieved_count` 使用同一 scope 口径。
- Tool Result record 同时保留 canonical `retrieved_count` 与 model projection 的
  `projected_count/omitted_messages/model_projection.truncated`。
- `AnswerArtifact` 由 Host 写入 `resolved_time_range` 与 `retrieval_coverage`；final answer
  不得从模型自行提交的日期或 coverage 取代这两个字段。
- 同一 Host-resolved 时间窗允许多次独立 root recent 查询；最终 Artifact 选择已经证明的最大
  `covered_units` 状态，较晚的小 root 样本不得降低更强 coverage。`retrieved_count` 仍按当前 Run
  唯一 message ID union 计算，且 basis、unit、eligible units、时间窗与单记录内部事实继续校验。
- `resolved_time_range` 保留 integer millisecond boundary、UTC 文本和 half-open interval；
  citation message timestamp 必须落在同一窗口内。

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| recent `limit <= 0` 或超过 5000 | Capability contract error；不查询第一页 |
| 通用 structured query 超过 100 | 仍由 `InvalidRetrievalQuery` 拒绝；不得同步放宽 |
| cursor 与 time_range/不一致的 absolute boundary/session | Capability contract/scope error；不得重新锚定第一页 |
| cursor 的 resolved UTC 文本被修改 | Capability contract error；不得信任模型字段 |
| recent page `count/read` 不一致 | Retrieval error；不得用 partial 掩盖 repository bug |
| `total_hits > returned_count` 且无 next cursor | Retrieval/coverage error；不得标记 complete |
| recent record 缺 coverage、同窗 eligible units 冲突、唯一消息 union 超过最大已证明 coverage 或单记录内部 count/status 冲突 | `COVERAGE_MISMATCH`；不得进入 graceful recovery |
| citation 越过 Host half-open window | `TIME_RANGE_MISMATCH`；不得删除 citation 后继续提交 |
| Tool Result token budget 不足 | projection 显式记录 omitted/truncated；canonical retrieval facts 保留 |
| complete zero-result | 仅在成功、无 facts、无 incomplete limitation 时允许 `kind=no_result` |

### 5. Good / Base / Bad Cases

- Good：2699 条窗口按 `1000 + 1000 + 699` 继续读取，页间无 overlap/gap，末页
  `coverage=complete`；Artifact 记录 `retrieved_count=2699`。
- Good：低密度或空窗口 `returned_count == total_hits`、`coverage=complete`，空窗口仍可通过
  positive-proof no-result contract。
- Base：单次 `limit=1000` 返回 `partial`，模型可见 projection 因 16000 token budget 只显示
  部分消息，但 Trace 同时记录 canonical 与 projected 数量。
- Bad：只把 `MAX_RECENT_MESSAGES_LIMIT` 改成 5000，却没有 `has_more/next_cursor`，然后让模型
  把尾部 1000 条写成整个窗口总结。
- Bad：继续使用当前时间或把毫秒时间戳交给模型自行计算日期，造成六月/八月错配。

### 6. Tests Required

- Capacity：`test_get_recent_messages_default_limit`、`test_get_recent_messages_hard_cap`、
  `test_recent_messages_does_not_reuse_structured_limit`，断言 `1000/5000/100` 三条边界。
- Coverage：large/total/partial/complete、empty-window complete、Artifact
  `retrieval_coverage` serialization、complete root 后独立 smaller root，断言
  total/returned/covered/eligible/has_more 与唯一消息 union。
- Continuation：`test_recent_messages_cursor_no_overlap`、`..._no_gap`、
  `..._same_timestamp_deterministic_order`、scope/window tampering，断言 keyset 页序列。
- Projection：canonical 500/1000/2699 与 model projected/omitted/token estimate 分离；Trace
  payload 不复制完整消息正文。
- Time/Evidence：archive_latest、UTC/毫秒一致性、citation half-open boundary、
  `TIME_RANGE_MISMATCH`/`COVERAGE_MISMATCH` 不被 recovery 吞掉。
- Regression：lexical、semantic、structured、SQL、context、runtime、Trace、CLI/TUI/Web、
  Conversation codec 与 no-result 全量回归。

### 7. Wrong vs Correct

#### Wrong

```python
messages = repository.read_messages(MessageQuery(limit=100))
return StructuredMessageResult(
    messages=messages,
    total_hits=2699,
    coverage=Coverage(status="complete", basis="canonical_store"),
)
```

#### Correct

```python
page = repository.read_recent_messages(RecentMessagesQuery(limit=1000, before_cursor=cursor))
has_more = remaining_hits > len(page)
next_cursor = make_host_cursor(page[0]) if has_more else None
return StructuredMessageResult(
    messages=page,
    total_hits=total_hits,
    returned_count=len(page),
    coverage=Coverage(
        status="partial" if has_more else "complete",
        basis="canonical_store",
        covered_units=covered_units,
        eligible_units=total_hits,
        unit="message",
    ),
    partial=has_more,
    truncated=has_more,
)
```

正确路径要求 Host 保存同一 resolved range/cursor/coverage 到 Tool Result、Trace、Evidence
和 Answer Artifact；模型只消费并原样回传 continuation facts。
