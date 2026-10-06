# P08 semantic diff

Parent=P07；production原文不改。

- Removed：`never send empty arrays. `（25字符），仅lexical/legacy参数段。
- Moved：Base候选→三个optional filter的Schema minItems=1、原工具description和typed input非空数组校验。
- Reworded：无；Added：session_ids/sender_user_ids/message_types的Field(min_length=1)、中文注释、29项真实SDK/typed input测试。
- Unchanged high-risk policy：filter如何选/ canonical user_id / trusted scope、时间字段、lexical routing、discussion、negative、stop与所有正文其他字节顺序不动。

8项SDK/Schema红灯、21项既有合法输入/Host检查通过；补齐后空数组在SDK阶段拒绝，省略/null/正常数组仍传原typed参数。原Host已经拒绝空数组，本轮不新增授权层，也不变更filter交集/范围规则。未新增数组项格式正则、maxItems或新的检索策略。

首次编辑脚本误找不含继承声明的class分隔符，未写入源码；实际继承签名定位后修复，保持原失败断言。static=170 passed in1.87s、Ruff/mypy116通过。Provider=0；候选20,054字符，仅接受L0。
