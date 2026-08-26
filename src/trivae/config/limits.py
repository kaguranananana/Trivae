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
DEFAULT_MEMBER_RESULT_LIMIT = 20
MAX_MEMBER_RESULT_LIMIT = MAX_STRUCTURED_RESULT_ITEMS

# 自动 context 只允许有限数量的 direct hit 读取邻居，避免 broad query 的 N+1 放大。
MAX_AUTOMATIC_CONTEXT_SOURCE_HITS = 20

# Tool Result 的模型投影有独立 token 预算，不等同于任何 Retrieval candidate 数量上限。
# 16k 对 32k/64k/128k context 分别约占 50%/25%/12.5%，当前 Runtime 尚无可靠动态 context registry。
DEFAULT_TOOL_RESULT_TOKEN_BUDGET = 16_000

# 动态 Tool Result 预算只在收到显式 context window 时启用；百分比和绝对上限不影响 Retrieval budget。
DEFAULT_MAX_TOOL_RESULT_PERCENT = 50
DEFAULT_MAX_TOOL_RESULT_TOKENS = 128_000
