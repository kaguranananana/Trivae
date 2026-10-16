# Execution

- [x] 审计 QQ parser、Canonical、FTS、semantic、context 和 Evidence 边界。
- [x] 建立真实 Failure Case baseline 和数量统计。
- [x] Storage/lexical：递归投影、统一 MessageProjection、FTS rebuild/read、context/range、版本检测与回归。
- [x] Semantic：子消息分块、恢复、范围过滤、版本与计数、真实媒体 caption 修复与完整正文生成检查。
- [x] Evidence：model projection、trusted snapshot、序列化、source 展示与回归。
- [x] 集成测试，真实 QCE 与 Agent E2E 验证，安全切换派生索引并记录性能。
- [x] 修复已复现的长跑中断恢复：同版本/水位显式 resume，复用 20104 块、完成 92288 块并通过校验/切换。
- [x] 全量 Qwen：92288 chunks、4903 转发范围回读、原始文件/Canonical 不变、校验后原子切换。
- [x] 全库真实候选 rank28 截断与情感正文32字裁剪根因修复；独立 review 和默认预算真实重投影通过。
- [x] uv run ruff check src tests；uv run mypy src；uv run pytest；必要文档/spec 与验证记录（1057 Python、69 Web；两组全库 Agent 四项最终运行全部通过）。
- [x] 工作提交、归档/journal 提交、按长期授权统一 git push；只暂存本任务文件。

所有实现须有简体中文注释，关键逻辑逐行说明。并行任务严格按文件 ownership，不能撤销其他任务编辑。用户授权覆盖本次重复的流程确认；仍先落盘规划、验证再收尾。
