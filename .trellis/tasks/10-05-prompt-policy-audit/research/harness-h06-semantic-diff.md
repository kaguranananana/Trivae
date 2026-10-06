# H06：首工具预期截停与真实异常分离

Iteration ID：H06。Scope：first-tool终态分类及失败原始参数诊断。Risk：低，实验Harness。Prompt lines：0。Owner：ScreeningRuntime / CLI。Expected/Maximum Provider calls：0/0。

输入：现有case / production query / 首轮模型调用。输出：原始choice、参数、实际异常、既有Trace与ledger。依赖：同一Application.query、SDK、EvaluationRunner。成功：只接受FirstToolProbeStop作为实验截停；未知错误立即停止剩余case。失败：保留artifact与失败Trace，不改异常，不重试。验证：ScriptedModel同轮坏JSON+合法call及全部合法call。演进：不修改生产Runtime或Prompt。

Removed：无Prompt文字。Moved：无Prompt责任。Reworded：无。Added：实验原始arguments_raw及精确终态判断。Unchanged high-risk policy：全部生产Base及P16候选逐字不动。

旧实现json.loads先于append，坏调用失去choice；同轮合法调用留下probe_calls，使CLI仅凭非空记录与Host零调用接受真正失败并执行后一个case。测试在原实现明确DID NOT RAISE。先保存raw，再解析；SDK将JSON解析错误包装成UserError，保留实际类型，不宣称Trace一定是JSONDecodeError。CLI只认可FirstToolProbeStop。原测试错误地假设Trace含单个failure字段，按真实versioned Trace/run投影定位修正；停止后续case断言不放宽。

静态276项通过、Ruff/mypy116通过。Malformed case模型只调用1轮、后case artifact不存在、Host0、Provider ledger0；合法双case正常记录FirstToolProbeStop，Host0。接受Harness修复，不是Prompt语义等价结论。新API/tokens/cost=0，本会话累计真实请求仍V01的2次，累计tokens/cost未知。
