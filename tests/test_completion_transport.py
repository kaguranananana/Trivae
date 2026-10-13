"""Provider 终态观测贯穿 Router/Planner；不将传输失败当作成功。"""

from __future__ import annotations

import asyncio
import json

from trivae.query.completion import CompletionObservation, CompletionProviderError, CompletionResult
from trivae.query.contracts import QueryContext
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import SoftPlanner
from trivae.query.router import RuleRouter


def _context() -> QueryContext:
    """选用规则不确定的请求，保证 Router 真正调用 completion。"""

    return QueryContext("查找架构讨论", "zh-CN", (), {}, ("lexical_search",))


def test_invalid_router_text_keeps_actual_usage_and_completed_transport() -> None:
    """JSON 失败不抹去真实调用的 Usage 与公开请求 ID。"""

    observation = CompletionObservation(
        provider="chatgpt-plan",
        model="account-model",
        usage={"input_tokens": 10, "output_tokens": 2},
        transport={"stream_completed": True, "request_id": "request-test"},
    )
    decision = asyncio.run(RuleRouter(completion=lambda _: CompletionResult("{invalid", observation)).route(_context()))
    assert decision.degraded and decision.degradation_code == "ROUTER_COMPLETION_INVALID"
    assert decision.usage == observation.usage
    assert decision.provider_transport == observation.transport


def test_classified_provider_failure_keeps_safe_diagnostics_in_both_stages() -> None:
    """额度错误保持同一 Provider，不改变既有 Router/Planner 的规则恢复行为。"""

    observation = CompletionObservation(
        provider="chatgpt-plan",
        model="account-model",
        transport={
            "status_code": 429,
            "request_id": "quota-request",
            "error_code": "subscription_sharing_usage_limit_exceeded",
            "stream_completed": False,
        },
    )

    def fail(_prompt: str) -> CompletionResult:
        """模拟边界已脱敏的真实错误，不提供凭证。"""

        raise CompletionProviderError("subscription_sharing_usage_limit_exceeded", observation)

    decision = asyncio.run(RuleRouter(completion=fail).route(_context()))
    result = asyncio.run(SoftPlanner(fail).plan(_context()))
    assert decision.degraded and decision.provider == "chatgpt-plan"
    assert decision.provider_transport == observation.transport
    assert result.plan is None and result.failure is not None
    assert "subscription_sharing_usage_limit_exceeded" in result.failure.message
    payload = QueryOrchestrator._planner_observation_payload(result, None)
    assert payload["provider_observation"] == observation.transport


def test_unknown_callback_error_does_not_copy_secret_text() -> None:
    """未知回调没有安全观测契约，秘密正文不能进入业务投影。"""

    def fail(_prompt: str) -> CompletionResult:
        """模拟第三方 callback 抛出含敏感正文的异常。"""

        raise RuntimeError("untrusted-secret-value")

    decision = asyncio.run(RuleRouter(completion=fail).route(_context()))
    result = asyncio.run(SoftPlanner(fail).plan(_context()))
    assert "untrusted-secret-value" not in repr(decision)
    assert "untrusted-secret-value" not in repr(result)


def test_successful_planner_keeps_completed_response_transport() -> None:
    """Plan 解析成功时 Trace 仍保留 Responses 成功终态和 Usage。"""

    raw = json.dumps({
        "version": 1, "title": "查找来源", "intent": "evidence",
        "steps": [{"goal": "取回消息", "suggested_tools": ["lexical_search"], "evidence_needed": ["原始消息"]}],
        "success_criteria": ["结论有来源"],
    })
    observation = CompletionObservation(
        provider="chatgpt-plan", model="account-model",
        usage={"input_tokens": 20, "output_tokens": 8},
        transport={"stream_completed": True, "response_id": "response-test"},
    )
    result = asyncio.run(SoftPlanner(lambda _: CompletionResult(raw, observation)).plan(_context()))
    assert result.plan is not None and result.failure is None
    payload = QueryOrchestrator._planner_observation_payload(result, None)
    assert payload["usage"] == observation.usage
    assert payload["provider_observation"] == observation.transport
