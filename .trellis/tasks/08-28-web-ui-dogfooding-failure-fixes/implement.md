# Implementation plan

## Phase 0 — planning gate

- [x] 创建 Trellis complex task。
- [x] 阅读项目 workflow、backend/project spec、既往 Web/temporal/streaming Failure 记录。
- [x] 完成真实环境只读基线：数据库规模、readiness、页面 DOM、console 初始状态和质量门。
- [x] 写入 `prd.md`、`design.md`、研究矩阵。
- [x] 向用户提交规划摘要，获得明确批准并取得第一次真实 Provider 查询的 action-time confirmation。
- [x] 在批准后执行 `python3 ./.trellis/scripts/task.py start`，进入实现阶段。

### Planning addendum — Final Answer Quality / Depth

- [x] 读取 Trivae final synthesis prompt、ModelAnswerClaim/AnswerContentBlock/Host compile/finalizer、Tool Result projection、Trace 和 Web answer renderer 的当前实现。
- [x] 直接读取 ChatLab 当前仓库的默认中文回答 prompt、tool result/evidence 结构、Agent final answer 链路和 EvidenceBlock/ChatMessage renderer；结论与待验证假设写入 `research/final-answer-depth-audit.md`。
- [x] 在真实 Web UI 中执行七类复杂问题，选择证据较丰富的 Case，同时记录 retrieval volume、model-visible volume、projection truncation、candidate claims、claim text、final artifact 和 DOM。
- [x] 对可复现 Case 在 ChatLab 运行相同问题与数据范围，比较有效 finding 覆盖、具体性、上下文、资源/URL、差异、限制和 source/citation，不以字数作唯一指标。
- [x] 在真实证据前生成并展示 3–5 个可证伪根因假设；按 A–G 顺序逐层排除，禁止先改 Prompt。

## Phase 1 — real browser exploration

- [x] 复用同一个 `trivae web` 和 in-app browser tab；记录 server URL、readiness 和浏览器初始 console/network 状态。
- [x] 按 `research/exploratory-matrix.md` 执行 20 个自然问题，覆盖 T/L/S/M/C 分组；每次只记录 bounded evidence。
- [x] 完成已执行的 UI/lifecycle 检查：scope、输入键盘、流式过程、Sources/context、Trace、Stop、切换、刷新和多轮恢复；未实际执行的 rename/delete 不在本轮宣称通过。
- [x] 为已确认 Failure 创建 `research/failure-*.md`；未复现的风险只列为观察项。
- [x] 为 Answer Quality / Depth 每个 Case 建立 bounded 表格：`query_label`、`trace_id`、retrieved/projected/omitted/truncated、candidate claim count/text lengths、answer structure、finding/source coverage、重要遗漏和 ChatLab 对照。

## Phase 2 — reproduce and locate root cause

- [x] 从真实浏览器证据回放最小步骤，复查对应 NDJSON、Conversation、Trace 和代码路径。
- [x] 明确根因分类、触发条件、影响范围和为何 Answer Depth Failure 不是 Provider/数据本身；独立 Provider Failure 另行记录。
- [x] 先写最小失败回归测试，测试真实失败的契约边界；不修改既有测试来规避实现问题。
- [x] 对“证据充分但答案简单”的最小 Case 建立 red semantic/prompt regression：多个独立正文与 citation 必须保留，不使用固定字数断言。
- [x] 明确比较 provider candidate、`AnswerContentBlock.text`、`answer.completed` 与 DOM，确认问题在 C/D，而不是 E/F；Provider 空 final 单独映射为透明 Runtime failure。

## Phase 3 — minimal implementation

- [x] 只修改根因所在的最小层，保持既有 Application/Query/Runtime/Retrieval/Trace 单一链路。
- [x] 新增/修改代码包含简体中文注释；关键逻辑按项目约定逐行解释。
- [x] 不增加无证据 fallback、降级、兼容分支、静默 catch、重试或单样例特判；空 final 映射是被真实 Failure 证明必要的透明错误修复。
- [x] 对每个已处理修复更新对应 `research/failure-*.md` 的根因、变更和回归结果。
- [x] Prompt 修复分离“bounded Evidence/Citation bookkeeping”与“自适应用户可见回答深度”；不强制固定 claim/section/字数，不把所有 query 改成 verbose。
- [x] Candidate 结构耦合已确认但未命中硬上限，因此保持 current-run provenance、citation binding、scope enforcement、coverage、partial propagation 和 trusted hydration，不做无证据 schema 重构。
- [x] AQ3 资源/GitHub 清单加入明确的 retrieval precedence：即使问题包含“最近”，也先用
  `lexical_search(github.com)`，避免把宽泛 recent 快照与 URL 检索合并后送入超大 synthesis context。
- [x] AQ4 暴露 `get_recent_messages.sender_user_ids`，并让 canonical sender scope 贯穿 Input、archive anchor、
  cursor continuation、Structured retrieval、SDK schema、Trace projection 和 Prompt guidance。
- [x] 为 Provider 边界补充 bounded response/transport shape Trace 和对应回归；记录 finish/status/usage/空文本
  shape，而不保存 Provider 正文或 hidden reasoning。

## Phase 4 — verification

- [x] 运行 Failure 对应的定向 Python 测试和真实 Web 重测。
- [x] 运行完整质量门：`uv run pytest -q`、`pnpm -C web test`、`pnpm -C web typecheck`、`pnpm -C web lint`、`uv run ruff check src tests`、`uv run mypy src`、`python3 -m compileall -q src tests`、`git diff --check`、`pnpm -C web build`。
- [x] 重启真实 Web server，按原始 Failure 步骤在浏览器复测；确认 readiness、Trace、finalizer、answer.completed 和 DOM 一致。
- [x] 复测原始 Answer Quality Case，并确认简单 yes/no 问题仍可简洁回答；报告调整前后实际回答的有效信息覆盖和 citation/limitation 变化。
- [x] 核实 Trellis 脚本实际命令；当前版本没有 `task.py check`，使用
  `uv run python .trellis/scripts/task.py validate .trellis/tasks/08-28-web-ui-dogfooding-failure-fixes`，结果通过。
- [x] 实现改变了项目长期契约，已更新 `.trellis/spec/backend/agent-runtime-guidelines.md`，明确用户正文深度与 Evidence/Citation metadata 的职责边界。

## Phase 5 — handoff

- [x] 汇总已修复 Failure、未修复但有证据的环境问题、真实查询覆盖和质量门结果。
- [ ] 向用户展示最终变更/验证摘要；得到提交计划确认后再提交代码。
- [ ] 按 `trellis-finish-work` 收尾并归档任务；报告可回滚点和仍存在的明确限制。

## 预期验证命令

```text
uv run pytest -q
pnpm -C web test
pnpm -C web typecheck
pnpm -C web lint
uv run ruff check src tests
uv run mypy src
python3 -m compileall -q src tests
git diff --check
pnpm -C web build
```

所有命令均应在实现后按风险执行；真实 Provider 查询不被这些离线质量门替代。
