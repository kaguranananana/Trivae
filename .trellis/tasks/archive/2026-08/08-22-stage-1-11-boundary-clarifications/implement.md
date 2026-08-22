# Stage 1.11 应用边界契约修订执行计划

## 1. 实施范围

本 task 只更新架构文档、同步索引和 Trellis 记录，不创建 Python 包、不改 CLI/API 代码、不引入新目录层级。

## 2. 执行顺序

1. [x] 在 Stage 1.11 ADR 中补齐双层依赖规则、Application facade、factory ownership、core/server lifecycle、trusted Query context、Evaluation 边界和 Trivae Home 命名空间语义。
2. [x] 更新 project architecture、overview、workflow 中的 Stage 1.11 摘要，使其与 ADR 使用同一组术语。
3. [x] 更新 backend index、directory-structure、quality-guidelines 中会影响实现的边界提示。
4. [x] 使用文本搜索检查旧措辞、混合依赖箭头和过时的 factory/lifecycle 描述。
5. [x] 运行 Trellis 校验、Markdown 链接/内容一致性检查和 git diff --check。
6. [x] 更新 implement/check 清单，提交文档变更，并归档 task。

## 3. 目标文件

- .trellis/spec/project/technical-decisions/stage-1-11-application-architecture.md
- .trellis/spec/project/architecture.md
- .trellis/spec/project/overview.md
- .trellis/spec/project/workflow.md
- .trellis/spec/backend/index.md
- .trellis/spec/backend/directory-structure.md
- .trellis/spec/backend/quality-guidelines.md

## 4. 一致性检查

正向检查词：

- Runtime Call Flow
- Source Dependency Rule
- Trivae Application Factory
- HTTP ASGI/Server App Factory
- trusted Application context
- conversations 与 traces
- logical namespace
- thin execution adapter

反向检查词：

- domain → infrastructure 作为唯一依赖规则的旧表述
- Application factory、dependencies、routes 混为一个 owner 的旧表述
- CLI、HTTP API、Evaluation 是三个薄入口
- Trivae Home 的概念边界为物理目录映射
- QueryRequest 字段可由普通客户端直接声明或扩权

## 5. 验证命令

- [x] python3 .trellis/scripts/task.py validate 08-22-stage-1-11-boundary-clarifications
- [x] git diff --check
- [x] 使用 rg 检查正向和反向词是否符合预期。
- [x] 使用脚本解析 implement.jsonl、check.jsonl，确认每行都是有效 JSON。
- [x] 检查修改后的 Markdown 相对链接目标存在。

## 6. 风险与回滚

主要风险是摘要文档与权威 ADR 出现术语漂移，或为解决表述问题意外引入新的架构层。实施时以 ADR 为唯一语义源，并限制同步文档只做摘要更新。

如果一致性检查发现范围超出 Stage 1.11，可在提交前用 apply_patch 逐项撤销对应文档段落；不使用 broad reset 或覆盖用户已有变更的操作。
