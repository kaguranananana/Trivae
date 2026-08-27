# Implement: ordered checklist

## Phase 1 — Failure B (lexical, 独立可验证)

- [ ] 1.1 `src/trivae/data/storage/sqlite_lexical_text.py`：normalize 函数 + STRATEGY_ID（纯函数，含 Han run 检测）
- [ ] 1.2 `tests/test_lexical_text_normalization.py`：bigram 生成、单字、混合 CJK+ASCII、ASCII/URL/code 不变性、query/doc 同函数一致性
- [ ] 1.3 `sqlite_lexical.py`：rebuild 用 normalize + derived meta 表写入 strategy id；drop 清理
- [ ] 1.4 `sqlite_read.py`：`_fts_match_expression` 归一化 terms；`_ensure_lexical_index_ready` 校验 strategy
- [ ] 1.5 复现脚本转正式测试 `tests/test_chinese_lexical_regression.py`：
  - 构造 "真心推荐 值得看一看"/"我推荐这个项目"/"推荐"/"不相关消息" → rebuild → lexical_search("推荐") 命中前两条
  - Chinese substring/full token、ASCII word、GitHub URL、repo name、ImportError、foo_bar、DeepSeek Harness、mixed 中文+ASCII、punctuation
- [ ] 1.6 stale detection 测试：旧 strategy / 缺 meta 表 → LexicalIndexError
- [ ] 运行 `uv run pytest tests/test_lexical_retrieval.py tests/test_sqlite_read.py tests/test_chinese_lexical_regression.py tests/test_lexical_text_normalization.py`

## Phase 2 — Failure A (get_recent_messages)

- [ ] 2.1 limits.py: DEFAULT_RECENT_MESSAGES_LIMIT / MAX_RECENT_MESSAGES_LIMIT(=MAX_STRUCTURED_RESULT_ITEMS)
- [ ] 2.2 structured.py: CanonicalReadRepository.read_recent_messages protocol + SQLiteCanonicalReadRepository 实现；StructuredRetrieval.retrieve_recent_messages
- [ ] 2.3 contracts.py: GetRecentMessagesInput
- [ ] 2.4 capabilities/recent_messages.py: GetRecentMessagesCapability（scope 继承/越权拒绝/relative resolve）
- [ ] 2.5 tools.py: RecentMessagesTool(+payloads/meta)；registry.py union
- [ ] 2.6 application.py 注册；query/contracts.py 默认 capability 白名单追加
- [ ] 2.7 openai_tools.py: GetRecentMessagesSDKToolAdapter；openai_adapter._build_agent 分支
- [ ] 2.8 prompt.py: tool selection boundary 段落重写
- [ ] 2.9 tests:
  - test_capabilities.py 风格新增 recent contract 用例（time_range resolve archive_latest/explicit ts/reversed/limit 越界/scope 越权/zero ok）
  - test_structured_retrieval.py 新增 ordering semantics（m1..m4 limit=2 → m3,m4 ascending; total; truncated; identity stable）
  - test_agent_tool_surface.py 新增 schema/description/trusted scope/envelope 断言
- [ ] 运行相关测试

## Phase 3 — Tool Selection Regression (确定性, 无 keyword router)

- [ ] 3.1 模型无关层：QueryRequest 默认白名单与 prompt 文案回归断言（temporal overview guidance 存在且 get_recent_messages 描述先行）
- [ ] 3.2 Evaluation case 文件 `evaluation/cases/temporal-overview-v1.json` + suite 追加（不硬编码主题名）

## Phase 4 — 全量质量门

- [ ] 4.1 `uv run pytest`（全量）
- [ ] 4.2 lint/typecheck（检查 pyproject scripts）

## Phase 5 — 真实 Smoke（真实 provider + data/trivae.sqlite3）

- [ ] 5.1 对真实库执行 lexical index rebuild（strategy v1）并记录 stats/latency
- [ ] 5.2 Smoke A: TUI/CLI 查询 "最近一两天大家都在讨论什么有价值的内容"；记录 trace_id/tool sequence/tool calls/model turns/latency/terminal outcome/final answer/citations；验证首 tool call = get_recent_messages
- [ ] 5.3 Smoke B: CLI/TUI lexical_search("推荐")（same session/time scope）；确认召回窗口内 hit（含 qq:1039179741:7674201141965536638），记录 returned/total/source_id/provenance/coverage
- [ ] 5.4 Trace 文件核对（data/traces/*.log）：get_recent_messages 的 resolved range/returned/total/truncated/projection truncation 可观察

## Phase 6 — ADR / interview-defense / 收尾

- [ ] 6.1 更新 stage-1-4-tool-capability-layer.md：§11 reopen 记录（trace id、before 数据、新决策 §19）
- [ ] 6.2 interview-defense 文档沉淀（十问）
- [ ] 6.3 journal/spec update 视情况
- [ ] 6.4 git add 有意文件 → commit → 工作树 clean

Validation commands:
```bash
uv run pytest tests/test_lexical_retrieval.py tests/test_chinese_lexical_regression.py
uv run pytest tests/test_structured_retrieval.py tests/test_capabilities.py tests/test_stage_b_tools.py tests/test_agent_tool_surface.py
uv run pytest
```
