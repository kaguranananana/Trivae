# H08：probe choice与usage共同归当前run

Iteration ID：H08。Scope：首工具实验观测生命周期。Risk：低。Prompt lines：0。Owner：ScreeningRuntime._build_agent。Expected/Maximum Provider calls：0/0。

输入：复用同一实验Runtime的两次正式Application.query。输出：当前run的probe_calls/probe_usage。依赖：原Application/Runner/SDK；成功：第二run只含第二工具与usage，第一artifact快照不变。失败：保留真实截停，不执行Host；不重试。验证：同Application顺序两次query。演进：实验CLI仍顺序执行，不扩展并行run支持。

原usage已在builder清空，而choice只在CLI清空；直接通过Application复用Runtime时，第二choice出现上一get_schema和本次find_members。1 red明确复现。让两种观测在新run构造入口统一重置，删除CLI重复清理；正式Runtime不增加实验分支，不新建Agent。

Removed/Reworded：无Prompt文字。Moved：实验choice清理责任CLI→实验Runtime builder，非Base迁移。Added：一个两query真实SDK regression。Unchanged high-risk：生产Base/P16候选/所有业务策略原样。

static306 passed in2.70s，重置入口位置调整后15项screening tests及Ruff通过。两run IDs不同；110/220 usage各原值、choice只含本次工具，模型共2轮，Host0。接受观测修复，0新增Provider/tokens/cost；累计真实仍V01的2，总token/费用未知。
