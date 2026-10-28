"""Fixed execution conditions for eval@v1."""
from __future__ import annotations

from collections.abc import Mapping

from trivae.config.settings import ModelSettings
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter

from .contracts import EvaluationContractError
from .variant import ControlledVariant

FORMAL_TOOLS = (
    "lexical_search", "semantic_search", "get_recent_messages", "get_message_context",
    "find_members", "get_schema", "execute_sql",
)
FORMAL_RUNTIME = {
    "max_turns": 8, "max_tool_rounds": 6, "max_output_tokens": 16384, "completion_max_tokens": 2048,
    "tool_result_budget_mode": "dynamic", "model_context_window_tokens": 128000,
    "per_call_tool_result_percent": 50, "per_call_tool_result_cap": 128000,
    "run_tool_evidence_percent": 25, "run_tool_evidence_cap": 256000, "run_tool_evidence_budget": 32000,
}


def effective_model_treatment(settings: ModelSettings) -> dict[str, object]:
    """Capture provider-specific request differences that settings alone do not show."""
    adapter = OpenAIAgentsRuntimeAdapter(model=object(), settings=settings)
    subscription = settings.provider == "chatgpt-plan"
    agent_effort = settings.chatgpt_reasoning_effort if subscription else adapter._resolved_reasoning_effort()
    planner_effort = settings.chatgpt_reasoning_effort if subscription else adapter._planner_reasoning_effort()
    return {"agent_reasoning_effort": agent_effort, "planner_reasoning_effort": planner_effort,
            "tool_transport": "namespace" if subscription else "direct",
            "agent_max_tokens_sent": not subscription}


def validate_formal_conditions(variant: ControlledVariant, runtime: Mapping[str, object],
                               router: Mapping[str, object], *, allow_prompt_variant: bool = False) -> None:
    """Reject drift; only model/provider and an explicitly allowed prompt may vary."""
    mismatches = [name for name, expected in FORMAL_RUNTIME.items() if runtime.get(name) != expected]
    if mismatches:
        raise EvaluationContractError("eval v1 runtime conditions differ: " + ", ".join(mismatches))
    if router.get("enabled") is not False:
        raise EvaluationContractError("eval v1 requires the Jev router to be disabled")
    if variant.available_tools != FORMAL_TOOLS:
        raise EvaluationContractError("eval v1 tool surface differs")
    if ((variant.prompt_identity != "production-default" and not allow_prompt_variant)
            or variant.evidence_citation_version != "production-default"
            or variant.runtime_configuration != {"trace_profile": "normal"}
            or variant.retrieval_configuration != {"surface": "agent-facing"}
            or variant.context_expansion_configuration != {"context_window_limit": None}
            or variant.model_parameters or variant.budget != FORMAL_RUNTIME
            or variant.execution_override.forced_route is not None
            or variant.execution_override.context_window_limit is not None):
        raise EvaluationContractError("eval v1 variant conditions differ")
