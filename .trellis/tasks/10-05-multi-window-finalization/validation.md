# 验证记录

## 实测结论

- 新增多窗回归在修改前经过 Tool → ToolResultRecord → Finalizer，稳定报原 TIME_RANGE_MISMATCH；修改后通过。
- 实现按窗聚合，不改变 source-local 引用时间约束；现有损坏快照、同窗 coverage 冲突和新增多窗半开边界越界均保持显式失败。
- 新增 SDK → Application Query → Conversation commit → normal Trace 回归通过。
- 原 Trace 六次 recent 请求在现有 canonical 数据上只读重放通过；逐窗 coverage 与原 Trace 一致：200/415、1/5629、1/3610、1/1869、1/883、1/108。均仍为 partial，没有伪造完整覆盖。
- 两份此前真实持久化答案（没有 retrieval_windows 字段）经新 codec 可读。
- `python -m pytest -q`：661 passed，16.81s。
- Ruff 对修改的源码、测试和重放脚本通过；mypy：115 source files 无错误。
- `git diff --check` 与 Trellis task validate 通过。
- 已重启当前项目的本地后端；`/api/readiness` 返回 HTTP 200，database ready、semantic completed、provider ready。

## 取舍与边界

主链路根因是将所有独立时间窗当成同窗分页。选择逐窗 Host 事实；未选择取首窗/最大窗、删除时间校验、扩大预算或 retry。新增答案字段不要求数据库迁移；旧字段仍描述单窗，多窗无可定义的单值总体覆盖率。查找和分组随 recent record 数线性处理，组内沿用现有唯一消息计数。

真实数据重放固定工具参数和最小有来源答案，没有重新调用模型，不证明模型会改善时间参数、停止策略或自然语言内容质量。检索召回与回答组织属于后续质量工作。

验证期间发现 normal finalization Trace 顶层字段已经达到 capture 上限；逐窗事实改由 evidence.prepare.completed 保存，避免新事实被截断并保持既有 finalization 事件结构。

项目 .venv 缺 pytest，已安装 pyproject 声明的 pytest 8.x 开发依赖。最初 unittest discover 未加载 pytest 的离线 fixture，产生环境依赖错误；正式全量结论使用 pytest，不以该错误运行判断产品修复失败。
