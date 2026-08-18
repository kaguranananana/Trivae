# Architecture Status

> 当前状态：**Pending architecture specification**
> 正式 Architecture Specification 到达前，本文件之外不假设任何架构。

---

## 已确认

- 语言：Python
- 领域：高噪声群聊技术情报分析（QQ 技术群等）
- 参考：ChatLab（借鉴范围、映射方式待正式规格）
- 输出形态：可追溯到原始聊天消息的证据型回答

## Pending architecture specification（不可自行决定）

以下内容等待正式架构文档，**不得自行补全或实现**：

- 系统整体架构
- Python package / module boundary
- 数据模型核心结构
- Database schema 关键设计
- Ingestion architecture
- Retrieval architecture
- Keyword / Semantic / Hybrid Retrieval 选型
- 是否增加 Reranker
- Agent Runtime 设计
- Router 架构（Rule / LLM / Hybrid）
- Planner 架构
- Tool architecture
- Context architecture
- Evidence / Citation model
- Evaluation architecture
- API / CLI 边界
- Retry / Fallback 策略
- 会明显改变系统复杂度的新依赖或基础设施
- Trace Schema（Observability 具体结构）

## 决策沉淀

- 正式架构文档到达后：内容摘要与映射关系沉淀到本文件或 technical-decisions.md。
- 后续重大决策按 [technical-decisions.md](./technical-decisions.md) 记录。

## 发现架构问题的处理流程

实现过程中若发现已确认架构存在重大问题：

1. 记录：`Problem / Evidence / Impact / Possible Options`
2. 停止对应架构改动
3. 等待新的设计决策（记录位置：problem-records.md 或对应 task）