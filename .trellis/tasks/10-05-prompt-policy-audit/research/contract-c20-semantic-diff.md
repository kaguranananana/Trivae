# C20 contract / semantic diff

- Removed/Moved/Reworded：无Prompt变化；两个Tool description原文不动。
- Added：lexical/legacy共用factory的default_limit与8项SDK/真实FTS测试。
- Unchanged high-risk policy：lexical routing、keyword/filter/context2/2、discussion20/40、停止/负面/时间。

复现6 failed/2 passed：scope1/10的公开默认值是1/10但SDK实际1000；真实scope5省略值直接返回越界error。现在factory先计算同一default供函数及Schema使用，两个名称均符合scope；正常默认1000不改，显式越界值仍由既有Host拒绝，不做运行时夹取或fallback。

Static274 passed in2.67s；Ruff/mypy116通过；实际小scope FTS两名称各返回已知1命中。Provider=0、new tokens=0、cost=0；只修已公开契约，不生成Prompt删除或宣称语义等价。
