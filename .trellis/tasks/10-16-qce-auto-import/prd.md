# QCE 本地增量导入与 macOS 调度

## 目标
QCE 写入 raw 目录后，Trivae 可独立发现所有尚未成功处理的 JSON，可靠导入 Canonical Store，并明确报告索引是否跟上。

## 范围与约束
- 每天本地时间 10:30、22:30，以 launchd StartCalendarInterval 调用 import-once；登录补查，失败后有界频率重试。
- 复用 SharedImporter.import_paths；稳定性检查、持久状态、失败恢复、CLI、安装/状态/卸载脚本属于本任务。
- 成功事务提交后才能标记文件 completed；partial / failed / writing 不得永久跳过。
- 首次运行根据成功批次筛选历史候选，并核对稳定快照与已有原始记录/provenance；无法证明完整导入时走现有幂等主链路。
- 只有 committed batch.inserted_count > 0 产生索引补偿工作；失败可观测，重启可恢复。
- 独立 worktree / 分支；开发测试只使用独立数据库和合成输入。2026-10-17 用户明确授权真实启用调度，完成隔离验证后安装 main 的 LaunchAgent。
- 不修改 QQ 接口、QCE 配置、原始 JSON、冻结 Evaluation、合并转发解析、FTS/语义/Evidence/Citation 核心。
- 合并转发任务已完成并合入 main；启用阶段接入既有索引构建器，新增待办才触发更新。局部向量增量不是现有接口能力，保持单独演进；生产端到端验收未完成前不得宣称可完整投产。

## 验收标准
1. 空目录成功退出；未变化文件重跑不解析；新/变化文件调用同一个 importer。
2. writing 文件明确 deferred；非法 JSON failed；单文件失败不阻止其他文件。
3. partial 可重试，冲突和 provenance 不变；提交前/后进程中断均不漏导。
4. 可信历史文件只做一次 JSON/provenance 核验，不重做消息规范化和重复写入；持久化版本后重跑不解析。未知或未完整导入的历史文件不被跳过。
5. 索引工作仅由实际新增创建；未接入/失败明确 pending/failed；补偿无需重新解析。
6. launchd plist 使用绝对路径、独立 Python 环境、工作目录、日志、进程锁、日历调度和失败重试；安装准备不自动启用。
7. 自动化测试覆盖重启恢复、休眠积压、重复导出、部分写入、JSON/导入/索引失败；独立 macOS launchd smoke 验证装载/运行/卸载。物理重启与休眠不得在共享开发机强行执行。

## 已确认事实
基于 main@22e464f；主工作区存在另一会话的转发检索未提交改动。SharedImporter 已有文件级事务、record partial、first-wins/variant 和 provenance；现有索引只有显式全量 rebuild。
