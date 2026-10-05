# 验证记录（2026-10-05）

## 交付

讨论调查优先深挖关键提问的回复；资源清单规则按真实需求限定。SDK 明确上下文参数是消息条数，默认仍为 8/8。统一消息投影增加 Host UTC 时间，正文裁剪保留日期/作者/来源。动态 instructions 读取已有轮次 state，说明已耗与剩余轮数；默认三轮与无工具最终综合不变。

## 代码验证

- implement 子代理：相关 pytest 77 项、全量 pytest 662 项通过。
- root 独立检查：`uv run --all-extras ruff check src tests` 通过，`uv run --all-extras mypy src` 通过（115 个源码文件）；实验脚本 Ruff 与 `git diff --check` 通过。
- 回归涵盖真实 SDK schema、初始及耗尽轮次提示、命中与语义上下文投影、正文裁剪后 source/author/timestamp/timestamp_utc 保留。
- 旧测试新增 runtime state 的真实 tool_rounds 字段；长消息 fixture 用于实际触发正文裁剪，没有删除旧断言或放宽业务结果。
- 最终 trellis-check 审查补上真实 SDK schema 的 before/after 默认值均为 8 的断言，77 项相关测试再次通过；Lint/type-check 通过。仅增加契约断言，没有改变候选产品代码或重跑真实样本。

## 正式工具重放

`retrieval_quality_probe.py` 走正式 Tool → Capability → ToolResultRecord → Model Projection。原案例向后 2/8 条均无推荐；20 条有推荐但无补充；40 条两者均可见。增加 UTC 字段后的 40 条投影估算为 4779 tokens，16k 下无截断。向后 40 仍为实验变量，不修改默认值。

## 真实配对条件

- `real_pair.py` 运行正式 Application/SDK/finalizer，不拼装或改写答案。
- 固定原长问题、同一群、一次 SQLite backup 的 canonical/semantic 内容、归档上界；允许历史背景访问，下界继续由原问题指定。
- Provider/model：当前 `.env` 的 DeepSeek/deepseek-flash；三轮工具、八轮 SDK backstop、dynamic evidence budget 一致。按现有 verified registry，1M context 对应 per-call 128k、run pool 250k。
- Baseline 为开始前保存的源码，Candidate 为四处产品修改；两侧均强制 Standard/no Plan，消除 Planner 差异。这不是原 Planned Trace 的逐调用重放，也不是冻结 ToolResult 的纯 Answerer 实验。
- 顺序为 A1、A2、B1、B2。非盲审、重复两次，只验证本 Failure Case，不作统计显著性或跨任务质量结论。
- 查询历史、Trace、Evaluation/feedback 数据与答案均保存到各 cell 独立目录；生产数据库不写入实验会话，canonical/semantic 采用本地备份。

## 配对实测

| 条件 | 工具轮数 | context 调用 | 推荐及补充进入回答 | 延迟 | Provider total tokens |
| --- | ---: | ---: | --- | ---: | ---: |
| Baseline 1 | 3 | 0 | 否 | 77.407s | 616378 |
| Baseline 2 | 3 | 0 | 否 | 92.360s | 622399 |
| Candidate 1 | 3 | 4 | 是 | 84.473s | 591757 |
| Candidate 2 | 3 | 7 | 是 | 72.791s | 141584 |

两次 Candidate 都围绕原教程提问读取后续消息。B1 在最后工具轮并行读取四个锚点，仍只消耗一轮；B2 更早在第二轮调查部分锚点。最终模型输入中可直接观察到书籍推荐与“这本书很详细”，两次正式答案均使用这些内容，推荐作者写为「在串中」，提问者为 Red Herring，日期为 8 月 11 日。B2 也把“调用个 api 谁都会”“这也能叫 agent 吗”归给朗易思听；B1 未复述这两句，不能算该项归属验证。

两次 Candidate 均出现 8 月 14 日书籍询问；B1 将此前课程背景写为 5 月 21 日，避免原例的 4 月误写，B2 不使用该历史背景，不能计为日期改正样本。没有机械总分，主要观测是关键回复恢复与使用。

Baseline 的大结果输入存在 Trace capture 和模型投影裁剪，不能以 capture 片段没有书名推断模型从未见过书名。能确认的是：没有显式 context 调用，最终答案没有使用已知推荐。Candidate 的 context 结果不截断，且 capture 保留推荐和解释，可支持正向送达证据。

延迟与 token 存在波动，Baseline 首次 embedding 冷加载与后续 warm run 不等价；AABB 顺序和 cache 也影响成本。表格为实测事实，不宣称普遍更快或更省。

## 其他真实查询回归

| 问题类型 | 工具/轮数 | 核对结果 |
| --- | --- | --- |
| 纯 GitHub 清单 | 1 次 lexical，1 轮 | github.com、limit=5000、0/0 上下文；未用 recent/SQL 重数，保留具体链接 |
| 简单书籍提及事实 | 2 次同轮 lexical，1 轮 | 正确命中朗易思听与 2026-08-14T15:01:47.000Z，无深挖 |
| 精确零结果 | 1 次 lexical，1 轮 | 明确报告该精确名称零命中，无编造内容 |
| 后训练教程局部调查 | lexical + semantic + context，2 轮 | 书籍及补充进入答案，正确归给在串中，日期与 canonical 一致 |

八次生产查询均 completed，未新增 Provider 重试或 fallback。零结果回答仍暴露群 ID 和毫秒边界，是既有“不要暴露内部细节”指导的遵从不足，不等于零结果检索失效。

## 保留的反例与限制

- B1 初始调用仍有宽泛 recent/无时间 semantic，后来才限定 15 天；用户的 8 月 1 日绝对下界与相对窗口起点没有始终一致。没有新增自然语言日期解析来掩盖该缺口。
- B1 历史段与整体范围概括仍存在不一致，还把晚于推荐的观点说成“此前”；新 UTC 字段降低换算负担，不保证时间关系正确。
- B2 仍用“唯一具体材料”等过强措辞；局部回复调查也出现“唯一”“未再出现”，现有窗口不能证明全话题穷尽。
- B2 部分书籍问答依然被称“未获回答”，同时又说明证据未确认，负面结论校准仍不稳定。
- 两次回答仍有招聘/工具闲聊占据篇幅，按背景给学习建议的组织也未完全稳定。没有通过扩字、关键词规则或后处理改写答案。
- 增长后的 SYSTEM_PROMPT 为 20450 字符，debug Trace 的 20k 字符 capture 会截断 system 段尾部；SDK 实际请求未被此 capture 截断，局部测试核对的是完整 RuntimeEvent。完整系统指导可通过源码重建，但不能把存储的 capture 当作完整 HTTP body。
- 本轮同时修改指导、UTC 和预算事实，只能归因整体候选；不能声称某一项单独产生收益。后续需要更广案例或拆变量实验时，再基于新 Failure Case 定范围。

## 实验工具自身问题

A1 查询已经完成并提交，但实验脚本最初误用不存在的 `result.answer` 属性，保存正文时失败。修为正式 `result.final_answer`，从已提交的隔离 Conversation Store 恢复同一次答案并导出既有 Trace，没有重跑或替换该样本。原 failure.json/stderr 保留，本问题归实验保存逻辑，不归 Provider 或模型质量。

## 设计、责任与演进事实

- Problem/Motivation：真实回答漏掉已存在的后训练推荐，作者与日期错绑；原问题与 canonical 对照保存在本地 reference.json。
- Rationale/Why not：正式工具已经能读取回复，故先改调查顺序、参数说明和可信事实。没有证据要求换 embedding、加 reranker、自动补所有上下文或增预算；若锚点两路都稳定召回失败，再评估检索层。
- Ownership/Boundary：模型判断话题关联与归纳；Host 管 scope、日期事实、轮次、引用和存储。没有增加第二套状态机、工具或补丁路由。
- Observability/Debug：每个 cell 有 result.json、answer.md、trace.sqlite3、trace.log、stdout/stderr；summary.json 汇总真实调用与正向证据可见性，reference.json 为人工核验素材。
- Scale/Performance：窗口扩大带入噪声，三轮内的 context 调用数会上升；UTC 字段增加投影体积。当前实测不能证明全局成本下降。
- Evolution：保持残余生成反例，下一轮优先处理绝对时间范围一致性与结论校准；不把无证据 retry/guard/rubric 塞入本次产品。
- Interview Defense Notes：本轮可以证明“已有工具结合新指导能恢复并使用关键回复”，不能证明“每次都全而准确”；依据为两次正式 Candidate 与四类回归，而非字数或 finalization=valid。

完整私有工件在本任务的 ignored `experiment/`；源码和脱敏验证记录留在任务目录。用户本轮要求实现，没有自动提交推送。
