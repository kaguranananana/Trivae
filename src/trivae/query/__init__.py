"""Query application contracts and orchestration entrypoints."""

from trivae.query.contracts import QueryContext, QueryDiagnostic, QueryRequest, QueryResult
from trivae.query.evidence import (
    AnswerArtifact,
    AnswerContentBlock,
    AnswerContractError,
    AnswerFinalizationError,
    CitationBinding,
    EvidenceItem,
    EvidenceSource,
    FinalizationErrorInfo,
    MessageDisplaySnapshot,
    MessageSource,
    StructuredSource,
    ToolResultRecord,
    finalize_answer,
)
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import Plan, PlannerFailure, PlannerInput, PlannerResult, PlanStep, SoftPlanner
from trivae.query.router import RouteDecision, RuleRouter
from trivae.query.runtime.contracts import ModelContextMessage

__all__ = [
    "AnswerArtifact",
    "AnswerContentBlock",
    "AnswerContractError",
    "AnswerFinalizationError",
    "CitationBinding",
    "EvidenceItem",
    "EvidenceSource",
    "FinalizationErrorInfo",
    "MessageDisplaySnapshot",
    "MessageSource",
    "Plan",
    "PlanStep",
    "PlannerFailure",
    "PlannerInput",
    "PlannerResult",
    "QueryContext",
    "QueryDiagnostic",
    "QueryOrchestrator",
    "QueryRequest",
    "QueryResult",
    "RouteDecision",
    "RuleRouter",
    "SoftPlanner",
    "StructuredSource",
    "ToolResultRecord",
    "finalize_answer",
    "ModelContextMessage",
]
