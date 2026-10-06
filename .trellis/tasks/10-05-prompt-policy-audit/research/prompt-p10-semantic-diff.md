# P10 semantic diff

Parent=P09；production SYSTEM_PROMPT原文不动。

- Removed：`limit must be a positive
integer within the schema bound, and `（62字符）。
- Moved：Base候选→recent原有字段description/动态Schema上界、SDK strict/ge=1、Capability trusted上界。
- Reworded：无；Added：仅recent.limit的strict/ge注解与中文职责注释、14项契约测试。
- Unchanged high-risk policy：recent-first选择、默认archive_latest两天、relative/absolute语义、时间互斥、cursor原样续传、stop/negative/discussion及其他正文逐字不变。

5失败/9通过的修改前复现：SDK转换bool/string/float，Host既有正整数及trusted上界测试通过。修复后非法原始值在registry前拒绝；default_limit仍由原scope推导；1/当前上限/省略参数保持，Host仍拒绝超上界且真实retrieval零调用。未把Schema maximum当执行验证，也不更改默认时间。

static=190 passed in1.84s；Ruff/mypy116通过。Provider=0，input/output/total tokens=0，cost=0。累计候选19,963字符。接受contract/L0候选，不证明真实语义等价或发布production。
