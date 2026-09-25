from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from agents import ModelResponse, Usage
from agents.models.interface import Model
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from trivae.bootstrap.application import create_application
from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope
from trivae.config.settings import load_settings
from trivae.query.completion import CompletionObservation, CompletionResult
from trivae.query.contracts import QueryRequest
from trivae.query.orchestrator import QueryOrchestrator
from trivae.query.planner import SoftPlanner, render_plan_guidance
from trivae.query.router import RuleRouter
from trivae.query.runtime.contracts import AgentRunRequest, RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter


class _RecordingSearchTool:
    """测试真实 SDK tool adapter 会收到同一个 trusted scope。"""

    name = "search_messages"

    def __init__(self) -> None:
        self.requests: list[tuple[object, ExecutionScope]] = []

    def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
        self.requests.append((request, scope))
        return ToolEnvelope("ok", None, {"truncated": False}, None)


class _RecordingRuntime:
    """不依赖 provider 的 Orchestrator spy，返回稳定 RuntimeResult。"""

    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> RuntimeResult:
        self.requests.append(request)
        return RuntimeResult(
            final_answer="recorded",
            provider="test",
            model="test-model",
            termination="completed",
            tool_calls=(),
        )


class RouterTests(unittest.TestCase):
    """Router 只判断 planning value，不把单个业务词当成 route。"""

    def _context(self, query: str) -> Any:
        from trivae.query.contracts import QueryContext

        return QueryContext(query, "zh-CN", (), {}, ("search_messages",))

    def test_obvious_standard_and_single_keyword_regression(self) -> None:
        router = RuleRouter()
        decision = asyncio.run(router.route(self._context("分析谁发言最多")))
        self.assertEqual(decision.route, "standard_execution")
        self.assertEqual(decision.source, "rule")

    def test_obvious_planned_uses_multiple_structural_signals(self) -> None:
        router = RuleRouter()
        decision = asyncio.run(
            router.route(self._context("找出故障的完整证据链，并比较前后观点变化"))
        )
        self.assertEqual(decision.route, "planned_execution")
        self.assertGreater(decision.confidence, 0.8)

    def test_ambiguous_query_uses_injected_llm_json(self) -> None:
        calls: list[str] = []

        def completion(prompt: str) -> str:
            calls.append(prompt)
            return '{"route":"planned_execution","confidence":0.81,"reason":"dependent investigation"}'

        decision = asyncio.run(RuleRouter(completion).route(self._context("请总结 alpha 的讨论")))
        self.assertEqual(decision.route, "planned_execution")
        self.assertEqual(decision.source, "llm")
        self.assertFalse(decision.degraded)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("scope", calls[0].lower())

    def test_invalid_llm_output_keeps_rule_and_marks_degraded(self) -> None:
        decision = asyncio.run(RuleRouter(lambda _: "not json").route(self._context("请总结 alpha 的讨论")))
        self.assertEqual(decision.route, "standard_execution")
        self.assertTrue(decision.degraded)
        self.assertEqual(decision.degradation_code, "ROUTER_COMPLETION_INVALID")

    def test_llm_unknown_route_and_exception_are_not_query_failures(self) -> None:
        unknown = asyncio.run(
            RuleRouter(lambda _: '{"route":"other","confidence":0.9,"reason":"bad"}').route(
                self._context("请总结 alpha 的讨论")
            )
        )
        self.assertTrue(unknown.degraded)

        def raise_error(_: str) -> str:
            raise RuntimeError("provider body contains secret")

        failed = asyncio.run(RuleRouter(raise_error).route(self._context("请总结 alpha 的讨论")))
        self.assertEqual(failed.route, "standard_execution")
        self.assertEqual(failed.degradation_code, "ROUTER_COMPLETION_PROVIDER_ERROR")


class PlannerTests(unittest.TestCase):
    """Planner 输出只是一份 bounded soft guidance。"""

    def _context(self) -> Any:
        from trivae.query.contracts import QueryContext

        return QueryContext("investigate", "zh-CN", (), {}, ("search_messages",))

    def test_valid_plan_filters_unknown_tools_dedupes_and_bounds_size(self) -> None:
        payload = {
            "version": 1,
            "title": "Investigate",
            "intent": "evidence",
            "steps": [
                {
                    "goal": f"goal-{index}",
                    "suggested_tools": ["search_messages", "unknown", "search_messages"],
                    "evidence_needed": ["message evidence", "message evidence"],
                }
                for index in range(8)
            ],
            "success_criteria": [f"criterion-{index}" for index in range(8)],
        }
        planner = SoftPlanner(lambda _: json.dumps(payload))
        result = asyncio.run(planner.plan(self._context()))
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(len(result.plan.steps), 5)
        self.assertEqual(len(result.plan.success_criteria), 5)
        self.assertEqual(result.plan.steps[0].suggested_tools, ("search_messages",))
        self.assertEqual(result.plan.steps[0].evidence_needed, ("message evidence",))
        guidance = render_plan_guidance(result.plan)
        self.assertIn("soft plan guidance", guidance.lower())
        self.assertNotIn("execute(...)" , guidance)

    def test_prompt_spells_out_the_existing_plan_contract(self) -> None:
        prompt = SoftPlanner._build_prompt(self._context())
        self.assertIn("intent MUST be exactly one of", prompt)
        self.assertIn("summary, trend, relationship, search, comparison, evidence, mixed", prompt)
        self.assertIn("steps MUST be a JSON array", prompt)
        self.assertIn("success_criteria MUST be a non-empty JSON array", prompt)
        self.assertIn("suggest get_recent_messages before SQL", prompt)
        self.assertIn("A SQL count alone is not verified zero-result evidence", prompt)

    def test_malformed_and_structurally_invalid_plan_fail_explicitly(self) -> None:
        malformed = asyncio.run(SoftPlanner(lambda _: "{bad").plan(self._context()))
        self.assertIsNone(malformed.plan)
        self.assertEqual(malformed.failure.code, "invalid_output")
        self.assertEqual(malformed.failure.detail_code, "json_decode_error")
        self.assertEqual(malformed.failure.parse_stage, "json_decode")

        invalid = asyncio.run(
            SoftPlanner(lambda _: '{"version":1,"title":"x","intent":"evidence","steps":[],"success_criteria":[]}').plan(
                self._context()
            )
        )
        self.assertIsNone(invalid.plan)
        self.assertEqual(invalid.failure.code, "invalid_output")
        self.assertEqual(invalid.failure.detail_code, "empty_steps")
        self.assertEqual(invalid.failure.parse_stage, "steps_validation")

    def test_plan_contract_failures_are_classified_by_field(self) -> None:
        cases = (
            (
                "invalid_intent",
                '{"version":1,"title":"x","intent":"other","steps":[{"goal":"g"}],"success_criteria":["c"]}',
                "intent_validation",
            ),
            (
                "missing_steps",
                '{"version":1,"title":"x","intent":"evidence","success_criteria":["c"]}',
                "steps_validation",
            ),
            (
                "invalid_steps",
                '{"version":1,"title":"x","intent":"evidence","steps":null,"success_criteria":["c"]}',
                "steps_validation",
            ),
            (
                "empty_success_criteria",
                '{"version":1,"title":"x","intent":"evidence","steps":[{"goal":"g"}],"success_criteria":[]}',
                "success_criteria_validation",
            ),
        )
        for detail_code, raw, parse_stage in cases:
            with self.subTest(detail_code=detail_code):
                result = asyncio.run(SoftPlanner(lambda _: raw).plan(self._context()))
                self.assertIsNone(result.plan)
                self.assertEqual(result.failure.code, "invalid_output")
                self.assertEqual(result.failure.detail_code, detail_code)
                self.assertEqual(result.failure.parse_stage, parse_stage)

    def test_empty_provider_content_is_not_reported_as_json_decode_error(self) -> None:
        observation = CompletionObservation(
            provider="deepseek",
            model="deepseek-v4-flash",
            request={"max_tokens": 2048, "json_mode": True},
            finish_reason="stop",
            response_content=None,
        )
        result = asyncio.run(
            SoftPlanner(lambda _: CompletionResult(None, observation)).plan(self._context())
        )
        self.assertIsNone(result.plan)
        self.assertEqual(result.failure.code, "generation_error")
        self.assertEqual(result.failure.detail_code, "empty_response")
        self.assertEqual(result.failure.parse_stage, "provider_response")
        self.assertEqual(result.observation.provider, "deepseek")

    def test_provider_length_is_classified_before_json_parsing(self) -> None:
        observation = CompletionObservation(
            provider="deepseek",
            model="deepseek-v4-flash",
            request={"max_tokens": 2048, "json_mode": True},
            finish_reason="length",
            usage={"output_tokens": 2048},
            response_content='{"version":1',
        )
        result = asyncio.run(
            SoftPlanner(lambda _: CompletionResult('{"version":1', observation)).plan(self._context())
        )
        self.assertIsNone(result.plan)
        self.assertEqual(result.failure.code, "invalid_output")
        self.assertEqual(result.failure.detail_code, "provider_length")
        self.assertEqual(result.failure.parse_stage, "provider_response")
        self.assertEqual(result.observation.finish_reason, "length")

    def test_provider_timeout_keeps_request_projection_and_timeout_stage(self) -> None:
        async def slow_completion(_: str) -> str:
            await asyncio.sleep(0.05)
            return "{}"

        planner = SoftPlanner(
            slow_completion,
            completion_timeout_seconds=0.001,
            completion_request={
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "max_tokens": 2048,
                "json_mode": True,
            },
        )
        result = asyncio.run(planner.plan(self._context()))
        self.assertIsNone(result.plan)
        self.assertEqual(result.failure.code, "timeout")
        self.assertEqual(result.failure.detail_code, "completion_timeout")
        self.assertEqual(result.failure.parse_stage, "provider_request")
        self.assertEqual(result.observation.request["max_tokens"], 2048)

    def test_unavailable_planner_is_a_degraded_optional_stage(self) -> None:
        result = asyncio.run(SoftPlanner().plan(self._context()))
        self.assertIsNone(result.plan)
        self.assertEqual(result.failure.code, "unavailable")


class OrchestratorTests(unittest.TestCase):
    """两路 route 只改变 soft guidance，runtime 和 capability boundary 不变。"""

    def test_answer_candidate_observation_keeps_only_shape_metrics(self) -> None:
        """答案深度诊断只记录 claim 数和正文长度，不泄露模型正文。"""

        output = json.dumps(
            {
                "claims": [
                    {"text": "主题一的完整说明"},
                    {"text": "主题二的完整说明与链接"},
                ]
            },
            ensure_ascii=False,
        )

        # 通过长度而不是正文内容观测 candidate，避免 Trace 复制聊天或模型原文。
        self.assertEqual(
            QueryOrchestrator._answer_candidate_observation(output),
            {
                "candidate_claim_count": 2,
                "candidate_claim_text_lengths": (8, 11),
            },
        )
        self.assertEqual(QueryOrchestrator._answer_candidate_observation("not-json"), {})

    def test_standard_and_planned_use_same_runtime_and_preserve_scope(self) -> None:
        runtime = _RecordingRuntime()
        scope = ExecutionScope(allowed_session_ids=("qq:100",))
        planner_payload = json.dumps(
            {
                "version": 1,
                "title": "Evidence",
                "intent": "evidence",
                "steps": [{"goal": "find evidence", "suggested_tools": ["search_messages"]}],
                "success_criteria": ["answer with evidence"],
            }
        )
        orchestrator = QueryOrchestrator(
            runtime,
            RuleRouter(),
            SoftPlanner(lambda _: planner_payload),
            capability_names=("search_messages",),
        )

        standard = asyncio.run(
            orchestrator.run(
                QueryRequest("分析谁发言最多", scope, available_capabilities=("search_messages",))
            )
        )
        planned = asyncio.run(
            orchestrator.run(
                QueryRequest(
                    "找出完整证据链，并比较前后观点变化",
                    scope,
                    available_capabilities=("search_messages",),
                )
            )
        )

        self.assertIsNone(standard.plan)
        self.assertIsNotNone(planned.plan)
        self.assertEqual(len(runtime.requests), 2)
        self.assertIs(runtime.requests[0].scope, scope)
        self.assertIs(runtime.requests[1].scope, scope)
        self.assertIsNotNone(runtime.requests[1].plan_guidance)
        self.assertNotIn("qq:100", runtime.requests[1].plan_guidance or "")

    def test_planner_degradation_still_executes_same_runtime(self) -> None:
        runtime = _RecordingRuntime()
        orchestrator = QueryOrchestrator(
            runtime,
            RuleRouter(),
            SoftPlanner(),
            capability_names=("search_messages",),
        )
        result = asyncio.run(
            orchestrator.run(
                QueryRequest(
                    "找出完整证据链，并比较前后观点变化",
                    ExecutionScope(),
                    available_capabilities=("search_messages",),
                )
            )
        )
        self.assertEqual(result.runtime_result.final_answer, "recorded")
        self.assertEqual(result.diagnostics[0].code, "PLANNER_UNAVAILABLE")
        self.assertEqual(len(runtime.requests), 1)

    def test_router_shadow_trace_and_evaluation_keep_primary_and_jev_separate(self) -> None:
        from trivae.evaluation.checks import query_result_snapshot
        from trivae.observability.collector import TraceCollector
        from trivae.observability.sqlite import SQLiteTraceStore
        from trivae.query.router import RouterProviderResult

        class JevProvider:
            async def decide(self, context):
                return RouterProviderResult(
                    route="planned_execution",
                    confidence=0.91,
                    probabilities={"standard_execution": 0.09, "planned_execution": 0.91},
                    provider="openrouter",
                    model="typesafe/jev-1.13-20260917",
                )

        async def primary_completion(_: str) -> CompletionResult:
            return CompletionResult(
                '{"route":"standard_execution","confidence":0.62,"reason":"baseline"}',
                CompletionObservation(provider="primary-provider", model="primary-model"),
            )

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "trace.sqlite3")
            trace = TraceCollector(
                store,
                trace_id="trace-router-shadow",
                request_id="request-router-shadow",
            )
            runtime = _RecordingRuntime()
            router = RuleRouter(
                primary_completion,
                decision_provider=JevProvider(),
                jev_enabled=True,
                provider_mode="shadow",
            )
            orchestrator = QueryOrchestrator(runtime, router, SoftPlanner())
            result = asyncio.run(
                orchestrator.run(
                    QueryRequest("请总结 alpha 的讨论", ExecutionScope()),
                    trace=trace,
                )
            )
            stored_trace = store.read_trace("trace-router-shadow")
            snapshot = query_result_snapshot(result)
            store.close()

        self.assertEqual(result.route_decision.route, "standard_execution")
        self.assertEqual(result.route_decision.source, "llm")
        self.assertEqual(result.route_decision.shadow.route, "planned_execution")
        decision_event = next(event for event in stored_trace.events if event.operation == "router.decision")
        shadow_event = next(event for event in stored_trace.events if event.operation == "router.shadow_decision")
        self.assertEqual(decision_event.payload["route"], "standard_execution")
        self.assertEqual(decision_event.payload["source"], "llm")
        self.assertEqual(shadow_event.payload["route"], "planned_execution")
        self.assertEqual(shadow_event.payload["model"], "typesafe/jev-1.13-20260917")
        self.assertEqual(snapshot["route"], "standard_execution")
        self.assertEqual(snapshot["router_shadow"]["route"], "planned_execution")
        self.assertEqual(len(runtime.requests), 1)

    def test_planner_failure_trace_keeps_debug_provider_and_parse_facts(self) -> None:
        from trivae.observability.collector import TraceCollector
        from trivae.observability.sqlite import SQLiteTraceStore

        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "trace.sqlite3")
            trace = TraceCollector(
                store,
                trace_id="trace-planner-debug",
                request_id="request-planner-debug",
                profile="debug",
            )
            observation = CompletionObservation(
                provider="deepseek",
                model="deepseek-v4-flash",
                request={"max_tokens": 2048, "json_mode": True},
                finish_reason="stop",
                usage={"output_tokens": 12},
                response_content='{"version":1,"title":"x","intent":"bad"}',
            )
            runtime = _RecordingRuntime()
            orchestrator = QueryOrchestrator(
                runtime,
                RuleRouter(),
                SoftPlanner(lambda _: CompletionResult(observation.response_content, observation)),
                capability_names=("search_messages",),
            )
            result = asyncio.run(
                orchestrator.run(
                    QueryRequest(
                        "找出完整证据链，并比较前后观点变化",
                        ExecutionScope(),
                        trace_profile="debug",
                        available_capabilities=("search_messages",),
                    ),
                    trace=trace,
                )
            )
            self.assertEqual(result.diagnostics[0].code, "PLANNER_INVALID_OUTPUT")
            events = store.read_trace("trace-planner-debug").events
            failure_event = next(event for event in events if event.operation == "planner.failed")
            self.assertEqual(failure_event.payload["parse_stage"], "intent_validation")
            self.assertEqual(failure_event.payload["failure_detail_code"], "invalid_intent")
            self.assertEqual(failure_event.payload["finish_reason"], "stop")
            self.assertIn("response_content", failure_event.payload)
            self.assertEqual(len(runtime.requests), 1)
            store.close()


class RuntimeExecutionTests(unittest.TestCase):
    """验证真实 SDK streamed loop 的事件、预算、backstop、取消和错误投影。"""

    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.tool = _RecordingSearchTool()
        self.registry.register(self.tool)
        self.scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)

    def test_stream_emits_content_tool_usage_and_completed_last(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(output=[function_call("search_messages", {"keyword": "alpha"}, call_id="c1")]),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model, max_turns=4)
        events = asyncio.run(self._collect(runtime.stream(AgentRunRequest("q", self.scope))))
        kinds = [event.type for event in events]
        self.assertIn("content_delta", kinds)
        self.assertIn("tool_started", kinds)
        self.assertIn("tool_completed", kinds)
        self.assertIn("usage_update", kinds)
        self.assertEqual(kinds[-1], "completed")
        self.assertEqual(events[-1].result.termination, "completed")

    def test_tool_budget_counts_multiple_calls_as_one_round_and_finalizes(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call("search_messages", {"keyword": "a"}, call_id="c1"),
                        function_call("search_messages", {"keyword": "b"}, call_id="c2"),
                    ]
                ),
                ModelStep(output=[assistant_message("budgeted final")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            max_turns=4,
            max_tool_rounds=1,
        )
        events = asyncio.run(self._collect(runtime.stream(AgentRunRequest("q", self.scope))))
        result = events[-1].result
        self.assertEqual(result.termination, "completed")
        self.assertEqual(result.tool_rounds, 1)
        self.assertEqual(result.tool_count, 2)
        self.assertEqual({call.tool_round for call in result.tool_calls}, {1})
        self.assertEqual([len(call.tools) for call in model.calls], [1, 0])
        self.assertLess(
            [event.type for event in events].index("tool_completed"),
            [event.type for event in events].index("finalizing"),
        )

    def test_sdk_absolute_backstop_is_not_normal_budget_completion(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(output=[function_call("search_messages", {"keyword": "a"}, call_id="c1")]),
                ModelStep(output=[function_call("search_messages", {"keyword": "a"}, call_id="c2")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            max_turns=2,
            max_tool_rounds=5,
        )
        result = asyncio.run(runtime.run(AgentRunRequest("q", self.scope)))
        self.assertEqual(result.termination, "max_turns_exceeded")
        self.assertEqual(result.error.code, "MAX_TURNS_EXCEEDED")
        self.assertEqual(result.error.category, "absolute_backstop")

    def test_cancellation_before_run_skips_model_and_final_synthesis(self) -> None:
        model = ScriptedModel([ModelStep(output=[assistant_message("must not run")])])
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model)
        abort_event = asyncio.Event()
        abort_event.set()
        events = asyncio.run(
            self._collect(runtime.stream(AgentRunRequest("q", self.scope), abort_event))
        )
        self.assertEqual([event.type for event in events], ["run_started", "aborted"])
        self.assertEqual(events[-1].result.termination, "aborted")
        self.assertEqual(len(model.calls), 0)

    def test_provider_and_unknown_tool_errors_are_secret_safe_terminal_failures(self) -> None:
        secret = "provider-secret"

        class ExplodingTool:
            name = "search_messages"

            def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
                raise RuntimeError(f"{secret} raw request body")

        registry = CapabilityRegistry()
        registry.register(ExplodingTool())
        model = ScriptedModel(
            [ModelStep(output=[function_call("search_messages", {"keyword": "a"}, call_id="c1")])]
        )
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=model)
        result = asyncio.run(runtime.run(AgentRunRequest("q", self.scope)))
        self.assertEqual(result.termination, "failed")
        self.assertEqual(result.error.code, "RUNTIME_ERROR")
        self.assertNotIn(secret, result.error.message)
        self.assertIsNotNone(result.error.diagnostic_type)

    def test_injected_model_and_provider_client_are_closed_idempotently(self) -> None:
        class ClosableScriptedModel(ScriptedModel):
            def __init__(self) -> None:
                super().__init__()
                self.closed = 0

            async def close(self) -> None:
                self.closed += 1

        model = ClosableScriptedModel()
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model)
        asyncio.run(runtime.aclose())
        asyncio.run(runtime.aclose())
        self.assertEqual(model.closed, 1)

    def test_real_provider_client_can_be_closed_without_network_request(self) -> None:
        settings = load_settings(
            {
                "DEEPSEEK_API_KEY": "test-secret",
                "TRIVAE_MODEL_NAME": "deepseek-chat-test",
            }
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, settings=settings)
        self.assertIsNotNone(runtime._provider_client)
        asyncio.run(runtime.aclose())
        self.assertIsNone(runtime._provider_client)

    async def _collect(self, stream: Any) -> list[Any]:
        return [event async for event in stream]


class _BlockingModel(Model):
    """用于验证运行中的 abort 会停止等待中的 model stream。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        await self.release.wait()
        return ModelResponse(output=[], usage=Usage(requests=1), response_id=None)

    async def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        self.started.set()
        await self.release.wait()
        if False:
            yield None


class CancellationDuringModelTests(unittest.TestCase):
    """abort 是 terminal intent，不能转成 final synthesis。"""

    def test_cancellation_during_model_becomes_aborted(self) -> None:
        async def scenario() -> list[Any]:
            registry = CapabilityRegistry()
            registry.register(_RecordingSearchTool())
            model = _BlockingModel()
            runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, max_turns=4)
            abort_event = asyncio.Event()
            task = asyncio.create_task(
                self._collect(runtime.stream(AgentRunRequest("q", ExecutionScope()), abort_event))
            )
            await model.started.wait()
            abort_event.set()
            return await task

        events = asyncio.run(scenario())
        self.assertEqual(events[-1].type, "aborted")
        self.assertNotIn("completed", [event.type for event in events])
        self.assertNotIn("finalizing", [event.type for event in events])

    async def _collect(self, stream: Any) -> list[Any]:
        return [event async for event in stream]


class ApplicationLifecycleTests(unittest.TestCase):
    """Application query entry和 runtime close 由 composition root 管理。"""

    def test_query_entrypoint_and_async_close(self) -> None:
        class ClosableRuntime(_RecordingRuntime):
            def __init__(self) -> None:
                super().__init__()
                self.closed = 0

            async def aclose(self) -> None:
                self.closed += 1

        with tempfile.TemporaryDirectory() as directory:
            runtime = ClosableRuntime()
            application = create_application(Path(directory) / "app.sqlite3", agent_runtime=runtime)
            result = asyncio.run(
                application.query(QueryRequest("分析谁发言最多", ExecutionScope()))
            )
            self.assertEqual(result.final_answer, "recorded")
            self.assertEqual(len(runtime.requests), 1)
            asyncio.run(application.aclose())
            asyncio.run(application.aclose())
            self.assertEqual(runtime.closed, 1)


if __name__ == "__main__":
    unittest.main()
