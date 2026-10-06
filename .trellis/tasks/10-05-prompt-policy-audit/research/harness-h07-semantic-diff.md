# H07：并行首调用的未完成解析不能通过probe

Scope：first-tool同轮解析完成性。Risk：低，Harness。Prompt lines：0。Owner：CLI / SDK观测。Expected/Maximum Provider calls：0/0。

H06仅核对终止异常；交换坏/合法首调用顺序，SDK先返回合法call的FirstToolProbeStop，同轮坏call已留raw但未解析，CLI仍继续后case。新增反向顺序fixture：1 red/2 green。根因是并行异常先返回不代表整轮调用都合法解析；不是Provider随机性，不应付费repeat。

Removed/Moved/Reworded：无Prompt变化。Added：对所有已观测probe_calls的解析完成检查、反向fixture。Unchanged high-risk：production Base/P16及所有路由/窗口/停止策略不变。

SDK异常保持真实类型：坏在前UserError、合法在前FirstToolProbeStop；后者不能遮蔽raw-only坏调用。任何已记录调用缺少解析arguments即拒绝probe并停止下一case。没有吞异常/补参数/额外重试；失败artifact和canonical Trace原样保存。

static289 passed in2.91s，Ruff/mypy116通过；三场景通过，坏/合法两个顺序均只执行一个模型轮、Host0、无下一case artifact；合法两case仍执行。新API/tokens/cost=0；累计2次真实V01、tokens/cost未知。接受Harness修复，不是Prompt语义gate。
