# Project Overview

> 简短说明，不展开架构细节（架构见 architecture.md，当前 Draft / In Progress）。

---

## 项目

**Trivae** — 使用 Python 实现的高噪声群聊技术情报分析系统。

## 目标

从大量 QQ 技术群等高噪声聊天记录中：

1. 根据自然语言问题寻找相关信息；
2. 分析其中的技术讨论；
3. 形成**能够追溯到原始聊天消息**的证据型回答。

## 核心特征

- 输入：海量、高噪声、非结构化的群聊文本；
- 输出：证据型回答（每个结论可追溯到原始消息）；
- 主要架构参考：[ChatLab](https://github.com/ChatLab/ChatLab)（借鉴范围与映射方式由正式 Architecture Specification 确定）。

## 已确认信息

| 项 | 值 |
|----|----|
| 语言 | Python |
| 领域 | 高噪声群聊情报 / 技术讨论分析 |
| 架构参考 | ChatLab（待正式规格） |
| 开发管理 | Trellis |
| 工程风格 | Simple / Explicit / Testable / Observable / Failure-case driven / Evidence-based |

## 当前阶段

**Stage 1.1 已完成**：Stage 0 的 Git、Trellis 与工程规范已完成；Data Plane + Query Plane 的架构骨架已沉淀，业务代码仍为零。

当前架构文档为 `Draft / In Progress`。Stage 1.2（Data Model + Ingestion）为下一阶段；Retrieval、Evidence、Trace、Database Schema 等细节仍为 Pending，不能视为最终 Architecture Specification。

**下一阶段**：Stage 1.2（Data Model + Ingestion）。在对应架构细节确认前不实现业务功能。

## 演进目标

持续把 Demo 演化为「可验证、可定位、可维护、可迭代」的工程系统，核心闭环：

```
实现 → 暴露问题 → 保存 Failure Case → 复现 → Trace/Log 定位 → 分析 Root Cause
→ 比较候选方案 → 最小合理修改 → 测试/Evaluation → 验证改善 → Regression → 文档沉淀
```

详见 [engineering-principles.md](./engineering-principles.md)。
