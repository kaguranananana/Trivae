# 小型 Prompt fixture

`discussion.json` 是人工编写的41条消息，不包含真实聊天数据。M1提问，M12推荐，M13评价，M33补充；M35精确书名，M36/M39资源URL，M38次日补充。七个case的GT直接列在同一文件。

实际SDK投影结果：after=8没有M12；after=20有M12/M13、没有M33；after=40有全部三条。推荐者A、评价者B、补充者C独立。测试经过正式importer、canonical、lexical、context、SDK projection和Application Finalizer。

这些测试证明窗口和证据边界，也能拒绝有消息时的no_result形状；不会证明真实模型会主动选择足够窗口。普通合法claims中强负面结论的语义仍须人工/真实GT审查，Finalizer不能替代它。只有0 API的ScriptedModel，没有隐藏思维或真实Provider。
