# Bootstrap Task: Fill Project Development Guidelines

**You (the AI) are running this task. The developer does not read this file.**

## 项目背景（与模板的差异）

本项目是 **Python 后端项目**（高噪声群聊技术情报分析），无 frontend。
`trellis init` 以 fullstack 模板生成了 backend + frontend 空白 spec，其中：

- **frontend 层不适用**，已删除。
- **backend 层**已按工程级原则填写（Stage 0 无业务代码，只写长期规范，不写代码模式）。
- 新增 **project 层**：Project Overview / Engineering Principles / Architecture（Pending）/ Workflow / Problem Records / Technical Decisions。

## 完成情况（Stage 0）

- [x] 项目级长期规范（project 层）已创建
- [x] backend 层（Python 工程规范）已填写
- [x] frontend 层已删除（不适用）
- [x] Architecture 标记为 Pending architecture specification
- [x] 未编写业务代码，未安装业务依赖

## 验收提示

- `.trellis/spec/` 无模板占位符（"(To be filled)"、"To fill" 等）。
- `index.md` 与各层实际文件集合一致。
- `get_context.py --mode packages` 正确列出 spec 层。

## Completion

完成后运行：

```bash
python3 ./.trellis/scripts/task.py archive 00-bootstrap-guidelines
```

归档后，新开发者将获得 `00-join-<slug>` 引导任务。