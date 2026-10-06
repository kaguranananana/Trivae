# 等价重构设计（第一批已批准）

## 问题与选项

20,450 字符的 Runtime Prompt 混合了选择策略、参数、Host enforcement、输出和历史反例。仅加标题无法减少重复；一次性下沉所有约束又会依赖当前不存在的 Structured Outputs/Schema 关系约束。

建议选用分批等价重构：第一批 Markdown 分层、同义规则合并、删除单行字面重复、压缩已有工具/Host 承接的实现说明。第二批仅在第一批回归成立且确有参数 Failure Case/契约需求时，补必要 Schema。Structured Outputs 是独立 provider 能力任务，不作为缩 Prompt 的先决条件。

## 稳定 Policy 层级

```text
Role and answer principles
Retrieval policy
  Recent overview
  Precise and conceptual lookup
  Discussion investigation
  Resource inventory
  Identity and structured statistics
Context and stopping policy
Evidence policy
  Author, chronology, strength, coverage
Output policy
  Semantic candidate + current source handles
  JSON claims / no_result generation contract
  Complete prose, bounded metadata
```

具体规则映射见 [prompt-policy-audit.md](research/prompt-policy-audit.md)。每个 Policy 的事实性表述只保留一个主位置；工具描述保留局部用途、字段语义和容量，不再制造第二份跨工具总策略。

## Ownership 与数据流

`SYSTEM_PROMPT + 动态预算 + soft Plan → SDK Tool Schema/description → typed input / Capability → scoped Retrieval → ToolResultRecord / model projection → 模型语义候选 → Finalizer → AnswerArtifact`。

- 模型：按意图选证据、调查锚点、作者/时间/推荐/使用关系、覆盖与结论强度、用户可读正文。
- Tool Schema/description：参数类型、可见上下界、source_id/message_id 用法、context 单位。Schema 无法替模型选择完整清单 limit，也无法识别昵称指谁。
- Host/Capability/SQL：trusted scope、archive_latest、UTC、游标、只读、实际输入校验。保持已有模块 ownership。
- Runtime：既有轮次与结果投影预算、动态剩余事实，不新增语义去重状态机。
- Finalizer：候选形状、引用、hydrate、scope/provenance、verified empty proof、现有 degraded/failed 诊断。校验通过不代表自然语言 entailment 正确。
- Evaluation：具体反例与模型行为比较，不通过生产 Prompt 堆样例补丁。

## 第一批保留与限制

保留 github.com-first 的当前 intent 范围、lexical inventory max/0 context、独立 semantic/category 补证、discussion anchor 优先 context、canonical identity、Host UTC、部分不能穷尽、无意义重复/error-loop 停止、完整正文和最小 claims/no_result JSON contract。

不改变任何工具名字、默认窗口/limit、Host enforcement、轮次/预算、Plan、Provider 配置、Finalizer recovery 和公共输出字段；不删除尚未具备 Schema 描述的必要参数用法。机械规则压缩必须能指出已存在的承接点，不能为了字数目标先删再补。

## 验收、观测与回滚

先跑当前 provider-free baseline，再固定数据/scope/query/Provider/model/effort/预算/路由/Plan 条件进行 Baseline/Candidate Development 配对。若强制 Standard 则两侧同样强制；若使用 Planned 则两侧同一冻结有效 Plan，不能把重新生成的不同 Plan 当单变量。

保留实际 request/模型输入、tool calls/arguments/results、context 关键回复、final candidate/answer、引用、coverage、error/Trace、usage 和 latency。成对交错执行并保留重复结果；冷启动/cache 和 provider 方差单独记录。评审以具体推荐、作者、日期关系、链接、范围、负面结论为依据，不加机械总分或武断字符 gate。

质量退化先定位丢失的稳定 Policy/模型执行路径；不通过更换测试、扩大预算、增加 fallback 或固定关键词修补。未通过的候选不替换生产 Prompt；保留基线和失败产物用于下一轮判断。

## 关键模块 7 问

1. Responsibility：明确模型策略与机器契约，减少重复，输入/输出边界保持现状。
2. Failure Cases：去重误删讨论 context、清单顺序、身份/时序/empty-proof 指导；预期风险，不虚称本轮新复现模型失败。
3. Observability：现有实际请求、ToolResult/Trace/answer/usage；20k debug capture 不等于完整 SDK request，需另存可重建完整输入。
4. Failure Attribution：Tool Selection、Tool Arguments、Context、Evidence Selection、Answer Generation 与 Provider 分开，Finalizer valid 不作为质量替代。
5. Technical Decision：纯标题重排收益有限；全量下沉缺现有契约；分批去重能控制变量并复用既有链路。
6. Verification：审计一致性与 provider-free baseline；真正等价仍依赖新的真实配对评测。
7. Regression：复用上轮讨论案例、Archify 日期反例与 Development，保留已知残余错误，不造特殊规则。

## 规划状态

审计已完成；用户已批准第一批实施；后续由主会话直接实现和检查。Schema 扩展、Structured Outputs 和 no_result 语义纠正均未决定为本轮产品改动，不提前落地或写成已确认 spec。
