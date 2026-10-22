"""实验首轮总额与后续额度的真实SDK回归，不调用网络。"""

from __future__ import annotations

import asyncio

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from scripts.run_first_round_budget_experiment import first_round_limit
from tests.test_tool_result_budget import _dynamic_settings, _message
from trivae.capabilities import CapabilityRegistry, ExecutionScope, ToolEnvelope
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import Coverage, LexicalQuery, MessageHit, RetrievalMetadata, RetrievalResult


class LargeSearch:
    """每次返回可裁剪的真实消息结构，让首轮和补查竞争同一16k池。"""

    name = "search_messages"

    def invoke(self, request, scope):
        messages = tuple(_message(index, f"{request.keyword}证据" * 200) for index in range(40))
        data = RetrievalResult(
            query=LexicalQuery(keyword=request.keyword, limit=100, context_before=0, context_after=0),
            filters={}, strategy="lexical", hits=tuple(MessageHit(message, (), 1.0, "test") for message in messages),
            expanded_messages=(), total_hits=40, returned_messages=40,
            coverage=Coverage("complete", "canonical_plus_lexical_index"), partial=False, truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0),
        )
        return ToolEnvelope("ok", data, {}, None)


def test_first_round_is_shared_and_second_round_uses_retained_pool():
    """首轮两个调用合计不超8k，第二轮能使用余额；全run仍不超16k。"""
    registry = CapabilityRegistry()
    registry.register(LargeSearch())
    model = ScriptedModel([
        ModelStep(output=[function_call("search_messages", {"keyword": word}, call_id=f"c{index}")
                          for index, word in enumerate(("first", "second"))]),
        ModelStep(output=[function_call("search_messages", {"keyword": "followup"}, call_id="c2")]),
        ModelStep(output=[assistant_message('{"claims":[],"limitations":[]}')]),
    ])
    runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, settings=_dynamic_settings())
    request = AgentRunRequest("读取材料后补查", ExecutionScope(max_results=100),
                              available_capabilities=("search_messages",))
    with first_round_limit(8_000):
        result = asyncio.run(runtime.run(request))
    assert result.termination == "completed"
    assert result.tool_rounds == 2
    assert len(result.tool_calls) == 3
    assert all(call.error_code is None for call in result.tool_calls)
    first, second, followup = result.tool_calls
    assert first.model_result_estimated_tokens + second.model_result_estimated_tokens <= 8_000
    assert first.tool_result_budget.effective_per_call_tool_result_budget == 4_000
    assert second.tool_result_budget.effective_per_call_tool_result_budget == 4_000
    # 第二轮仍先扣协议控制预留，实际数据额度应等于当时余额，不能假设严格大于8k。
    assert (followup.tool_result_budget.effective_per_call_tool_result_budget
            == followup.tool_result_budget.remaining_run_tool_evidence_budget_before_call)
    assert followup.tool_result_budget.effective_per_call_tool_result_budget > 4_000
    assert sum(call.model_result_estimated_tokens for call in result.tool_calls) <= 16_000
