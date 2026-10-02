# 验证记录

## 正式请求前
- 首轮全量 pytest 657 passed/17.72s；补强 raw model_output ownership 与 Judge 入口日期测试后，全量 **659 passed/16.76s**。
- ruff check src tests evaluation scripts 通过；mypy src 115 source files 通过；git diff --check 通过。
- 参数契约：SDK generated schema 字段说明；搜索投影短handle；当前run resolver；canonical直接调用；错误字段MESSAGE_NOT_FOUND；model_output raw source_id 与 Tool Trace canonical message_id 分层。
- 日期：保留 low-r2 原 Claim/Evidence/Citation，日期比较稳定否定已明确编码的同日关系，验证时间顺序/间隔；既有 Judge 输入保留UTC时间。mock判定只验证 parser/投影，不宣称自动语义质量。
- preflight-v1失败原样保留，正式attempts/paid HTTP=0；v2通过，无付费请求。
- 根目录 Ruff 62个已存在问题全部对应未改文件；不把 scoped lint 通过写成整个仓库根扫描全绿。

## 正式 E2E

- execution commit14de11f；8既有Case×2treatments×1、相邻AB/BA四对各四对，16/16 E2E完成、valid artifact16/16。不是答案正确率。
- 54实际HTTP/54响应200：Planner8、Runtime46；8/8有效Plan，0provider_length；无SDK重试、无额外repeat。
- Standard Planner0、Planned1，Router/Jev0调用；八对实际首次Runtime HTTP去掉production renderer guidance后完全相同。
- 36业务Toolcalls，0Toolerrors；11context raw全部source_id=mN-K、normalized canonical message_id；36原始function/Tool序列对齐。
- 16 raw/16 Trace/16 AnswerArtifact/16 Evaluation；SQLite run/trace IDs与raw一致；16 conversations/32 messages。
- semantic source audit完成16条全部Claim/来源binding，并保留原low-r2日期失败重点。明确非人工adjudication、非独立盲审，未付费Judge。
- 质量限制：两路dependent/context required reply均漏取；P cite漏写已取到7k；P temporal把10h26m12s写成一天多、无支持频率判断；S dependent也错误合并后续关系。零结果/排名/聚合正确，不能把结构性通过扩写为语义全通过。
- 工程结论：限制使用、保留架构、routing继续保守；16次后停止，0targetedrepeat，无新付费Planner实验安排。局部新关系/覆盖问题未改变该保守决策，详细停止理由见report/source-audit。

## 收口后复检（2026-10-03）

- `uv run --extra dev --extra semantic pytest -q`：**659 passed in 16.22s**，完整输出pytest-final.txt。
- `ruff check src tests evaluation scripts .trellis/tasks/10-02-planner-engineering-closure/analyze_closure.py`：通过。
- `mypy src`：115 source files通过；`git diff --check`：通过。
- 额外根目录Ruff仍为62个既有问题，与正式前诊断逐条相同，21文件均与221f57a逐字相同；ruff-root-final-diagnostics.json保留，不声称根扫描通过。
- 重新离线分析raw，analysis.json/semantic-review-packet.json逐字一致；检查132 frozen files与当前源码/Case逐字一致；当前生产Application materialized Snapshot仍相同。
- 历史两次实验artifact与原Case/GT无修改；Evaluation/Trace IDs及全部正式分母再次核验；见final-integrity.json。复核0新增付费请求。
- 已更新PRD/design/report/ADR/runtime guideline/architecture/README/interview evidence。completed任务留原目录，保持冻结路径和链接稳定；不自动创建新任务。
