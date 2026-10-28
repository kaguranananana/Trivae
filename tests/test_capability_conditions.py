"""Formal model experiments reject accidental changes to budgets or tools."""
from dataclasses import replace

import pytest

from tests.test_evaluation import _variant
from trivae.config.settings import CHATGPT_PLAN_BASE_URL, ModelSettings
from trivae.evaluation.capability_conditions import (
    FORMAL_RUNTIME,
    FORMAL_TOOLS,
    effective_model_treatment,
    validate_formal_conditions,
)
from trivae.evaluation.contracts import EvaluationContractError


def _formal_variant():
    return replace(_variant(), prompt_identity="production-default", evidence_citation_version="production-default",
                   available_tools=FORMAL_TOOLS, runtime_configuration={"trace_profile": "normal"},
                   retrieval_configuration={"surface": "agent-facing"},
                   context_expansion_configuration={"context_window_limit": None}, budget=FORMAL_RUNTIME)


def test_formal_conditions_fix_window_tool_budget_and_router():
    variant = _formal_variant()
    validate_formal_conditions(variant, FORMAL_RUNTIME, {"enabled": False})
    with pytest.raises(EvaluationContractError, match="model_context_window_tokens"):
        validate_formal_conditions(variant, {**FORMAL_RUNTIME, "model_context_window_tokens": None}, {"enabled": False})
    with pytest.raises(EvaluationContractError, match="tool surface"):
        validate_formal_conditions(replace(variant, available_tools=("lexical_search",)), FORMAL_RUNTIME, {"enabled": False})
    with pytest.raises(EvaluationContractError, match="router"):
        validate_formal_conditions(variant, FORMAL_RUNTIME, {"enabled": True})


def test_model_specific_tool_transport_and_reasoning_are_recorded():
    deepseek = ModelSettings(api_key="fixture", base_url="https://example.test", provider="deepseek",
                             model_name="deepseek-flash", max_turns=8, model_context_window_tokens=128000,
                             run_tool_evidence_budget=32000)
    treatment = effective_model_treatment(deepseek)
    assert treatment["agent_reasoning_effort"] == "low"
    assert treatment["planner_reasoning_effort"] == "none"
    assert treatment["tool_transport"] == "direct"
    subscription = replace(deepseek, api_key="", base_url=CHATGPT_PLAN_BASE_URL, provider="chatgpt-plan",
                           model_name="gpt-6.1-sol", chatgpt_reasoning_effort="medium")
    treatment = effective_model_treatment(subscription)
    assert treatment["agent_reasoning_effort"] == "medium"
    assert treatment["tool_transport"] == "namespace"
    assert treatment["agent_max_tokens_sent"] is False
