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
# 数值目前与 lexical 相同，但它们代表不同的配置责任，不能通过引用 lexical 常量耦合。
DEFAULT_TRUSTED_RESULT_LIMIT = 5_000
MAX_TRUSTED_RESULT_LIMIT = 5_000

# structured/member/SQL 维持小型结果边界，不与 lexical message candidate 共用容量。
DEFAULT_STRUCTURED_RESULT_LIMIT = 100
MAX_STRUCTURED_RESULT_ITEMS = 100

# get_recent_messages 是 broad temporal browsing，必须拥有独立的高 recall 容量。
# 这两个值故意不引用 structured 常量：相同的数值不代表相同的业务边界。
DEFAULT_RECENT_MESSAGES_LIMIT = 1_000
MAX_RECENT_MESSAGES_LIMIT = 5_000
# 无时间参数时 get_recent_messages({}) 等价于相对最近 N 天，锚定 archive_latest。
RECENT_MESSAGES_DEFAULT_AMOUNT = 2
DEFAULT_MEMBER_RESULT_LIMIT = 20
MAX_MEMBER_RESULT_LIMIT = MAX_STRUCTURED_RESULT_ITEMS

# 自动 context 只允许有限数量的 direct hit 读取邻居，避免 broad query 的 N+1 放大。
MAX_AUTOMATIC_CONTEXT_SOURCE_HITS = 20

# 显式原文读取按字符分页；它独立于引用卡片的1000字摘录，超长消息可继续读取。
MAX_MESSAGE_CONTENT_PAGE_CHARS = 8_000

# Tool Result 的模型投影有独立 token 预算，不等同于任何 Retrieval candidate 数量上限。
# 未知 context 时 per-call 和 run-level 都回到这个 16k 安全边界。
DEFAULT_TOOL_RESULT_TOKEN_BUDGET = 16_000

# canonical message provenance 必须能承载 message-producing retrieval 的最大批次；
# 这是 Tool Result record 的 item ceiling，不是 lexical、recent 或模型 token 上限。
MAX_TOOL_RESULT_MESSAGE_ITEMS = 5_000

# 单次 Tool Result 的 ceiling 与一次 Run 的累计 Evidence pool 分开配置。
DEFAULT_PER_CALL_TOOL_RESULT_PERCENT = 50
DEFAULT_PER_CALL_TOOL_RESULT_CAP = 128_000
DEFAULT_RUN_TOOL_EVIDENCE_PERCENT = 25
DEFAULT_RUN_TOOL_EVIDENCE_CAP = 256_000
