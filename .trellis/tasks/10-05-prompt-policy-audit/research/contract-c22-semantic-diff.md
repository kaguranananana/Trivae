# C22：semantic可选数组的现有非空契约

Iteration ID：C22。Scope：semantic session_ids/sender_user_ids/message_types的数组形状。Risk：低。Prompt lines：0。Owner：SDK / SemanticSearchInput。Expected/Maximum Provider calls：0/0。

输入：可选数组。输出：合法typed filters或明确错误。依赖：既有SDK/Host。成功：Schema公开minItems=1并由SDK实际拒绝空数组，omit/null/合法数组原值保持。失败：SDK在registry前显式失败，不补filter或换工具。验证：3空数组SDK、3原Host拒绝、3合法形式/Schema。演进：filter选择、canonical identity及authorization不变。

Removed/Moved/Reworded：无。Added：三个Field(min_length=1)与9 tests。Unchanged high-risk：production Base/P16候选及Retrieval/Discussion/Negative/Temporal/Stop全部原文不动。Base空数组规则仅针对lexical/legacy，不能虚报semantic Prompt删除。

6 red/3 green：Host原来确实拒绝三个空数组，SDK原返回error envelope而非解析拒绝；合法省略/null/数组值原已送达，但Schema缺minItems。修复让Schema与SDK共同承接既有Tool description/Host约束，未增加item格式规则或身份推断。合法数组参数测试使用RecordingHandler证明typed projection，不能当作真实授权/semantic召回测试。

static298 passed in2.55s，Ruff/mypy116通过。接受L0契约修复；新Schema再次改变冻结条件，旧V01不可当本轮同条件结果。新API/tokens/cost=0；累计仍2次真实请求且总token/费用未知。
