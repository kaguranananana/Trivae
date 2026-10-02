# 验证记录

## 正式请求前
- 首轮全量 pytest 657 passed/17.72s；补强 raw model_output ownership 与 Judge 入口日期测试后，全量 **659 passed/16.76s**。
- ruff check src tests evaluation scripts 通过；mypy src 115 source files 通过；git diff --check 通过。
- 参数契约：SDK generated schema 字段说明；搜索投影短handle；当前run resolver；canonical直接调用；错误字段MESSAGE_NOT_FOUND；model_output raw source_id 与 Tool Trace canonical message_id 分层。
- 日期：保留 low-r2 原 Claim/Evidence/Citation，日期比较稳定否定已明确编码的同日关系，验证时间顺序/间隔；既有 Judge 输入保留UTC时间。mock判定只验证 parser/投影，不宣称自动语义质量。
- preflight-v1失败原样保留，正式attempts/paid HTTP=0；v2通过，无付费请求。
- 根目录 Ruff 62个已存在问题全部对应未改文件；不把 scoped lint 通过写成整个仓库根扫描全绿。

## 正式 E2E
待限定16次运行完成后记录，不自动扩样。
