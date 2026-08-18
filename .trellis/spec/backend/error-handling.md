# Error Handling

> 错误处理长期原则（源自工程原则第 1、3 节）。
> 具体异常类型体系、错误契约等待 Architecture Specification。

---

## 核心原则

1. **根因优先**：异常 → 先复现、定位根因、修复主链路；不掩盖问题。
2. **错误显式暴露**：禁止静默吞错（silent error swallowing）；错误必须可见、可定位。
3. **最小修复**：不做超出根因范围的改动，不加无依据的分支。

## 禁止

- `except Exception: pass`（或等价静默吞错）。
- 用 fallback / 兼容分支 / 启发式后处理掩盖主链路问题。
- 针对单个样例的特殊规则。

## Retry / Fallback（默认不加）

仅当真实 Failure Case 证明存在可恢复的 transient error（外部 API 短暂失败、网络抖动、模型偶发格式错误）时才引入。引入必须说明：

- 触发条件
- 为什么主链路无法直接解决
- 最大次数 / 边界
- 失败后如何暴露错误
- 测试覆盖
- 相关指标

## 架构级错误处理（Pending）

以下内容等待 Architecture Specification：

- 异常类型体系 / 错误码设计
- Tool 参数错误处理策略
- Agent Loop 错误恢复策略