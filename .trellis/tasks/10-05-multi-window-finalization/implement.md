# 实施

- [x] 新增真实 Tool → record → finalize → codec 的多窗回归，确认修改前失败。
- [x] 按窗聚合时间和 coverage，保持源级边界与既有坏输入测试。
- [x] 同步 codec、Trace、规范；复放真实 Trace 的六窗事实。
- [x] 执行 targeted tests、Ruff、mypy、全量 pytest；记录真实结果。

回滚范围仅限本任务文件，不触碰已有 WebUI 修改。
