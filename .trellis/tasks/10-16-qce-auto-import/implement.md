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
- [ ] 接入最终增量索引 updater、执行生产整链路验收，再完成 task 归档；当前不启用真实任务。

回滚仅移除本功能文件和新增表；不得删除既有 Canonical 数据。索引更新不在本任务默认执行，生产启用等待集成验收。
