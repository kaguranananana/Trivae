# 研究状态（Agent Quality Research 2026-10-29）

分支：`research/agent-quality-20261029`（自 main 创建）。状态目录：`research/agent-quality-20261029/`。

## 当前进度

- 2026-10-29 Setup 轮完成：分支与状态目录就绪，四个状态文件（budget.json / LEDGER.md / STATE.md / QUESTION_POOL.md）已建立，测试命令与评测入口已验证，环境事实已记录。尚未开展任何真实模型请求。
- 2026-10-30 整合轮完成：四路勘察（①代码链路静态阅读 ②prompt-ab-eval-v1-20261029 数据梳理 ③历史负结果与工程约束 ④Case 02/04/05/15 共 16 运行六阶段 trace 定位）已整合为 QUESTION_POOL.md 的 Q1–Q13，并对其承重引用做了抽查复核（见「已验证结论」）。问题池含排除方向清单（13 类历史负结果方向不入池）。本轮未发出任何真实模型请求，预算未动。问题池指针：`research/agent-quality-20261029/QUESTION_POOL.md`。

## 已验证结论

（只记录本实验条件下真实跑过、有命令输出佐证的结论；注明验证命令与日期）

- 2026-10-30 Case 15 目标消息不在三次新增运行的 trace 中：`grep -c "7698750208906130992"` 于 `data/evaluation/prompt-ab-eval-v1-20261029/A/agent-runs/cap1-15-open-source/run-02/traces/trace-001.json`、`B/agent-runs/cap1-15-open-source/run-01/traces/trace-001.json`、`B/agent-runs/cap1-15-open-source/run-02/traces/trace-001.json` 均输出 0（文件存在、0 命中）。支撑 Q1-H1。
- 2026-10-30 A/B 聚合指标复读（`python3` 读 `data/evaluation/prompt-ab-eval-v1-20261029/metrics.json`）：effective_completion A/B = 9/32（0.28125）；key_fact_coverage_case_equal_weight A=0.528125 / B=0.459375；relative_change.completion=0.0、coverage=-0.13018；repeat_completion_agreement=0.625；repeat_fact_coverage_jaccard=0.703125；new_agent_attempts 44 尝试 / 42 有效 / 2 失败；new_agent_usage_including_failures.requests=185 ⇒ **1 次运行尝试 ≈ 4.2 次 DeepSeek 请求**（预算换算参考，非今晚账目）。
- 2026-10-30 coverage-assessments.json 02b 条目（`python3` 定位读取）：requirement 为「Distinguish turning old-login behavior into a fast test as a forwarded recommendation, not a proven universal fix」，4 臂全 uncovered，rationale 写「均未报告『把旧登录行为变成快速测试』这一转述建议」——rationale 措辞（未报告内容）与 requirement 实质判据（来源属性区分）不一致，而勘察四观察到 B1 claim-6 近乎逐字复述该内容且绑定 e6。支撑 Q3 / Q4-H3。
- 2026-10-30 代码静态抽查（分支 research/agent-quality-20261029，Read/grep 核验勘察一引用）：`src/trivae/query/runtime/openai_tools.py:90-94` 整轮控制预留超剩余 run pool 直接 `raise ToolResultBudgetExhausted`；`:99-105` 仅「同轮全为 get_recent_messages」均分剩余额度；`src/trivae/query/evidence.py:58` `MODEL_TOKEN_CHAR_RATIO = 3`；`src/trivae/config/limits.py:8,11-16,37,44,51-54` 各默认值与勘察一致；`src/trivae/observability/collector.py:64-65` normal 档 max_string_length=512 / max_items=16；`src/trivae/retrieval/semantic/retrieval.py:144-147` 排序 key=(not literal, dense_rank)、158-190 准入无最低分阈值、189-190 达 limit 即停；`src/trivae/query/evidence.py:2257,2309` 裁剪二分从稳定顺序尾部省略、2279 正文阶梯 512→…→32；`src/trivae/retrieval/context.py:188-193` 邻居扩展锚点上限 MAX_AUTOMATIC_CONTEXT_SOURCE_HITS=20；`src/trivae/evaluation/checks.py:47-51` 落盘上限 direct_hits=50 / retrieval_calls=8 / evidence_sources=50 / evidence_message_ids=20；`src/trivae/query/runtime/openai_adapter.py:1648-1689` 动态 instructions 仅含 SYSTEM_PROMPT + 工具轮预算 + no_result 资格 + 计划指导，**无查询时点锚定事实**；`grep -i -E "time|current|date|…" src/trivae/query/runtime/prompt.py` 显示时间规则均为检索窗口选择（:16-24,117-121），未见答案层时效声明要求（全文确认留给 Q8 第 1 步）。

## 已否定假设

（空——记录被实验否定（或无法证实）的假设，附否定证据）

## 待验证假设

- 全部 13 个问题均为 open（待研究），完整清单与最小实验设计见 `research/agent-quality-20261029/QUESTION_POOL.md`（Q1–Q13，含各问题的待否定假设 H 列表与排除方向清单）。
- 第 1 轮进入（全部零预算离线）：Q1 第 1 步（检索重放，含 Q2 capability 级核对与语义 limit 截断频率）、Q4（14 份 review 人工裁决 + 复算脚本固化）、Q5（token 估算校准）、Q7（omitted 分布离线统计）、Q9（A/B 行为量对比）、Q8 第 1 步（prompt.py 全文确认 + temporal 错误分布）。
- 需要预算的第 2 轮候选（Judge 仅 32 次，按第 1 轮数据取舍）：Q8 第 2 步（≈9 请求 + 4 评审）、Q3 第 2 步（≈17 + 8）、Q6 第 2 步（≈17 + 8）、Q10（≈67 + 16）、Q1 第 2 步（≈17 + 8）——全取会超预算，须排序。

## 评测缺陷

（空——记录评测方法、CLI、工作库管理中发现的问题与规避方式）

## 下一步实验

按优先级（全部零模型成本，不消耗 budget.json）：

1. **Q1 第 1 步 检索重放**：只读连接 `data/evaluation/frozen-20261028-validated/`（trivae.sqlite3 + trivae.semantic.sqlite3），对 16 case 全部 GT 证据消息 × 每次运行真实查询词（study-data.json + 各 record 目录 runs.json 的 retrieval_calls.direct_hits 全量表）重放 lexical/semantic 检索；产出「每条未覆盖事实的失败层分布表」（分词/索引、窗口外、投影断层、已可见未采用四层）。同脚本顺带完成 Q2 的 capability 级投影核对与 Q1-H2 的 semantic limit 截断频率。
2. **Q4-① 人工裁决**：按 `interview-docs/Evaluation校准审阅-20261028.md` 逐题确认 14 份 Eval v1 v2.1 review，计算 judge-人工一致率（<80% 则本轮所有 judge 结论加强 provisional 标注）。
3. **Q5 token 校准**：冻结库分层抽样中文/英文/混合各 ≥300 条，bytes/3 vs tokenizer 实测 + A/B usage 对账回归；偏差 >30% 则 Trace 双指标 + Q6 解读带校正系数。
4. **Q7 离线统计**：omitted_hit/omitted_context 消息 timestamp 分布 × GT 证据交集 × >20 hit 邻居覆盖。
5. **Q9 行为对比**：study-data.json 对比 A/B 两臂 tool_calls/检索次数/证据量/答案具体事实密度，定位 B 覆盖率回退机制。
6. **Q8 第 1 步**：全文读 prompt.py 确认无时效声明要求；统计 52 条 temporal_or_scope_error 的运行分布。

产出汇总后决定第 2 轮预算投向（见「待验证假设」）。

## 预算状态

- 剩余额度以 `research/agent-quality-20261029/budget.json` 为准（键名 `deepseekRemaining` / `judgeRemaining`，勿改动）。
- 每次真实 DeepSeek Agent HTTP 请求（含失败）与每次 ChatGPT OAuth Judge 评审，必须先在 `research/agent-quality-20261029/LEDGER.md` 登记一行，再同步扣减 budget.json。
- 当前初始额度：DeepSeek Agent HTTP 请求 250 次；Judge 评审 32 次。
- 预算换算参考（2026-10-30 整合轮，来自 prompt-ab-eval-v1-20261029/metrics.json，非今晚账目）：1 次运行尝试 ≈ 4.2 次 DeepSeek 请求（185 请求 / 44 次尝试）；1 次有效运行 = 1 次 Judge 评审。按此换算今晚最多约 59 次运行尝试、32 次可评审运行；QUESTION_POOL.md 各实验的预计成本已用该换算。

## 环境事实

勘察时间：2026-10-29（Setup 轮，本节所有事实均来自当次实际命令输出）。

### Git 与分支

- Setup 开始时 `git status`：`nothing to commit, working tree clean`，分支 `main`，与 `origin/main` 同步。
- `git checkout -b research/agent-quality-20261029`：分支此前不存在，为新建并切换（`git branch --list` 未命中，非复用）。
- Setup 轮未做任何 git commit / push（按约定由后续轮次负责）。

### 测试命令

- 可用命令：**`uv run pytest --collect-only -q`**。实际输出：`1394 tests collected in 2.97s`（2026-10-29）。 ordered 备选的第一项即成功，`python -m pytest --collect-only -q` 与 `pytest --collect-only -q` 未再尝试。
- 仅验证了 collect，未运行完整测试。

### 评测 CLI

- `uv run trivae --help`：顶层子命令 `auth, import-once, digest, import, chat, trace, eval, semantic, import-diagnostics, web`。
- `uv run trivae eval --help`：子命令 `cases, run, freeze-data, clone-data, cleanup-workspaces, suite-candidates, compare-experiments, report, review, langsmith-sync, langsmith-map, langsmith-resolve, langsmith-review-sync, show, compare, regression, router-jev, snapshot, retrieval-packet, retrieval-annotate, retrieval-metrics, benchmark`；支持 `--env-file`。
- `uv run trivae eval run --help` 要点：必填 `--suite`、`--variant`；`--record-dir`（"Create a formal experiment record"）、`--freeze-manifest`（"Validated frozen master manifest for a formal run"）；另有 `--agent-model`、`--cases-dir`、`--evaluation-database`、`--repeat`、`--case-list`、`--judge-version`、`--allow-prompt-variant`、`--keep-workspace`。

### 实验记录目录命名约定

- `docs/evaluation.md:104` 的通用示例为 `--record-dir data/evaluation/my-experiment`。
- 实际既有实验记录均在 **`evaluation/experiments/<主题slug>-<YYYYMMDD>/`**：`ls evaluation/experiments/` 列出 16 个目录（如 `answer-quality-20261020`、`storage-management-20261029`）；`docs/evaluation.md:72` 与 `:115` 也以 `../evaluation/experiments/<name>/` 引用。今晚新实验应沿用该模式（如 `evaluation/experiments/<今晚主题>-20261029/`）。
- `docs/evaluation.md:107`：`evaluation.sqlite3` 默认存于记录目录，可用 `--evaluation-database` 指定独立持久路径；Run 与完整 Trace 投影在 Application 关闭前原子写入记录目录，成功后自动清理临时工作库。

### 评测数据库生命周期约束（来自 AGENTS.md）

- 正式 Suite 评测必须走 `trivae eval run --record-dir ... --freeze-manifest <master>/freeze.json`；入口校验冻结身份后为每次运行创建独立 APFS 写时复制工作库；不共享 master 或其他实验的工作库。
- 手写脚本复用 `trivae.evaluation.workspace.EvaluationWorkspace` 并在结果持久化后调用 `mark_results_persisted()`；Clone 不可用即明确失败。
- 过期工作副本用 `trivae eval cleanup-workspaces --manifest <master>/freeze.json` 回收；调试可显式 `--keep-workspace`。

### .gitignore 对 research/ 的处理

- `.gitignore` 中无 `research` 相关条目（`grep -n -E "research|evaluation/experiments" .gitignore` 无匹配，exit=1）。
- `git check-ignore -v research/agent-quality-20261029/budget.json research/agent-quality-20261029/STATE.md` exit=1：**未被忽略**。
- `git status --porcelain` 显示 `?? research/`：目录为未跟踪状态，**研究文档可以随本分支提交**。
