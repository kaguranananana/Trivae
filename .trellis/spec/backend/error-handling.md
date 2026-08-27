# Error Handling

> 错误处理长期原则（源自工程原则第 1、3 节）。
> Stage 1.9 已确认跨层 Error Code ownership 与 Failure Attribution 原则；M6 已落地 Trace failure attribution 与 safe `TRACE.*` diagnostics，完整 user-facing Exception/API mapping 仍待实现。

---

## 核心原则

1. **根因优先**：异常 → 先复现、定位根因、修复主链路；不掩盖问题。
2. **错误显式暴露**：禁止静默吞错（silent error swallowing）；错误必须可见、可定位。
3. **最小修复**：不做超出根因范围的改动，不加无依据的分支。

## 禁止

- `except Exception: pass`（或等价静默吞错）。
- 用 fallback / 兼容分支 / 启发式后处理掩盖主链路问题。
- 针对单个样例的特殊规则。

## 异常包装必须保留根因文本

把底层异常转换为项目错误类型时（`raise ProjectError(...) from exc`），新 message 必须包含原始异常的完整 `str(exc)`，不得只记录 `type(exc).__name__`。原因：Tool Result / Trace 只投影最终 message，丢失原文会让网络瞬态、缓存损坏、配置错误等不同根因在日志中不可区分，只能靠事后复现定位。

- 推荐格式：`f"...: {type(exc).__name__}: {exc}"`；保留 `from exc` 维持异常链。
- 失败路径测试断言注入异常的原始文本出现在转换后 message 中，而非只断言异常类型。
- 参考实现：`src/trivae/retrieval/semantic/embedding.py`（2026-08-27 `SEMANTIC_EMBEDDING_FAILED` 排障教训：trace 中只剩 `ValueError` 类名，根因不可判读）。

## Retry / Fallback（默认不加）

仅当真实 Failure Case 证明存在可恢复的 transient error（外部 API 短暂失败、网络抖动、模型偶发格式错误）时才引入。引入必须说明：

- 触发条件
- 为什么主链路无法直接解决
- 最大次数 / 边界
- 失败后如何暴露错误
- 测试覆盖
- 相关指标

## 架构级错误处理

已确认：

- 首个破坏本层 contract 的组件拥有 Error Code；Wrapper 跨层传播时不得改名覆盖根因。
- Failure Attribution 区分 `origin_stage`、`observed_stage`、handling 与 Query terminal outcome。
- Router / Planner degradation、Tool Contract Error、Runtime Failure、User Abort 与 Budget exhaustion 分开表达。
- 未分类 Tool / Adapter 异常不得转换成 generic model-visible Tool Error 来吞掉实现缺陷。

仍 Pending：

- 具体异常类型体系、完整 Error Code 枚举与 Exception mapping
- user-facing error message 与 API mapping
- 更完整的 user-facing logging/API mapping 与部署级 Trace payload retention policy
