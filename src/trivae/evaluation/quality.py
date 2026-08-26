"""真实回答质量 Review 使用的共享维度与 Failure Label。"""

# 质量轴拆开 retrieval/evidence/claim/readability，避免压成一个没有归因能力的总分。
QUALITY_AXES = (
    "retrieval_recall",
    "evidence_coverage",
    "citation_validity",
    "claim_evidence_entailment",
    "enumeration_completeness",
    "overclaim_unsupported_inference",
    "user_facing_readability",
)

# 这些标签只作为人工/辅助 Judge 的显式词表，不根据单个 query 关键词自动猜测。
FAILURE_LABELS = (
    "MENTION_TO_RECOMMENDATION",
    "INTENT_TO_ACTUAL_USE",
    "REVIEW_TO_PERSONAL_USAGE",
    "HIT_COUNT_TO_UNIQUE_ENTITY_COUNT",
    "PARTIAL_TO_NEGATIVE_ASSERTION",
    "MISSING_EXPLICIT_RESOURCE",
    "ENUMERATION_INCOMPLETE",
)
