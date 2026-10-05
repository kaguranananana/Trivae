# 执行计划

1. 保存 baseline 代码，检查原案例和现有运行入口。
2. implement 子代理负责四处产品修改及契约测试；root 负责隔离真实实验、任务材料和规范。
3. 运行正式工具 probe、相关测试、Ruff 与 mypy。
4. 重复两次 baseline/candidate 配对，逐项检查实际回复、作者、日期、错误否定及内容相关性；回归其他四类问题。
5. 使用 trellis-check 检查最小 diff，运行全量后端测试，记录实际结果与未改善项。
6. 更新规范、validation 与会话记录。本次未授权新的提交推送，不自动提交。

命令：`.venv/bin/python -m pytest`、`.venv/bin/ruff check src tests`、`.venv/bin/mypy src`、`.venv/bin/python .trellis/workspace/anontokyo/retrieval_quality_probe.py`。
