"""Trivae 各层共用的有界结果默认值。"""

# 默认值需要同时被 trusted scope、Capability、Retrieval 和 Provider schema 使用。
# 保留有界读取，避免把全库消息一次性送入模型；100 足以覆盖常见的资源检索清单。
DEFAULT_RESULT_LIMIT = 100

# Tool Result 的模型投影有独立 token 预算，不等同于 Retrieval 的结果数量上限。
# 100 条 bounded hit 的 slim projection 实测约需 15.6k estimate，因此保留 16k 余量；超出仍显式失败。
DEFAULT_TOOL_RESULT_TOKEN_BUDGET = 16_000
