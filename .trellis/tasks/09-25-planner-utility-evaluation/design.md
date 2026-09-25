# Design: forced-path Planner utility

## 实验边界

`EvaluationRunner → TrivaeApplication.query() → QueryOrchestrator` 保持现有主链。`forced_route` 在 QueryOrchestrator 决策处绕过 Router；standard 直接进入共享 Runtime，planned 调用现有 SoftPlanner 一次并将 plan 渲染为 soft guidance，随后进入同一 Runtime。Planner 不执行 Tool。Planner 返回 failure 时，现有设计记录 degraded diagnostic 并继续同一 Runtime；未捕获异常仍向上显式传播。

不修改 Planner prompt、Router taxonomy、主模型、Retrieval、Tool、Evidence/Citation 或 Runtime 语义。最小行为差距是现有 Evaluation raw projection 缺乏直接分析 Planner 调用/状态/延迟/usage 的字段；只从现有 Trace terminal event 增补 bounded operational projection。

## 数据与身份

- 主 Suite：37 条 Development、六个既有 GT category；不擅自为每条 Case 增加 route GT。旧 forced Variant 使用 M6 代码/模型/单 Tool，身份已过期。
- 两个本轮 Variant pin 当前 execution commit、官方 DeepSeek、实际 Settings 与七 Tool surface、当前 Snapshot/索引、Evidence/Citation、context 和 Evaluation identity；除 `role`、`variant_id` 等识别字段外，配置差异仅为 forced route。`role` 与 ID 是展示身份，不是执行变量。
- 独立 Environment manifest、Evaluation SQLite、raw、Trace projection、报告置于被 Git 忽略的本轮目录。正式运行时必须由干净 execution commit 产生 manifest；不在运行后改写执行代码。
- Smoke 与 targeted repeat 使用独立 Suite、Evaluation DB 和输出目录；不得计入 74 run。
- Benchmark 以 `--paired-by-case` 按同一 Case 的 standard→planned 顺序交替执行。首轮仪表 smoke 在先跑完 4 条 standard 后发生连续 Provider connection error；独立 fresh-client planned 探针成功，说明当次故障未证明 Planner 接口损坏。交替顺序缩短 A/B 时间间隔，但不消除同一窗口的 Provider 随机故障；原 smoke 保留为诊断记录，不作为正式结果。

## 判定与边界

分别报告 completion、valid answer、expected fact coverage、evidence recall、citation/grounding 及适用的类别指标；指标的 available/not-applicable/unavailable 状态保留。只有同一 Case 上同口径且 GT-backed 的指标可做 paired delta。优先判定：一侧 completed 且另一侧没有完成；其次比较同一已定义的 GT-backed 质量维度。不同维度冲突或只有 answer 文字不同而没有可用 GT 指标时标 `needs_review`，不造综合分数。`same` 表示可观测的既有质量指标相同，并不证明语义答案等价。

Provider/Planner 失败与答案质量分开；Provider error 不作 Planner 的质量损失推断。Tool sequence 变化只证明行为变化，不自动证明 plan 因果有效。针对关键差异输出答案、GT、Evidence/Citation、Planner 摘要、Tool sequence 和自动指标供人工复核；含原始答案的 review packet 仅留 local ignored 目录。

## 开发前七问

责任：测量现有 Planner treatment，不重新设计其职责。失败：Settings、索引漂移、Provider、Planner parse/timeout、Runtime、Evidence/Citation。观测：raw/Evaluation/normal Trace 以 run/trace ID 关联。归因：按原有 failure code 与 stage；无法区分时标未知。技术取舍：复用 Benchmark Runner/GT，新增最少 projection，避免第二套执行器。验证：smoke、37×2、targeted repeat 和工程检查。回归：只有发现可复用实现缺陷时新增测试/Problem Record；普通实验结论沉淀 ADR。
