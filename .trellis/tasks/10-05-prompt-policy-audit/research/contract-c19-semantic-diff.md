# C19 contract / semantic diff

- Removed/Moved/Reworded：无Prompt变化；Tool description不改。
- Added：Schema与函数共用default_limit、4项实际SDK省略值检查。
- Unchanged high-risk policy：semantic routing、dense40/context2/2、时间/filter/stop；显式参数仍原值，上界仍Host拒绝。

复现2 failed/2 passed：scope1/5的Schema default为1/5，SDK实际却传10。现在factory在注册函数前算同一default，函数与Schema共用；scope>=10仍10。这是落实已有公开默认值，不是夹取模型显式limit或生成fallback。typed request的省略值符合Schema；既有C18上界与显式1/10继续通过。

Static266 passed in2.47s；Ruff/mypy116通过；0API。改变只在原本违反已公开default的省略调用，正常大scope默认值不变。Base未声明此默认值，不删除Prompt，也不宣称semantic equivalence。
