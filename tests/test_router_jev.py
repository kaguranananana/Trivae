from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

from trivae.config.settings import SettingsError, load_router_jev_settings
from trivae.evaluation.router_jev import (
    RouterEvaluationError,
    load_router_evaluation_cases,
    run_paired_router_evaluation,
    write_router_evaluation_report,
)
from trivae.interfaces.cli import build_parser
from trivae.query.completion import CompletionObservation, CompletionResult
from trivae.query.contracts import QueryContext
from trivae.query.jev_provider import JevRouteDecisionProvider
from trivae.query.router import (
    RouterDecisionProviderError,
    RouterProviderResult,
    RuleRouter,
)


def _context(
    query: str = "请总结 alpha 的讨论",
    *,
    prior_context: tuple[Any, ...] = (),
    data_snapshot: dict[str, object] | None = None,
) -> QueryContext:
    """创建一份 Router 可见 context，测试不连接聊天数据或外部服务。"""

    return QueryContext(
        query,
        "zh-CN",
        prior_context,
        {} if data_snapshot is None else data_snapshot,
        ("search_messages",),
    )


class _DecisionClient:
    """记录 Decisions 请求形状并返回测试给定的普通 JSON projection。"""

    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def post(self, path: str, *, cast_to: object, body: dict[str, object]) -> object:
        self.calls.append((path, body))
        return self.response


class _DecisionProvider:
    """为 Router behavior tests 提供成功或显式失败的 typed result。"""

    def __init__(self, result: RouterProviderResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def decide(self, context: QueryContext) -> RouterProviderResult:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class RouterJevSettingsTests(unittest.TestCase):
    def test_defaults_are_router_specific_and_do_not_require_an_api_key(self) -> None:
        values = {
            "TRIVIAE_MODEL_PROVIDER": "deepseek",
            "TRIVIAE_MODEL_NAME": "primary-model",
            "TRIVIAE_MODEL_BASE_URL": "https://primary.example/v1",
        }

        settings = load_router_jev_settings(values)

        self.assertTrue(settings.enabled)
        self.assertEqual(settings.model, "typesafe/jev-1.13")
        self.assertEqual(settings.endpoint, "https://openrouter.ai/api/alpha/decisions")
        self.assertEqual(settings.mode, "shadow")
        self.assertEqual(settings.api_key, "")
        self.assertEqual(values["TRIVIAE_MODEL_PROVIDER"], "deepseek")
        self.assertNotIn("OPENROUTER_API_KEY", values)

    def test_only_supported_modes_and_decisions_endpoint_are_accepted(self) -> None:
        with self.assertRaises(SettingsError):
            load_router_jev_settings({"TRIVIAE_ROUTER_JEV_MODE": "silent"})
        with self.assertRaises(SettingsError):
            load_router_jev_settings({"TRIVIAE_ROUTER_JEV_ENDPOINT": "https://openrouter.ai/api/v1"})

    def test_config_repr_and_safe_projection_never_include_key_value(self) -> None:
        settings = load_router_jev_settings({"OPENROUTER_API_KEY": "configured-test-value"})
        self.assertNotIn("configured-test-value", repr(settings))
        self.assertNotIn("configured-test-value", str(settings.to_safe_dict()))
        self.assertTrue(settings.to_safe_dict()["api_key_configured"])


class JevDecisionProviderTests(unittest.TestCase):
    def test_sends_router_projection_and_keeps_confidence_distinct_from_probability(self) -> None:
        client = _DecisionClient(
            {
                "model": "typesafe/jev-1.13-20260917",
                "answers": {
                    "route": {
                        "type": "choice",
                        "choice": "planned_execution",
                        "probabilities": {
                            "standard_execution": 0.61,
                            "planned_execution": 0.39,
                        },
                        "confidence": 0.73,
                    }
                },
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 4,
                    "cost": 0.00012,
                    "provider_metadata": "discarded",
                },
            }
        )
        settings = load_router_jev_settings({"OPENROUTER_API_KEY": "configured-test-value"})
        provider = JevRouteDecisionProvider(settings, client=client)
        context = _context(data_snapshot={"session_count": 2})

        result = asyncio.run(provider.decide(context))

        self.assertEqual(len(client.calls), 1)
        path, request = client.calls[0]
        self.assertEqual(path, "/alpha/decisions")
        self.assertEqual(request["model"], "typesafe/jev-1.13")
        state = request["state"]
        self.assertEqual(state["query"], context.query)
        self.assertEqual(state["locale"], "zh-CN")
        self.assertEqual(state["data_snapshot"], {"session_count": 2})
        self.assertNotIn("available_capabilities", state)
        self.assertEqual(result.route, "planned_execution")
        self.assertEqual(result.confidence, 0.73)
        self.assertEqual(result.probabilities["planned_execution"], 0.39)
        self.assertEqual(result.usage, {"input_tokens": 21, "output_tokens": 4, "cost": 0.00012})
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.model, "typesafe/jev-1.13-20260917")

    def test_missing_key_fails_before_request_and_invalid_choice_is_explicit(self) -> None:
        missing_key_client = _DecisionClient({})
        missing_key_provider = JevRouteDecisionProvider(
            load_router_jev_settings({}), client=missing_key_client
        )
        with self.assertRaises(RouterDecisionProviderError) as missing_key:
            asyncio.run(missing_key_provider.decide(_context()))
        self.assertEqual(missing_key.exception.code, "JEV_ROUTER_API_KEY_MISSING")
        self.assertEqual(missing_key_client.calls, [])

        invalid_client = _DecisionClient(
            {
                "answers": {
                    "route": {
                        "type": "choice",
                        "choice": "other",
                        "probabilities": {
                            "standard_execution": 0.5,
                            "planned_execution": 0.5,
                        },
                        "confidence": 0.5,
                    }
                }
            }
        )
        invalid_provider = JevRouteDecisionProvider(
            load_router_jev_settings({"OPENROUTER_API_KEY": "configured-test-value"}),
            client=invalid_client,
        )
        with self.assertRaises(RouterDecisionProviderError) as invalid:
            asyncio.run(invalid_provider.decide(_context()))
        self.assertEqual(invalid.exception.code, "JEV_ROUTER_INVALID_RESPONSE")

    def test_openai_sdk_posts_to_configured_decisions_endpoint(self) -> None:
        requests: list[httpx.Request] = []
        response_payload = {
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "standard_execution",
                    "probabilities": {
                        "standard_execution": 0.8,
                        "planned_execution": 0.2,
                    },
                    "confidence": 0.84,
                }
            }
        }

        def handle_request(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=response_payload, request=request)

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
        sdk_client = AsyncOpenAI(
            api_key="x-test-only",
            base_url="https://openrouter.ai/api",
            http_client=http_client,
            max_retries=0,
        )
        provider = JevRouteDecisionProvider(
            load_router_jev_settings({"OPENROUTER_API_KEY": "x-test-only"}),
            client=sdk_client,
        )

        async def run() -> RouterProviderResult:
            try:
                return await provider.decide(_context())
            finally:
                await provider.aclose()
                await http_client.aclose()

        result = asyncio.run(run())
        self.assertEqual(result.route, "standard_execution")
        self.assertEqual(len(requests), 1)
        self.assertEqual(str(requests[0].url), "https://openrouter.ai/api/alpha/decisions")
        posted_body = json.loads(requests[0].content)
        self.assertEqual(posted_body["model"], "typesafe/jev-1.13")

    def test_openrouter_statuses_map_to_diagnostic_failure_codes(self) -> None:
        expected_codes = {
            401: "JEV_ROUTER_AUTH_ERROR",
            403: "JEV_ROUTER_AUTH_ERROR",
            404: "JEV_ROUTER_MODEL_UNAVAILABLE",
            429: "JEV_ROUTER_RATE_LIMITED",
            502: "JEV_ROUTER_PROVIDER_UNAVAILABLE",
            503: "JEV_ROUTER_PROVIDER_UNAVAILABLE",
        }

        for status_code, expected_code in expected_codes.items():
            with self.subTest(status_code=status_code):
                def handle_request(request: httpx.Request) -> httpx.Response:
                    return httpx.Response(
                        status_code,
                        json={"error": {"message": "test-only response"}},
                        request=request,
                    )

                http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
                sdk_client = AsyncOpenAI(
                    api_key="x-test-only",
                    base_url="https://openrouter.ai/api",
                    http_client=http_client,
                    max_retries=0,
                )
                provider = JevRouteDecisionProvider(
                    load_router_jev_settings({"OPENROUTER_API_KEY": "x-test-only"}),
                    client=sdk_client,
                )

                async def run() -> None:
                    try:
                        await provider.decide(_context())
                    finally:
                        await provider.aclose()
                        await http_client.aclose()

                with self.assertRaises(RouterDecisionProviderError) as failure:
                    asyncio.run(run())
                self.assertEqual(failure.exception.code, expected_code)

    def test_timeout_and_network_errors_keep_safe_type_diagnostics(self) -> None:
        cases = (
            (httpx.ReadTimeout("test-only timeout"), "JEV_ROUTER_TIMEOUT"),
            (httpx.ConnectError("test-only connection failure"), "JEV_ROUTER_NETWORK_ERROR"),
        )

        for transport_error, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                def handle_request(request: httpx.Request) -> httpx.Response:
                    raise transport_error

                http_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_request))
                sdk_client = AsyncOpenAI(
                    api_key="x-test-only",
                    base_url="https://openrouter.ai/api",
                    http_client=http_client,
                    max_retries=0,
                )
                provider = JevRouteDecisionProvider(
                    load_router_jev_settings({"OPENROUTER_API_KEY": "x-test-only"}),
                    client=sdk_client,
                )

                async def run() -> None:
                    try:
                        await provider.decide(_context())
                    finally:
                        await provider.aclose()
                        await http_client.aclose()

                with self.assertRaises(RouterDecisionProviderError) as failure:
                    asyncio.run(run())
                self.assertEqual(failure.exception.code, expected_code)


class RouterJevModeTests(unittest.TestCase):
    def test_high_confidence_rule_never_calls_optional_providers(self) -> None:
        provider = _DecisionProvider(
            RouterProviderResult("planned_execution", 0.8, {
                "standard_execution": 0.2,
                "planned_execution": 0.8,
            })
        )

        decision = asyncio.run(
            RuleRouter(
                decision_provider=provider,
                jev_enabled=True,
                provider_mode="jev",
            ).route(_context("分析谁发言最多"))
        )

        self.assertEqual(decision.source, "rule")
        self.assertEqual(decision.route, "standard_execution")
        self.assertEqual(provider.calls, 0)

    def test_jev_mode_uses_jev_only_for_ambiguous_route(self) -> None:
        provider = _DecisionProvider(
            RouterProviderResult(
                "planned_execution",
                0.71,
                {"standard_execution": 0.29, "planned_execution": 0.71},
                provider="openrouter",
                model="typesafe/jev-1.13",
            )
        )

        decision = asyncio.run(
            RuleRouter(
                completion=lambda _: self.fail("Jev mode called the existing LLM"),
                decision_provider=provider,
                jev_enabled=True,
                provider_mode="jev",
            ).route(_context())
        )

        self.assertEqual(decision.route, "planned_execution")
        self.assertEqual(decision.source, "jev")
        self.assertEqual(decision.provider, "openrouter")
        self.assertEqual(decision.confidence, 0.71)
        self.assertEqual(provider.calls, 1)

    def test_jev_failure_keeps_static_rule_and_exposes_stable_degradation(self) -> None:
        provider = _DecisionProvider(RouterDecisionProviderError("JEV_ROUTER_RATE_LIMITED"))

        decision = asyncio.run(
            RuleRouter(
                decision_provider=provider,
                jev_enabled=True,
                provider_mode="jev",
            ).route(_context())
        )

        self.assertEqual(decision.route, "standard_execution")
        self.assertEqual(decision.source, "rule")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.degradation_code, "JEV_ROUTER_RATE_LIMITED")

    def test_unknown_provider_failure_records_only_its_exception_type(self) -> None:
        decision = asyncio.run(
            RuleRouter(
                decision_provider=_DecisionProvider(RuntimeError("private response text")),
                jev_enabled=True,
                provider_mode="jev",
            ).route(_context())
        )
        self.assertEqual(decision.degradation_code, "JEV_ROUTER_PROVIDER_ERROR")
        self.assertEqual(decision.provider_error_type, "RuntimeError")
        self.assertNotIn("private response text", str(decision))

    def test_shadow_success_or_failure_cannot_change_primary_llm_route(self) -> None:
        async def completion(_: str) -> CompletionResult:
            return CompletionResult(
                '{"route":"standard_execution","confidence":0.63,"reason":"baseline"}',
                CompletionObservation(provider="primary-provider", model="primary-model"),
            )

        successful_shadow = _DecisionProvider(
            RouterProviderResult(
                "planned_execution",
                0.91,
                {"standard_execution": 0.09, "planned_execution": 0.91},
                provider="openrouter",
                model="typesafe/jev-1.13",
            )
        )
        successful = asyncio.run(
            RuleRouter(
                completion,
                decision_provider=successful_shadow,
                jev_enabled=True,
                provider_mode="shadow",
            ).route(_context())
        )
        self.assertEqual(successful.route, "standard_execution")
        self.assertEqual(successful.source, "llm")
        self.assertFalse(successful.degraded)
        self.assertEqual(successful.shadow.route, "planned_execution")
        self.assertEqual(successful.shadow.confidence, 0.91)

        failing_shadow = _DecisionProvider(RouterDecisionProviderError("JEV_ROUTER_TIMEOUT"))
        failed = asyncio.run(
            RuleRouter(
                completion,
                decision_provider=failing_shadow,
                jev_enabled=True,
                provider_mode="shadow",
            ).route(_context())
        )
        self.assertEqual(failed.route, "standard_execution")
        self.assertEqual(failed.source, "llm")
        self.assertFalse(failed.degraded)
        self.assertTrue(failed.shadow.degraded)
        self.assertEqual(failed.shadow.degradation_code, "JEV_ROUTER_TIMEOUT")

    def test_shadow_success_does_not_rescue_a_failed_primary_llm(self) -> None:
        def failed_completion(_: str) -> str:
            raise RuntimeError("private response text")

        provider = _DecisionProvider(
            RouterProviderResult(
                "planned_execution",
                0.9,
                {"standard_execution": 0.1, "planned_execution": 0.9},
            )
        )
        decision = asyncio.run(
            RuleRouter(
                failed_completion,
                decision_provider=provider,
                jev_enabled=True,
                provider_mode="shadow",
            ).route(_context())
        )

        self.assertEqual(decision.route, "standard_execution")
        self.assertEqual(decision.source, "rule")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.degradation_code, "ROUTER_COMPLETION_PROVIDER_ERROR")
        self.assertEqual(decision.provider_error_type, "RuntimeError")
        self.assertEqual(decision.shadow.route, "planned_execution")

    def test_jev_timeout_keeps_static_route(self) -> None:
        class _NeverCompletes:
            async def decide(self, context: QueryContext) -> RouterProviderResult:
                await asyncio.Future()

        decision = asyncio.run(
            RuleRouter(
                decision_provider=_NeverCompletes(),
                jev_enabled=True,
                provider_mode="jev",
                decision_timeout_seconds=0.001,
            ).route(_context())
        )
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.degradation_code, "JEV_ROUTER_TIMEOUT")
        self.assertEqual(decision.source, "rule")


class RouterJevEvaluationTests(unittest.TestCase):
    def test_manifest_is_provisional_and_report_excludes_raw_queries(self) -> None:
        suite_id, cases = load_router_evaluation_cases(Path("evaluation/router-jev/cases-v1.json"))
        self.assertEqual(suite_id, "router-provider-diagnostic-v1")
        self.assertEqual(len(cases), 16)

        async def llm_completion(_: str) -> CompletionResult:
            return CompletionResult(
                '{"route":"standard_execution","confidence":0.6,"reason":"test"}',
                CompletionObservation(
                    provider="primary-provider",
                    model="primary-model",
                    usage={"input_tokens": 3, "output_tokens": 2},
                ),
            )

        jev_provider = _DecisionProvider(
            RouterProviderResult(
                "standard_execution",
                0.65,
                {"standard_execution": 0.65, "planned_execution": 0.35},
                usage={"input_tokens": 4, "output_tokens": 1, "cost": 0.0001},
                provider="openrouter",
                model="typesafe/jev-1.13",
            )
        )
        report = asyncio.run(
            run_paired_router_evaluation(
                suite_id=suite_id,
                cases=cases,
                llm_completion=llm_completion,
                jev_provider=jev_provider,
                llm_identity={"provider": "primary-provider", "model": "primary-model"},
                jev_model="typesafe/jev-1.13",
                repetitions=2,
            )
        )
        self.assertEqual(report["case_summary"]["ambiguous_case_count"], 13)
        self.assertEqual(report["case_summary"]["provider_calls_per_variant"], 26)
        self.assertEqual(report["promotion_recommendation"]["recommendation"], "continue_shadow")
        self.assertFalse(report["promotion_recommendation"]["promoted"])
        self.assertAlmostEqual(
            report["metrics"]["jev"]["usage"]["cost_usd_actual"],
            0.0026,
        )
        self.assertAlmostEqual(
            report["metrics"]["jev"]["usage"]["successful_request_cost_usd_per_100_estimate"],
            0.01,
        )
        serialized = json.dumps(report, ensure_ascii=False)
        for case in cases:
            self.assertNotIn(case.query, serialized)
        self.assertEqual(report["cases"][0]["adjudication_status"], "pending_human_adjudication")

    def test_output_is_create_only_and_reports_contract_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            write_router_evaluation_report({"status": "completed"}, output)
            with self.assertRaises(RouterEvaluationError):
                write_router_evaluation_report({"status": "completed"}, output)

    def test_cli_exposes_router_evaluation_without_requiring_other_query_options(self) -> None:
        parsed = build_parser().parse_args(
            ["eval", "router-jev", "--output", "data/evaluation/router-jev/run.json"]
        )
        self.assertEqual(parsed.evaluation_command, "router-jev")
        self.assertEqual(parsed.repeat, 1)
        self.assertEqual(parsed.cases, Path("evaluation/router-jev/cases-v1.json"))


if __name__ == "__main__":
    unittest.main()
