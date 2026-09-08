# Trivae 项目证据复盘

> 交付阶段：个人项目 / 工程验证，已完成 Development Evaluation；未证明生产上线、Holdout 泛化或真实用户收益。
>
> 事实截止：2026-09-05。本复盘只使用仓库源码、SQLite、Evaluation artifact、测试与 Git 历史，不引用群聊正文。

## 1. 问题背景

真实群聊记录同时存在来源重叠、重复消息、内容冲突、短中文检索漏召回、上下文碎片化和时间范围不明确等问题。普通“向量检索 + 大模型”只能给出一段生成文本，无法回答结果是否来自当前请求、是否越权、是否遗漏、为什么失败，以及不同方案是否真的改善了质量。

项目目标是把“搜索聊天记录”扩展为一条可复核的调查链路：先形成统一事实库，再让 Agent 在明确的 Scope 和预算内组合检索工具，最终只提交能绑定当前运行证据的答案，并用固定环境下的 Evaluation 对失败做分层归因。

## 2. 方案决策

1. **事实与索引分离：** Canonical Store 保存规范化消息与 provenance；FTS5 和 sqlite-vec 是可重建派生索引。索引策略变化不修改事实层。
2. **检索能力分层：** lexical、semantic、structured、temporal 和 context 各自保留输入、排序、coverage 与失败语义，不以万能 hybrid 接口隐藏差异。
3. **控制面最小化：** Router 只判断复杂度，Planner 只生成一次软指导，简单与复杂请求都进入同一个 Agent Runtime。
4. **执行有界：** 最大 Turn、Tool Round、单次/整次 Tool Result Budget、Planner 超时和 cooperative cancel 分别控制循环、结果膨胀与中止语义。
5. **答案由 Host 验证：** 模型只提交带短来源句柄的 Claim；Host 从当前 Run 的 Tool Result 解析、回填并校验 Evidence/Citation。
6. **先修测量链路：** 发现评测分类和 Provider lifecycle 缺陷后，先修根因并保持 Retrieval quality failure 可见，没有通过改 GT、加重试或重命名指标掩盖问题。

## 3. 个人动作

Git 历史显示，2026-08-18 至 2026-09-05 的 256 个提交均由同一仓库作者完成。结合用户将其作为个人项目简历材料的上下文，可以将下列动作写成个人设计与实现，但不扩写为团队负责人或生产 Owner：

- 建立 Canonical Message、来源、会话、成员、导入批次、重复与冲突 variant 数据模型。
- 实现文件级事务、记录级错误、幂等 Canonical 写入和派生索引重建。
- 复现 FTS5 `unicode61` 连续中文漏召回，设计 CJK bigram v2 并补充 mixed-script regression。
- 实现时间感知 Parent/Small Child 语义分块、向量索引身份与 missing/building/partial/failed/stale 状态。
- 基于 OpenAI Agents SDK 实现 Tool Loop、工具白名单、结果预算、取消、流式事件和终态投影。
- 建立 Answer Artifact、当前 Run provenance、Scope 校验、来源水合和 zero-result positive-proof contract。
- 建立 Evaluation Case/Variant/Run/Trace/Failure Artifact，并完成 GT、冻结、真实 Provider 运行与根因修复。
- 实现 FastAPI/NDJSON 流式服务与 Vue 3 前端投影，使产品入口复用同一查询链路。

## 4. 交付状态

**状态：工程验证完成到 Stage 3 Development baseline，Ready for 后续 Gate；不是生产上线。**

- 数据、检索、Agent、Evidence、Trace、Evaluation、CLI/TUI/Web 主链路均有源码和自动化测试。
- 真实 Provider 已通过应用查询入口参与 Development Evaluation。
- Holdout 不存在；没有 unseen/generalization 结论。
- 没有仓库证据支持真实外部用户数、业务转化、节省工时、线上并发或 SLA。

## 5. 落地范围

| 维度 | 已有范围 | 边界 |
| --- | --- | --- |
| 数据 | 989,256 条导入输入；473,236 条唯一 Canonical Message；14 份来源文件；7 个会话 | 来源文件不等于独立群；不公开聊天正文与成员身份 |
| 导入 | 28 个 completed batch；516,020 次重复输入；5,550 次冲突；当前 0 import error | 证明当前 Snapshot 导入完成，不代表任意未来格式都无错误 |
| 词法索引 | 473,236 条 FTS5 row；CJK bigram v2 | 只证明当前索引与 Snapshot 对齐 |
| 语义索引 | 54,267 个 chunk/vector；473,236 条 canonical message 被索引；状态 completed | 使用固定 embedding identity 与 chunker v1，不代表参数最优 |
| Evaluation | 47 条人工裁决 GT；37 Development + 10 Calibration；五 Variant；185 次正式 Development 运行 | 1 repetition；Calibration 不进入 headline denominator；无 Holdout |
| 产品入口 | CLI、Textual TUI、FastAPI/NDJSON、Vue 3 | 本地产品形态，未证明生产流量与多机部署 |

## 6. 效果证据

### 实测结果

- 10 个 exhaustive/corpus 精确谓词 Query、33 个 relevant item 上，lexical Recall@10 为 33/33；这个结论不能泛化为所有问题的系统召回率。
- full-system Development baseline 为 37/37 execution completed、37/37 valid Answer Artifact；它证明执行与结构契约完成，不等于 37/37 事实正确。
- 47/47 GT 已完成人工裁决；environment gate 4/4、freeze verification 12/12 通过。
- post-fix raw record、Evaluation SQLite 与 Trace 各有 185 条可对齐记录。
- 当前重新验证为 pytest 576 passed，Ruff 与 Mypy 全部通过。

### 阶段结果

- Evaluation 能把 provider、retrieval miss、ranking、context、coverage、answer generation 与 zero-result 分开记录。
- 修复后观察到 4 个可定位 ranking failure，相关消息位于 direct rank 14–29；不再把它们笼统记成未召回。
- Benchmark runner async 化后，Application 创建、Provider 请求与关闭保持在同一 event loop。

### 尚未成立的效果

- semantic 没有被证明全面优于 lexical；现有结果只支持互补通道定位。
- context expansion 的 uplift 样本过小且方向不稳定。
- Provider availability window 不代表 Variant quality 下降，也不能用重试抹去。
- 没有 Holdout、生产 SLA、真实用户或业务收益证据。

## 7. 个人边界

- 可以写“个人项目”“设计并实现”“定位并修复”，因为仓库提交历史与用户提供的项目上下文支持个人交付口径。
- 不写“带领团队”“跨部门推进”“生产 Owner”“支撑多少用户”，仓库没有此类证据。
- 47.3 万是项目数据规模，不是个人用户规模；185 是 Evaluation run 数，不是线上请求量。
- `valid Answer Artifact` 是输出契约指标，不是事实正确率。
- 对外只展示脱敏统计、源码结构和评测口径，不展示原始群名、成员标识、消息正文或凭据。

## 8. 待补证据

1. 用户本人确认 `anontokyo` Git 作者身份可否直接作为公开个人 ownership 证据。
2. 项目真实使用方式：仅自用、作品集演示、内部试用或公开部署。
3. 一到两个真实用户任务的前后对比，例如查找耗时、复核成本或错误案例。
4. Holdout 生成、人工审核、冻结与一次性运行结果。
5. 固定硬件、并发、Provider 与请求分布下的 P50/P95、成本和资源占用。
6. 数据授权与对外披露口径；正式简历是否允许出现 473,236、14 与 7。

## 9. 面试追问

1. 为什么 Canonical Store 的幂等性只约束事实写入，而 ImportBatch 仍然保留每次运行？
2. first-wins 发生冲突时，怎样保留另一版本又不污染当前事实？
3. 为什么 CJK bigram 能修短词漏召回，mixed CJK/ASCII 边界怎样处理？
4. 语义分块为什么让短 Child 检索、Parent/Canonical Message 回源？
5. 语义索引身份包含哪些字段，为什么配置变化必须让旧索引 stale？
6. 为什么 Router 不直接选择工具，Planner 不直接执行步骤？
7. Tool Round 与 Tool Result Budget 的故障模式分别是什么？
8. 预算耗尽后的无工具 Final Synthesis 如何保证仍有证据可用？
9. cooperative cancel 与 `asyncio` task cancellation 有什么语义差异？
10. 模型为什么只能看到短 source handle，Host 如何映射回可信来源？
11. 历史会话中的 Evidence 为什么不能直接成为新 Run 的 Citation？
12. zero-result 为什么需要所有相关检索完整成功且为空？
13. 为什么 Development、Calibration、Holdout 不能放在同一个分母？
14. 如何区分 retrieval miss 和 ranking failure，旧分类器错在哪里？
15. 为什么 Provider timeout 不能归因成语义/上下文 Variant 变差？
16. 如果下一阶段只能做一个动作，为什么应优先完成 Holdout 而不是直接加 Reranker？

## 升维迁移

- **原始事实：** 做了一个能搜索群聊并回答问题的 Agent。
- **高密度表达：** 将 98.9 万条重叠群聊输入归并为 47.3 万条可追溯事实，构建多路检索与受预算约束的 Agent Runtime，并用当前 Run 引用和 185 次真实 Provider Evaluation 将答案质量拆解为可复核、可归因的工程事实。
- **升维动作：** 从“功能清单”提升为“失败模式 → 工程机制 → 证据口径 → 适用边界”。
- **可选重写题：** 不使用“提升稳定性”或“减少幻觉”，用一句话说明 zero-result positive proof 带来的可验证变化。

## 候选简历表述

推荐直接使用 `简历-Trivae-Agent岗.md` 的五条投递版；空间紧张时使用四条压缩版。所有数字都必须保留 Development、exhaustive/corpus 或数据规模等限定词。
