# C23：recent可选数组非空契约

Iteration ID：C23。Scope：get_recent_messages.session_ids/sender_user_ids的数组形状。Risk：低。Prompt lines：0。Owner：SDK / GetRecentMessagesInput。Expected/Maximum Provider calls：0/0。

输入：可选数组；输出：合法typed filters或明确解析错误。依赖：原SDK/Host。成功：minItems=1公开且空数组在registry前拒绝，合法值原样送达。失败：保留SDK错误，不补filter或更换时间窗。验证：2 SDK空数组、2原Host拒绝、3合法形式。演进：时间/cursor/身份策略不动。

Removed/Moved/Reworded：无。Added：两字段min_length=1及7 tests。Unchanged high-risk：production Base/P16候选、Tool description、time默认/互斥/cursor和filter选择不变。Base只要求unused时omit session_ids，此判断仍归模型，不删。

5 red/2 green：原Host已拒绝空数组，SDK没有解析拒绝且Schema缺minItems；合法值已保持，仅Schema断言失败。修复与已公开Args非空契约一致；省略/null/合法数组及typed default amount2/day/archive_latest、limit10、cursorNone原样保持。只验证typed projection，不能当真实时间问答或授权测试。

static305 passed in3.18s、Ruff/mypy116通过。接受contract/L0；Schema改变需新的同条件验证，旧V01不外推。新增API/tokens/cost=0；累计真实2请求，总token/费用未知。
