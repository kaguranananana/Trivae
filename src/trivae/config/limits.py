"""Trivae 各层共用的有界结果默认值。"""

# 默认值需要同时被 trusted scope、Capability、Retrieval 和 Provider schema 使用。
# 保留有界读取，避免把全库消息一次性送入模型；100 足以覆盖常见的资源检索清单。
DEFAULT_RESULT_LIMIT = 100
