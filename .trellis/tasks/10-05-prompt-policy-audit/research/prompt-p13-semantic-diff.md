# P13 semantic diff

Parent=P12；production原文不动。

- Removed：`send one\nSQL string and optionally max_rows; `（45字符）。
- Moved：Base候选→原SDK string/ExecuteSQLInput与新增max_rows strict/ge=1解析。
- Reworded：无；Added：单字段strict/ge、18项契约检查及static里的既有SQL主链路测试。
- Unchanged high-risk policy：SQL选择、schema调查、单语句/只读/scope及错误停止；discussion/negative/time/stop/routing全字节不改。

复现9 failed/9 passed：SDK先转换true/字符串/浮点数，nullable整数Schema分支未表达minimum；typed input已经拒绝原始非法值。现在SDK拒绝非法原输入且registry零调用；原SQL string拒绝不变。省略/null仍交Host推导trusted上界，合法1/10保持；真实Host超上界在repository之前拒绝。不改SQL解析、执行、默认行数或输出。

Static234 passed in2.80s，Ruff/mypy116通过；Provider=0、tokens=0、cost=0。累计候选19,818字符，只接受contract/L0；没有运行语义gate或替换production。
