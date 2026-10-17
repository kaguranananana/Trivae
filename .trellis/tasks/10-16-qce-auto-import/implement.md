# 执行计划

- [x] 建立现有 ingestion/CLI baseline；实现 additive 状态存储和 batch 恢复。
- [x] 实现稳定文件快照、import_paths 编排、索引工作接口及进程锁。
- [x] 添加轻量 bootstrap 装配与独立 import-once CLI，保持 TrivaeApplication 不变。
- [x] 实现 launchd 安装准备、状态、卸载和运行说明；真实任务保持未启用。
- [x] 测试独立 SQLite：空目录、历史接管、新/变更、重复、partial、非法 JSON、稳定采样、复制期间变化、中断、索引补偿、互斥。
- [x] 执行独立 CLI 和 macOS launchd smoke；确认原目录不受影响。
- [x] Ruff、mypy、pytest、diff 检查；记录集成依赖与实测限制。
- [x] 更新 spec。
- [x] 本轮独立开发与复核完成；收尾提交、journal 和远端同步以本分支 Git 记录为准。
- [x] 与已完成的转发检索代码合并，隔离验证和完整回归通过。
- [x] 启用阶段：接入既有索引构建入口，仅新增数据触发，每种索引合并待办为一次构建。
- [x] 隔离验证无变更不构建、重复导出不构建、嵌套转发和失败/中断补偿。
- [x] 按用户新授权安装并启用 main 的 10:30/22:30 LaunchAgent，首轮 40 文件完成，新入库 23,087，FTS 与 Agent lexical/recent 工具已验证。
- [ ] 语义全库构建完成后验收真实 semantic / Query / Citation（目前 building，明确不宣称已完成）。
- [ ] 生产整链路验收完成后归档；语义局部增量算法保持独立演进项。

停止调度使用卸载脚本，保留 Canonical、原始文件及日志；不得删除既有数据。生产启用按用户本轮明确授权执行，整链路结果另行记录。
