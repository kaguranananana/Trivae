"""订阅 Provider 配置、登录状态和独立 Evaluation 工具边界回归测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_evaluation import _case, _snapshot, _trace, _variant
from trivae.bootstrap.status import ProviderReadiness
from trivae.config.model_capabilities import resolve_context_window, resolve_reasoning_effort
from trivae.config.settings import (
    CHATGPT_PLAN_BASE_URL,
    SettingsError,
    load_router_jev_settings,
    load_settings,
)
from trivae.evaluation.benchmark.judge import LLMClaimJudge
from trivae.evaluation.checks import operational_measurements, query_result_snapshot
from trivae.evaluation.contracts import EvaluationContractError
from trivae.evaluation.retrieval_annotation import LLMRetrievalAnnotator
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.observability.contracts import TraceTimelineItem
from trivae.query.completion import CompletionProviderError
from trivae.query.contracts import QueryResult
from trivae.query.router import RouteDecision
from trivae.query.runtime.budget import ToolResultBudgetConfig
from trivae.query.runtime.contracts import RuntimeErrorInfo, RuntimeResult


def _settings_env() -> dict[str, str]:
    """使用目录返回的测试 slug；它不代表任何真实可用模型或能力。"""

    return {"TRIVAE_MODEL_PROVIDER": "chatgpt-plan", "TRIVAE_MODEL_NAME": "catalog-slug-fixture"}


class ChatGPTSettingsTests(unittest.TestCase):
    """只测试有实际跨 Provider 混用风险的配置边界。"""

    def test_old_key_and_endpoint_do_not_enter_subscription_settings(self) -> None:
        # 复现用户直接在现有 DeepSeek .env 上切换 Provider 的真实操作方式。
        settings = load_settings({
            **_settings_env(),
            "TRIVAE_MODEL_API_KEY": "old-api-key",
            "TRIVAE_MODEL_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_API_KEY": "legacy-api-key",
            "DEEPSEEK_BASE_URL": "https://legacy.example",
        })
        self.assertEqual(settings.api_key, "")
        self.assertEqual(settings.base_url, CHATGPT_PLAN_BASE_URL)
        self.assertNotIn("old-api-key", repr(settings))
        self.assertNotIn("legacy-api-key", str(settings.to_safe_dict()))
        self.assertFalse(settings.to_safe_dict()["api_key_configured"])
        self.assertEqual(settings.to_safe_dict()["auth_mode"], "chatgpt_oauth")
        self.assertEqual(settings.to_safe_dict()["protocol"], "responses")
        self.assertFalse(settings.to_safe_dict()["server_max_tokens_allowed"])

    def test_direct_settings_cannot_redirect_oauth_or_consume_api_key(self) -> None:
        settings = load_settings(_settings_env())
        with self.assertRaisesRegex(SettingsError, "official base URL"):
            replace(settings, base_url="https://third-party.example/v1")
        with self.assertRaisesRegex(SettingsError, "must not contain an API key"):
            replace(settings, api_key="api-key")

    def test_model_slug_is_explicit_and_capabilities_remain_unknown(self) -> None:
        with self.assertRaisesRegex(SettingsError, "auth models"):
            load_settings({"TRIVAE_MODEL_PROVIDER": "chatgpt-plan"})
        settings = load_settings(_settings_env())
        resolution = resolve_context_window(
            explicit_context_window_tokens=settings.model_context_window_tokens,
            provider=settings.provider, model_name=settings.model_name,
        )
        self.assertIsNone(resolution.context_window_tokens)
        self.assertEqual(resolution.source, "fallback")
        self.assertIsNone(resolve_reasoning_effort(provider=settings.provider, model_name=settings.model_name))
        # 未知 context 沿用已有 dynamic shared pool，不伪造 GPT context 大小。
        budget = ToolResultBudgetConfig(
            context_window_tokens=resolution.context_window_tokens, context_window_source=resolution.source,
        )
        self.assertEqual(budget.budget_resolution, "dynamic_fallback")
        self.assertEqual(budget.run_tool_evidence_budget, 16_000)

    def test_jev_is_independent_of_primary_subscription_provider(self) -> None:
        values = {**_settings_env(), "OPENROUTER_API_KEY": "jev-key"}
        settings = load_settings(values)
        jev = load_router_jev_settings(values)
        self.assertEqual(settings.api_key, "")
        self.assertEqual(jev.api_key, "jev-key")
        self.assertTrue(jev.enabled)
        self.assertEqual(jev.mode, "shadow")

    def test_old_provider_projections_keep_their_contract(self) -> None:
        for provider in ("deepseek", "opencode-go"):
            with self.subTest(provider=provider):
                settings = load_settings({
                    "TRIVAE_MODEL_PROVIDER": provider, "TRIVAE_MODEL_NAME": "test-model",
                    "TRIVAE_MODEL_API_KEY": "key", "TRIVAE_MODEL_BASE_URL": "https://api.example/v1",
                })
                self.assertEqual(settings.api_key, "key")
                self.assertNotIn("auth_mode", settings.to_safe_dict())
                self.assertEqual(ProviderReadiness.from_settings(settings).status, "ready")

    def test_readiness_requires_login_and_plan_scopes(self) -> None:
        settings = load_settings(_settings_env())
        for authenticated, plan_enabled, expected_code in (
            (False, False, "CHATGPT_LOGIN_REQUIRED"),
            (True, False, "CHATGPT_PLAN_SCOPE_REQUIRED"),
            (True, True, None),
        ):
            with self.subTest(authenticated=authenticated, plan_enabled=plan_enabled):
                with patch("trivae.auth.ChatGPTAuthStore") as store:
                    store.return_value.status.return_value = {
                        "authenticated": authenticated, "plan_usage_enabled": plan_enabled,
                    }
                    readiness = ProviderReadiness.from_settings(settings)
                self.assertEqual(readiness.status, "ready" if expected_code is None else "not_configured")
                self.assertEqual(readiness.error_code, expected_code)
                self.assertEqual(readiness.provider, "chatgpt-plan")
                self.assertEqual(readiness.to_dict()["protocol"], "responses")

    def test_independent_chat_completions_tools_reject_subscription_provider(self) -> None:
        settings = load_settings(_settings_env())
        for tool in (LLMClaimJudge, LLMRetrievalAnnotator):
            with self.subTest(tool=tool.__name__):
                with self.assertRaisesRegex(EvaluationContractError, "does not support chatgpt-plan"):
                    tool(settings)

    def test_readiness_exposes_unreadable_credentials(self) -> None:
        # 本机存储失败应成为明确 readiness 原因，不把无效会话误报为 ready。
        with patch("trivae.auth.ChatGPTAuthStore") as store:
            store.return_value.status.side_effect = PermissionError("credential file permission denied")
            readiness = ProviderReadiness.from_settings(load_settings(_settings_env()))
        self.assertEqual(readiness.status, "not_configured")
        self.assertEqual(readiness.error_code, "PermissionError")
        self.assertIn("credential file permission denied", readiness.message)

    def test_evaluation_records_actual_safe_configuration_from_same_trace(self) -> None:
        settings = load_settings(_settings_env())
        configuration = settings.to_safe_dict()
        item = TraceTimelineItem(
            sequence=1, stage="runtime", operation="runtime.configuration", phase="completed",
            operation_id="runtime-config", parent_operation_id=None, outcome="ok",
            duration_ms=None, limitations=(), payload=configuration,
        )
        trace = replace(_trace(), timeline=(item,))
        measurements = operational_measurements(None, trace)
        self.assertEqual(measurements["model_configuration"], configuration)
        # 历史 Trace 没有配置事件时不捏造当前设置，也不改变 frozen Variant。
        self.assertNotIn("model_configuration", operational_measurements(None, _trace()))

    def test_evaluation_keeps_provider_failure_reason_and_actual_identity(self) -> None:
        result = QueryResult(
            runtime_result=RuntimeResult(
                final_answer=None, provider="chatgpt-plan", model="catalog-slug-fixture",
                termination="failed", tool_calls=(),
                error=RuntimeErrorInfo(code="CHATGPT_PLAN_LIMIT", message="plan quota exhausted; request id req-fixture"),
            ),
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
        )
        snapshot = query_result_snapshot(result)
        self.assertEqual(snapshot["runtime"]["provider"], "chatgpt-plan")
        self.assertEqual(snapshot["runtime"]["model"], "catalog-slug-fixture")
        self.assertIn("plan quota exhausted", snapshot["runtime"]["error"]["message"])

    def test_evaluation_preserves_safe_completion_failure_before_runtime(self) -> None:
        payload = {
            "provider": "chatgpt-plan", "model": "catalog-slug-fixture", "error_code": "quota_exceeded",
            "error_message": "quota_exceeded: application quota reached",
            "completion_request": {"stream": True, "store": False},
            "provider_observation": {"error_code": "quota_exceeded", "request_id": "req-quota", "status_code": 429},
        }
        item = TraceTimelineItem(
            sequence=2, stage="query", operation="query.failed", phase="failed",
            operation_id="query", parent_operation_id=None, outcome="error",
            duration_ms=None, limitations=(), payload=payload,
        )
        trace = replace(_trace(), timeline=(item,))
        measurements = operational_measurements(None, trace)
        for name, value in payload.items():
            self.assertEqual(measurements[name], value)
        self.assertIsNone(measurements["usage"])

        async def query(_request):
            # 注入的分类错误已符合安全异常契约，Runner 必须落盘后仍向 caller 抛出。
            error = CompletionProviderError(payload["error_message"], stops_inference=True)
            error.trace_id = trace.trace_id
            raise error

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEvaluationStore(Path(directory) / "evaluation.sqlite3")
            runner = EvaluationRunner(
                query_executor=query, trace_reader=lambda _trace_id: trace,
                store=store, snapshot_resolver=_snapshot,
            )
            with self.assertRaises(CompletionProviderError):
                asyncio.run(runner.run_case(_case(), _variant()))
            run = store.list_runs()[0]
            store.close()
        self.assertEqual(run.exception_message, payload["error_message"])
        self.assertEqual(run.operational_measurements["provider"], "chatgpt-plan")
        self.assertEqual(run.operational_measurements["model"], "catalog-slug-fixture")

    def test_evaluation_does_not_copy_unknown_callback_exception_body(self) -> None:
        async def query(_request):
            raise RuntimeError("unknown callback contains credential fixture")

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEvaluationStore(Path(directory) / "evaluation.sqlite3")
            runner = EvaluationRunner(
                query_executor=query, trace_reader=lambda _trace_id: _trace(),
                store=store, snapshot_resolver=_snapshot,
            )
            with self.assertRaises(RuntimeError):
                asyncio.run(runner.run_case(_case(), _variant()))
            run = store.list_runs()[0]
            store.close()
        self.assertNotIn("credential fixture", run.exception_message)
        self.assertIsNone(run.operational_measurements["provider"])


@pytest.mark.parametrize("effort", ["medium", "high"])
def test_effort_is_explicit_and_rejects_unverified_provider_model_combinations(effort):
    """精确身份允许已验证档位，未知组合仍显式拒绝，不悄悄改档。"""
    import pytest

    values = {"TRIVAE_MODEL_PROVIDER": "chatgpt-plan", "TRIVAE_MODEL_NAME": "gpt-6.1-sol",
              "TRIVAE_CHATGPT_REASONING_EFFORT": effort}
    settings = load_settings(values)
    assert settings.chatgpt_reasoning_effort == effort
    assert settings.to_safe_dict()["reasoning_effort"] == effort
    for override in ({"TRIVAE_MODEL_NAME": "unknown"}, {"TRIVAE_CHATGPT_REASONING_EFFORT": "low"},
                     {"TRIVAE_MODEL_PROVIDER": "deepseek", "TRIVAE_MODEL_API_KEY": "test",
                      "TRIVAE_MODEL_BASE_URL": "https://api.deepseek.com"}):
        with pytest.raises(SettingsError, match="reasoning effort"):
            load_settings({**values, **override})
    with pytest.raises(SettingsError, match="reasoning effort"):
        replace(settings, model_name="unknown")
