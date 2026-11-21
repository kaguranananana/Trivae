# 研究状态（Agent Quality Research 2026-10-29）

分支：`research/agent-quality-20261029`（自 main 创建）。状态目录：`research/agent-quality-20261029/`。

## 2026-10-31 后续预算研究已分支保存

R2/R6产品修复已选择性合入并推送main（ce553277，状态8b684599）。本目录原研究历史继续保留；后续预算扣减与新报告位于`codex/budget-capacity-20261031`，入口`research/budget-capacity-20261031/REPORT.md`。该后续分支的budget.json/LEDGER.md为本次继续后的累计事实：DeepSeek117、Judge4；不是重新初始化额度。原分支历史128/6只适用于10月30日结束。新增11 Agent HTTP（含6个400）、2 Judge推理HTTP（含1连接失败），另一次恢复在授权模型目录GET时失败、未发推理请求。没有更换Provider或扩大额度。

100/200/500固定池GT出现18/19/19；32/64/128K条件Host目标可见14/18/18；32/64K真实受控合成各交付2/3，尚无总体质量收益。原始材料及本轮失败均留存；产品预算不改。后续以新分支账本和报告为准，不从下方历史余额恢复请求额度。

## 版本归档与远端同步（2026-10-31）

用户已授权提交并推送最近研究成果，目标为当前分支的origin/research/agent-quality-20261029；不合并main、不部署。七份不含内嵌群聊原文的R1脚本按原文归档，说明见[rounds/README.md](rounds/README.md)。原Q4脚本、十一份JSON及计数锁原位保留并纳入忽略规则；没有清理或重写原始研究文件。下文“原19文件未跟踪”“未推送”描述的是10月30日收尾时的历史状态，当前同步情况以Git为准。没有新增实验或模型请求，预算仍128/6。

## 最新结论与恢复入口（2026-10-30，本轮已收束）

- 完整交付：[REPORT.md](REPORT.md)；面试材料在根interview-docs目录。Z Code原R1的8脚本/11JSON仍未跟踪且未编辑/暂存，11份JSON尺寸与接管清单相同。
- 两处工程修复留在本地研究分支：e5f53ac4容量优先序、642896de贯穿Host预算；56cfd2c5修复真实SDK httpx2计数；7bfd5576为独立Prompt实验入口。没有推送、合主、部署或重启。主Prompt仍是原B，R7候选未采纳。
- R2：16计划Run，15有效答案/15 Review，含1次Case10非法JSON失败；R6：8/8答案和Review；R7：4计划Run，3有效答案/3 Review，含1次预算失败。另保留2个早期中断尝试，共30次实际尝试、28计划槽、26份完整答案/新Review。复用基准不重复计为新请求。
- 已验证：51个原ANN池选中chunk不变，rank1整块丢失19→0，Capability已知目标8→18（+10/-0）；同一新Envelope过旧/新Host，48可比较、3两侧均原控制预算不足，目标可见10→14（+4/-0）。不是总体召回率或答案准确率。
- 真实4题双轴≥3辅助信号：原逻辑3/8、仅cap-rank2/8、完整rank4/8；样本小且07有低task风险。R6仅3/8 Run实际触发semantic hit删除，不把未生效路径的分数变化归功于修复。
- R7首轮联合提及0/4→4/4，交付4/4→3/4，双轴≥3仍1/4，按预注册门槛停止，不执行01/10额外控制，不调同题Prompt。产品Prompt文件不改。
- **整项预算：已用DeepSeek122/250、OAuth Judge26/32，剩128/6。** budget.json、LEDGER.md的148行和HTTP原件相符；初版httpx漏计的9次已从Trace追记，未重置额度。Token已填：119个Agent请求有Usage、3未知；26个Judge全部有Usage。禁止把旧AB的185/42或本轮基准复用混为新预算。
- 最终代码验证1398 passed/1 skipped（37.49s）、相关43、Ruff与Mypy148源码、diff通过。当前没有本轮Agent/Judge/离线实验在运行。原数据、失败、未采纳候选、保留工作库均未清理。

### 后续继续时

以原工作区的本文件、budget.json、LEDGER.md及ignored data/evaluation/agent-quality-codex-20261030/为准。干净codex实验worktree只是代码环境，运行时--research-state-dir指向原工作区；不要从旧工作树或旧Setup段恢复250/32。不要重跑已完成的64历史AB、R2/R6基准或填补失败槽。

最优先的新实验是Q6批次控制准入与预算内最终合成合同：R7保存了31409结果Token/剩591后失败的真实Case。先按原Trace做确定性复现，不扩大预算、不压低估算、不加重试。其次做Claim级人工裁决和来源/任务/时效属性验证。Q13非法JSON仍是明确失败，原完整正文不全，不能声称修好。Q8“无查询时间”已被64/64实际输入否定；精确tokenizer校准、Capability未跑题、Router/轮数收益仍未验证，不自动延续旧清单。

以下Setup、整合与逐轮续记保留为历史，出现冲突以上方结论及代码/原始结果为准。

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

## Codex接管续记 · 2026-10-30（覆盖上文过时的“下一步”）

- 恢复事实见RECOVERY-20261030.md；Z Code R1已有八脚本/十一JSON，原件保留，未重新初始化工作流。当前无其他在跑的实验。
- R2容量断层：两项真实机制回归先红后绿；候选只把字面之外核心的保留顺序从时间改为检索排名，容量仍100、外部顺序仍时间。51次保存ANN池的精确离线A/B进行中，复用旧embedding；先前单独baseline审计因与配对审计重复而停止，无结果冒充完成。
- 当前完整验证1395 passed/1 skipped（39.64s）、Ruff通过、Mypy148源码通过、diff检查通过。候选尚未获答案质量验证，不标总体有效。
- R3已完成：评测信号口径审计，见R3-results.md。02b原rationale不准确但冻结属性要求仍未满足，未改原分数；52条time/scope辅助分类41范围/4来源日期/7历史当当前，停止“统一日期锚定可解决52条”假设；R1 L6非语义采用、Q4非人工裁决、Q5非精确tokenizer。
- 预算从本轮会话/文件交叉恢复为已用0 Agent、0 Judge，剩余250/32；HTTP准入计数脚本以MockTransport验证失败计数和超额前拒绝，通过，未产生真实网络请求。后续每次实际推理HTTP先登记并扣减；最终状态以budget.json+LEDGER+ignored http-events.jsonl核对。
- 不自动push/合并/部署。不暂存Z Code已有rounds文件。下一步等待51次离线配对结束，若已知目标无退化且净增，再启动小规模真实对照。

R2离线最终：51/51 baseline与原件一致，1007 selected chunk完全相同；top dense rank整块丢失19→0，GT消息按调用出现8→18（+10/-0），literal IDs无变化。26条旧S3精确核验7真容量损失/6仅parent/13数字区间误判。真实入口两次本地预检（固定eval合同、dirty Git）失败，均0HTTP；准备在本地阶段提交的干净worktree继续。预算仍250/32。

2026-10-30真实首批接线修复：httpx2默认SDK漏计，立即停止；从保留工作库逐请求确认并追记9HTTP，含2中断流；剩余241/32。原始interruption-traces和request-count-recovery.json保留在Codex ignored目录，Baseline08有1个完成Run可复用，其余中断不评分。计数器修复覆盖实际httpx2+httpx，3回归通过，后续不再复跑已完成Baseline08重复1。独立干净实验worktree位于~/.codex/worktrees/trivae-agent-quality-20261030，保留源R1文件不动；正式数据工作库仍由EvaluationWorkspace管理。

R3/R4续记：原64Run的首个模型可见上下文64/64已有正确查询时点，Q8“缺查询时间输入”被实际Trace证伪，不再做日期注入。完整新增回归后1398 passed/1 skipped（36.28s）。真实计数器已验证覆盖httpx2，后续HTTP正常逐笔扣减；首个OAuth Judge成功，当前实时额度看budget.json。

R6进行中：真实Case08证明R2修复只闭合Capability容量，Host预算仍会按时间丢高rank目标。源Envelope已通过Workspace隔离重放并冻结；固定预算10933，旧Host75条/目标0，新Host80条/目标1。43项相关回归通过，完整回归与51调用同Envelope旧/新Host检查正在运行；实现仅修改primary优先序传递与slot省略顺序。R2全套真实矩阵仍在56cfd2c5干净worktree运行，不混入R6。R5联合查询离线Kimi/DeepSeek分别1422/2495命中、各前100目标0；联合79条目标2；MCP/Skills分别前100目标0、联合87条目标1。暂不改Prompt，保留独立方向。

R6离线最终：51次同Envelope旧/新Host对照，48可比较、3两侧均原控制预算不足；GT可见10→14（+4/-0），无新增投影错误。完整1398 passed/1 skipped（37.49s）、Mypy148/Ruff/diff通过。R2真实16计划Run→Baseline8 completed、Candidate7 completed+1 Case10非法JSON（Unicode295），不补跑；15份答案Judge进行中。实际累计Agent73请求，Judge实时以budget为准。R6代码仅工程层已验证，尚无真实答案质量收益结论。

R6真实阶段已启动（新Variant，642896de）：host-01-07和host-08-10两批，每题两次，共8个新Run；复用R2 Candidate七个完整答案与一个原失败槽作基准。旧Case10不补跑。原R2 15份Judge在补齐。后续继续检查这两批record目录和budget/LEDGER，原R1材料仍保留未暂存。

R2最终：15/15有效答案Judge已完成，联合两轴≥3 Baseline3/8计划槽、cap-rank2/8（成功答案2/7），不是旧严格completion指标。该阶段实际Agent73/Judge15。R6新增8/8已交付且无新增运行失败，8份Judge进行中；本轮总实时预算以budget为准。R7已预注册仅一条比较联合检索Prompt候选（未运行），最多先4Run/4Judge，只有重复正向才进4个非比较控制；总Judge15+8+8=31≤32。产品Prompt仍严格等于保存的B，无修改。

R6最终真实8/8交付、8份Review，34 Agent/8 Judge；截至此阶段累计107/23，余143/9。联合Judge≥3信号2/8计划槽→4/8，原逻辑3/8，不能宣称总体提升。07有低task风险，但其两个Run没有触发semantic hit裁剪（一个100条无省略、另一个无semantic），已加入实际处理暴露审计。R7首片已启动joint-07、joint-08各两次，复用R6对应基准；4新Judge上限，产品Prompt仍未改。
