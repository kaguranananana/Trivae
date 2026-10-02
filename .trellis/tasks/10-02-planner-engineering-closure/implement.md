# 执行计划

1. 完整审计相关提交、任务、报告、规范、生产入口/测试及八条 GT。
2. 先建立旧契约与时间关系的 provider-free 失败复现，再修复 schema/prompt/Judge evidence projection。
3. 实现 bounded closure runner/preflight/tests，先 pytest/Ruff/mypy/diff check。
4. 提交生产与 runner，记录 clean execution identity；预检/正式运行固定 16 次。
5. 完整 ToolResult 与 canonical source 逐 claim 核验，必要时仅对一个新严重 case 2+2 重复。
6. 更新 report/validation/decision/runtime/README/interview evidence；明确 closed 与不安排进一步实验。
7. 正常 commit/push，fetch/rev-list 核对 ancestry，工作树 clean；保留历史目录。
