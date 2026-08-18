# Directory Structure

> 目录与文件组织约定。**当前阶段（Stage 0）：无业务代码。**

---

## 当前结构

```
.
├── .trellis/          # Trellis 工作流（spec / tasks / workspace / scripts）
├── .opencode/         # OpenCode Trellis 集成（plugins / agents / commands / skills）
├── AGENTS.md          # AI 会话项目指令（Trellis 管理块 + 项目内容）
└── .gitattributes
```

## 约定（Stage 0 生效）

- **不创建未经确认的业务模块结构**：Python package 布局、`src/` 或顶层包等一律等待 Architecture Specification。
- 业务代码尚未出现（验收标准之一）。

## 后续阶段（架构到达后补充）

- Python package / module boundary → 由 Architecture Specification 定义后填入本文件。
- 测试目录布局 → 随首份业务代码的确定落地（预计 pytest 结构，工具链在进入 Stage 1 时确定）。