# P07 semantic diff

Parent=P06；production原文不动。

- Removed：`keyword must be exactly one string. `（36字符）。
- Moved：Base候选→已有Tool description/SDK string类型与SearchMessagesInput。没有新增运行时实现。
- Reworded：无；Added：14项SDK/typed input/实际Schema测试和候选manifest条目。
- Unchanged high-risk policy：关键词如何选、lexical-first、实体锚点、optional filter、讨论、negative、temporal、stop全部原字节与顺序不动。保留原大小写及空白，不顺手整理周边句子。

修改前14项全部通过：两adapter拒绝bool/number/list/object，registry零调用；typed input也拒绝这四种原类型。实际Schema是string、工具description公开exactly one non-empty string，合法anchor沿原路径执行。本轮不增加minLength、canonical格式或字符串规范化算法。

static=141 passed in2.14s、Ruff/mypy116通过。Provider=0；候选20,079字符。只接受L0开发候选，尚不替换production或声明模型行为等价。
