# Research: Baseline 实际内容与附带来源复核

- Query: 逐案核对预注册必要事实、实际附带引用与 canonical 来源；判断回复结构损失是否导致本次错误。
- Scope: internal；8 条 Development Baseline；只读 canonical 和实际 Artifact，不调用 Provider。
- Date: 2026-10-20

## Findings

### 方法、工件与判定边界

已读取私有 `protocol.json` 的必要事实、8 个 case/target 文件、8 个实际 Baseline Artifact，以及其中 ToolResultRecord、source snapshot、source handles、调用和预算事实。以 `SQLiteCanonicalReadRepository.read_message_by_id`（`sqlite_read.py:839`）恢复实际附带的每条来源，包括转发 occurrence；只读连接由 `sqlite_read.py:571` 实现。

共核对 **161 次实际 message-source 引用**，全部可恢复，snapshot 正文前缀和时间均与 canonical 一致。此数字包含重复引用，不是去重消息数。8 次查询均 completed、finalization valid；这只证明执行和结构契约。自然语言支持与核心要求另查。

详细但不包含私聊正文的结构化记录在同目录 `baseline-assistant-review.json`。每个必要事实均列 pass/fail/pending、理由和该案内 source handle；human_review 一律 pending，review_status 一律 assistant_provisional。主会话可把此脱敏结构复制到私有审查 packet。研究角色未写入任务 research 之外。

`grounded_answer` 使用预注册条件的严格合取：附带引用不支持其绑定 block 时，即使事实在同次其他位置可见，也不能算 claim-level citation 通过。因此以下 fail 不都表示核心答案错误。pending 不算默认 pass，也不擅自记为明确失败。

### 八案结论

| Case 尾名 | 核心要求 | 实际附带引用支持 | grounded answer 暂定 | 判断依据 |
| --- | --- | --- | --- | --- |
| context-archify | pass | fail | fail | e3/e4 有独立自用与评价来源，不能因历史 target 缺失判无人反馈；但 e1 开头的实际使用与整体倾向判断只绑定身份/发布来源，属于局部引用绑定不足。 |
| context-mattpocock-1 | pass | fail | fail | 仓库、使用指导与有效好评均存在；e3 另把 m1-81 的别话题体验归入目标工具好评，canonical 邻域可复核。 |
| context-mattpocock-2 | pass | pending | pending | 显式 context 找回正向回复及后续认可，实际附到 e1；多数/主流倾向的措辞强度需人工裁定，不能由 target 覆盖证明。 |
| para-intern-owner | pass | pending | pending | 认可与谨慎两种立场均有实际来源，且没有伪称一致；e4 从个别认可推广成群体相对偏好，需人工裁定推断边界。 |
| lexical-resume-miner | fail | pending | fail | 未识别具名项目与其用途，转为无名 skill 和一般方法；不是仅漏引用某次重复出现的 target。 |
| para-resume-advice | pending | fail | fail | 有一般简历建议，但把关键词匹配推广成缺数据情形下的明确相对优先级，附带来源不支持该比较；是否满足原问题整体要求保留人工判断。 |
| cite-nanobot | pass | fail | fail | 目标项目、插件用途准确；e1 代码规模数字在同次 m2-73 可见，却未实际附到该 block，属于引用遗漏，不能说数字虚构。 |
| cite-meimei | pass | pass | pass | 两个方向的具体资源有实际分享来源；无链接的框架提及与资源分享已区分。 |

此表不是新增机械 rubric；用于保留实际观察，避免执行成功、target recall、必要事实支持、引用绑定和整体质量互相代替。不将小样本 assistant 暂判当作 human adjudication 或普遍成功率。

### 已证明的具体问题

**mattpocock-1 的别话题正面体验归属。** e3 的 m1-81 没有指名目标，canonical reply_to 字段为空；该消息前约 180 秒的同 session canonical 对话在讨论另一类产品与定价。模型投影没有发生消息预算省略，但答案把这条作为目标仓库的体验。首个可确认错误在 Evidence Selection / Answer Synthesis 的话题归属，不能归因于本来就为空的 reply 字段未投影。e3 其他有效好评仍成立，不能把“存在好评”一并判假。

**mattpocock-1 的作者疑点已排除。** m1-55 与 m1-56 显示名不同，canonical sender_user_id 相同，因此不能据此判作者错绑。不增加别名规则。

**resume-miner 的实质不足。** 当前工具序列为 semantic_search（原问题表述、limit=20、context 2/2、dense_top_k=40、partial/truncated）后深入一个无名 skill 锚点。它没有得到具名项目证据，也没有为具名资源缺口尝试现有另一检索路径，最终未完成用户要发现具体工具的核心要求。这里应先核查当前快照正式 lexical 是否能用用户区别性概念找到资源，再决定最小指导修改；不能从这次遗漏直接推断 embedding 损坏。

**回复结构丢失的因果边界。** 先前研究已确定 `_model_message_projection` 未送达 canonical reply target，但本批没有建立它导致明确回答错误的因果链。mattpocock-2 在无该结构字段时仍正确恢复并使用正向回复；mattpocock-1 的已证误归消息 reply 字段为 NULL。不能为了实现预设方案把不同问题合并。

### 对候选方案的判断

将“具体工具/资源发现”所需证据澄清为 **具名对象或可用入口，而非仅一般方法与无名 skill**，是本次真实失败支持的业务充分性合同澄清。当前 `prompt.py:92-114` 与现有工具说明已允许首路 weak/insufficient 时换另一工具；需要明确的是何为 materially insufficient，不是增加新调查状态机。

建议只在身份/入口这一实质证据仍缺失时引导使用另一条已有检索路径。不要改成所有资源问题固定双工具顺序，不加题目词表、case ID 分支、全局大窗口、增预算或 retry。离线可达性证明只说明工具能够找到；A/B 仍须证明实际候选行为是否改善。没有收益也应保留结果。

### 可复用测试与工具

- source/窗口/projection：`test_context_source_contract.py:38`、`test_evidence.py:349/363/420`、`test_retrieval_budget.py:176`。
- 若仅澄清 Prompt，静态测试只能证明合同文字，不能证明模型会选择另一检索路径。
- 已有 `scripts/run_prompt_screening.py` 支持受控实验模式与 HTTP 预算。代码差异与仅 Prompt 差异应分别冻结，不把 Prompt 替换入口误当任意代码 A/B。
- 本次内容复核没有运行 Provider、没有新 query、没有修改任何答案或评估原始结果。

## External References

无外部搜索；版本事实均来自本批冻结条件和实际本地 Artifact。未独立验证聊天中提到的外部项目规格。

## Caveats / Not Found

- 本批仅既有、已暴露 Development，不是新盲测；human applicability/semantic review 仍 pending。
- target 未覆盖全部语义正确答案。archify 的实际较新来源足以回答问题，不能只因历史 target 漏附就判整体错误。
- 严格引用绑定判定可能比“整份回答某处出现真实证据”更严；这是预注册 citation-entailment 要求的应用，应与核心答案正确性分列。
- 引用可解析、snapshot 对得上，只证明可信来源身份，不证明自然语言蕴含。
- 私聊原文、个人显示名和详细上下文未写入 tracked 研究报告；私有 Artifact 保留全部复核定位依据。
