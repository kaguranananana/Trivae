# M7 Real DeepSeek Baseline Design

## Scope

本 follow-up 只执行已经确认的 M7 baseline contract，不修改 Evaluation 架构。运行边界保持：

```text
temporary real-data Snapshot
  -> Case/Suite + last-stable-m6 Variant
  -> EvaluationRunner
  -> TrivaeApplication.query()
  -> QueryOrchestrator -> Router/Planner/Runtime/Tool/Retrieval
  -> Answer Artifact + canonical Trace
  -> deterministic checks + EvaluationResult
```

不使用 scripted model，不自动 retry，不把失败包装为成功。

## Dataset and Variant

- Canonical SQLite 先复制到系统临时目录；只在副本重建 FTS5。
- Snapshot identity 由 `DatasetSnapshot.from_database()` 生成；Evaluation Store 与副本 Canonical/Trace/Conversation Store 分离。
- 使用 `evaluation/variants/last-stable.json` 的 `last-stable-m6`，pin 到 M6 `cce944d`、`deepseek/deepseek-v4-flash`、temperature/top-p、M6 prompt、Router/Planner/Runtime、lexical retrieval、tool budget 和 Evidence/Citation version。

## Case slice

本轮固定 8 个不含私有正文的 Case：simple keyword、trusted session、context expansion、no result、insufficient evidence、partial/truncated retrieval、evidence-backed answer、Planner utility。Reference Truth 未冻结时保持 `not_reviewed`，不计算质量分数。

## Failure handling

真实 Provider 或 Finalizer 失败时保留 QueryResult/Trace/Run facts；只根据 Trace 建立 `FailureDiagnosis`。若 owner 或根因证据不足，使用 `likely` 或 `unresolved`，不通过关键词自动确认。
