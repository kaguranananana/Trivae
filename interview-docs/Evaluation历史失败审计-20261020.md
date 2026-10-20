# Evaluation 历史失败审计（2026-10-20）

本轮从已有失败出发，没有重新造一套题库。历史质量基线是 `7bac928` 的 37 Development × 5 Variant = 185 runs；Gate 3 candidate 是 `8805aa2`，二者不混用。最新 CJK bigram v2 已在本轮前进入生产，不能把本轮变化归因给再次修改 tokenizer。

## 原始证据可用性

历史 baseline 与 Gate 3 各 185/185 个 Trace 文本均在本地，两个 Evaluation SQLite 均可打开。原始聊天、完整 Trace、答案和 Packet 保持 Git 忽略。Normal Trace 常将字符串截为 512 字符，大检索调用的 ID 摘要也可能只含前 50 个；“摘要未见”不等于“从未召回”。人工 Packet 包含补充审核参考来源，也不等于模型实际看到过这些来源。

历史 GT 为 473,236 条消息、14 个来源；本轮固定副本为 811,892 条消息、88 个来源，索引状态另行冻结。历史结果用于定位，不作为本轮百分比提升的 A。新 Case 使用独立 `quality-` 身份，保留历史 Case/版本来源；原人工 GT 不伪装成已经审核过新快照。

## Context recovery 0/3 到底测了什么

旧指标判断的是 required_context 是否进入**最终 Evidence**，不是上下文工具是否正常工作。三个历史 Case 的 anchor 已召回，但 required_context 未取得，没有调用 `get_message_context`，Host projection 没有消息省略记录。

| Case | 历史 D 表现 | 当时根因证据 | 本轮 Baseline | 修复价值与边界 |
|---|---|---|---|---|
| dev-context-archify | Evidence 1/2；context 0/1 | 只做 lexical，before=0/after=2，所需回复不在返回中 | 旧 target 最终 0/2；其他实际使用与正负评价足以回答核心问题 | 不能把旧 target 缺失直接判为当前内容失败；仍有局部 claim 引用支持问题 |
| dev-context-mattpocock-1 | 1/2；0/1 | 两次 lexical 都关闭邻居窗口；所需回复不含检索词 | 旧 target 1/2；已给用法和其他好评，但混入另一话题体验句 | 属于获取/选据与话题归属；没有证明 reply 投影缺失是此次错误原因 |
| dev-context-mattpocock-2 | 1/2；0/1 | 同上，没有后续 context | 旧 target 2/2，模型可见且被引用 | 当前该次运行已恢复，不制造“修复 0/3 模块”的收益 |

当前快照中三条 required_context 都有明确 reply 关系；与 anchor 之间分别间隔 9、143、1 条消息。这个距离是**新快照诊断**，不能冒充历史重算。统一增大少量邻居不能覆盖 143 条的情况，全面扩窗也不是证据质量修复。

## Evidence Recall 49/67 的 18 个缺失

缺失来自 13 个 Case，不能把它们全部归为检索失败。

| Case | 历史最终命中 | 当时根因证据 | 当前仍可能存在 | 修复价值 |
|---|---|---|---|---|
| dev-cite-meimei | 1/3 | 大检索摘要截断，最终漏两 target | 本轮 3/3，核心与绑定暂判通过 | 历史遗漏本次未复现 |
| dev-cite-nanobot | 3/4 | 四 target 都在 direct hits，未发生 projection 省略 | 本轮 4/4，但有正确数字附错引用的问题 | 应查选据与 claim 绑定，不能扩大 Top-K 代替修复 |
| dev-lexical-forge | 2/3 | 三 target 都在 direct hits | 调参外回归保留 | 区分 GT 冗余来源与业务事实遗漏 |
| dev-lexical-siclaw | 2/3 | 三 target 都已召回 | 调参外回归保留 | 同上 |
| dev-lexical-mcp-switch | 1/2 | 大调用摘要截断 | 调参外回归保留 | 未观测深度不等于不存在 |
| dev-lexical-resume-miner | 0/4 | semantic/lexical/context 多次调查，历史摘要不足以锁定单一原因 | 本轮四 target 均未返回，答案没有具名工具；完成但核心不合格 | 本次主问题：工具发现的证据充分性判断 |
| dev-lexical-vibe-game | 1/3 | 两次各 100 消息，摘要截断 | 调参外回归保留 | 不用历史摘要猜排名/投影原因 |
| dev-para-intern-hard-part | 0/1 | partial GT；100 消息摘要截断 | 调参外回归保留 | 不外推全库语义 Recall |
| dev-para-job-anxiety | 0/1 | partial GT，多路检索仍漏 target | 未纳入本轮调参 | 待专门核验实际业务事实 |
| dev-para-resume-advice | 0/1 | 多次调用仍漏已知 target | 本轮仍 0/1，核心充分性待审 | 单一目标遗漏不能自动判所有建议错误 |
| 三个 context Case | 各 1/2 | 见上表 | 当前 0/2、1/2、2/2 | 不把历史小样本归纳为普遍缺陷 |

本轮 8 条开发 Baseline 的 19 个固定 target：direct 11、Tool returned 12、model-visible 12、final Evidence 11。完整 Host record 与 Trace 的结构化 `output_projection` 可核对，没有 Host projection 省略；不能把未取回的 7 个目标归成预算截断。

## Gate 3 的 12 条人工复核

`review.md` 已填写：2 fail、4 failed_no_answer、5 confirmed_with_notes、1 confirmed。`packet.json` 顶层和 12 条 item 仍 pending，属于状态不同步；本轮保留原产物，不重写它们，不升级任何 Judge claim 为人工裁决。

| Case/组 | 审计结论 |
|---|---|
| dev-context-archify | 人工内容 fail：未取得关键反馈并作过强否定；Packet 参考节选不是模型输入 |
| dev-para-intern-owner | 人工内容 fail：遗漏相反立场，将争议压成单向结论；本轮 Baseline 已包含不同立场，仍有局部来源归属与概括待审 |
| dev-lexical-agentic-zh / dev-lexical-nanobot-wiki | Provider failure，无可评答案，不能归成内容错误 |
| dev-temporal-14d / dev-zero-empty-1 | Runtime 虽 completed，生产 Finalizer 拒绝 `INVALID_ANSWER_ARTIFACT`，Query 实际 failed；不是成功交付 |
| dev-temporal-2d | 实际只覆盖 100/2699、partial、has_more=true。旧 review 建议补“完整覆盖”的解释与 Host 事实冲突，不采纳 |
| 其余 confirmed / confirmed_with_notes | 保留原审核强度；部分补充语句仍需完整来源支持，不能扩大为全体准确率 |

v1 sealed Holdout 的 90/90 SettingsError 是冻结 worktree 未加载主目录环境配置；v2 是复用已暴露 Case 的 recovery，52 completed/38 failed。均不作为本轮独立泛化证据。

## 本次决策

选定 `resume-miner` 的真实核心遗漏，定位在 **Tool Selection / evidence sufficiency**：相关方法或无名 Skill 被当成工具发现问题的充分结果。现有词法路径在原有上限内能够取得具名目标，修复仅澄清现有 Prompt 中的充分性条件。reply 结构投影与 source-hit cap 披露虽有独立缺口，本批尚无单点因果证据，不混入 treatment。

实验结果、未改善和退化见 [端到端质量实验](Evaluation端到端质量实验-20261020.md)；简历主张与追问见 [证据账本与面试](Evaluation优化-证据账本与面试.md)。
