"""Trivae 各层独立的有界预算。"""

from typing import Literal

ToolResultBudgetMode = Literal["fixed", "dynamic"]

# lexical candidate 服务 inventory/broad recall；hard cap 仍阻止无界 FTS 读取。
DEFAULT_LEXICAL_RESULT_LIMIT = 1_000
MAX_LEXICAL_RESULT_LIMIT = 5_000

# semantic result 是最终 evidence 数量，不能因为 lexical recall 变大而同步放宽。
DEFAULT_SEMANTIC_RESULT_LIMIT = 10
MAX_SEMANTIC_RESULT_LIMIT = 20

# trusted scope 只提供跨工具的最大 umbrella；各 Capability 仍必须应用自己的 hard cap。
DEFAULT_TRUSTED_RESULT_LIMIT = MAX_LEXICAL_RESULT_LIMIT
MAX_TRUSTED_RESULT_LIMIT = MAX_LEXICAL_RESULT_LIMIT

# structured/member/SQL 维持小型结果边界，不与 lexical message candidate 共用容量。
DEFAULT_STRUCTURED_RESULT_LIMIT = 100
MAX_STRUCTURED_RESULT_ITEMS = 100

# get_recent_messages 是 broad temporal browsing；容量沿用 structured bound，
# 不复用 semantic 的 10/20 evidence 数量上限。
DEFAULT_RECENT_MESSAGES_LIMIT = DEFAULT_STRUCTURED_RESULT_LIMIT
MAX_RECENT_MESSAGES_LIMIT = MAX_STRUCTURED_RESULT_ITEMS
DEFAULT_MEMBER_RESULT_LIMIT = 20
MAX_MEMBER_RESULT_LIMIT = MAX_STRUCTURED_RESULT_ITEMS

# 自动 context 只允许有限数量的 direct hit 读取邻居，避免 broad query 的 N+1 放大。
MAX_AUTOMATIC_CONTEXT_SOURCE_HITS = 20

# Tool Result 的模型投影有独立 token 预算，不等同于任何 Retrieval candidate 数量上限。
# 未知 context 时 per-call 和 run-level 都回到这个 16k 安全边界。
DEFAULT_TOOL_RESULT_TOKEN_BUDGET = 16_000

# 单次 Tool Result 的 ceiling 与一次 Run 的累计 Evidence pool 分开配置。
DEFAULT_PER_CALL_TOOL_RESULT_PERCENT = 50
DEFAULT_PER_CALL_TOOL_RESULT_CAP = 128_000
DEFAULT_RUN_TOOL_EVIDENCE_PERCENT = 25
DEFAULT_RUN_TOOL_EVIDENCE_CAP = 256_000
