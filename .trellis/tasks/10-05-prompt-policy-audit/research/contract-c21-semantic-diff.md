# C21：semantic邻居窗口的非负整数契约

Iteration ID：C21。Scope：semantic_search.context_before/context_after。Risk：低，确定性参数合法性。Prompt lines：0。Owner：SDK解析 / SemanticSearchInput。Tests：真实FunctionTool原始类型、合法默认和窗口。Expected/Maximum Provider calls：0/0。

输入：原始JSON窗口参数。输出：已验证整数的typed input；非法参数在registry前拒绝。依赖：原SDK/typed input；成功：拒绝隐式类型转换，不改变合法数值。失败：SDK ModelBehaviorError显式失败，不降级/重试。验证：8非法组合及4合法窗口。演进：不变更context调查策略。

Removed/Moved/Reworded：无Prompt变化，Base没有该semantic context机械句。Added：两字段strict/ge=0、12 tests。Unchanged high-risk policy：生产Base与P16候选、discussion20/40、semantic routing、stop、negative、time逐字保持。

旧SDK将bool/string/float转为int，使原Host严格类型校验看到合法值。负整数原已被Host envelope拒绝，但Schema无minimum且SDK未先拒绝；不能把全部12个red说成非法输入均被接受。4合法case实际值已送达，只在缺失minimum断言失败。新Schema明确minimum=0；公开默认2/2、limit10、dense40和合法0/20/40仍保持，不增加单侧上限或改变原evaluation-only clamp。

12 red→12 green；static288 passed in2.86s、Ruff/mypy116通过。新Schema不同于V01，因此旧probe不能复用为同条件本轮验证。接受确定性契约修复，不证明模型选窗或Prompt语义等价；0新增API/tokens/cost，累计真实请求仍2、总token/费用未知。
