from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from trivae.capabilities import CapabilityRegistry, ExecutionScope, ToolEnvelope
from trivae.config.limits import (
    DEFAULT_PER_CALL_TOOL_RESULT_CAP,
    DEFAULT_PER_CALL_TOOL_RESULT_PERCENT,
    DEFAULT_RUN_TOOL_EVIDENCE_CAP,
    DEFAULT_RUN_TOOL_EVIDENCE_PERCENT,
    DEFAULT_TOOL_RESULT_TOKEN_BUDGET,
)
from trivae.config.model_capabilities import resolve_context_window, resolve_reasoning_effort
from trivae.config.settings import ModelSettings, SettingsError, load_settings
from trivae.evaluation.checks import operational_measurements
from trivae.observability.collector import TraceableAgentRuntime, TraceCollector
from trivae.observability.projection import project_trace
from trivae.observability.sqlite import SQLiteTraceStore
from trivae.query.contracts import QueryResult
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.query.router import RouteDecision
from trivae.query.runtime.budget import (
    ToolResultBudgetConfig,
    ToolResultBudgetError,
    ToolResultBudgetExhausted,
)
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.retrieval.structured import (
    Coverage,
    LexicalQuery,
    MessageHit,
    MessageProjection,
    RetrievalMetadata,
    RetrievalResult,
)


def _message(index: int, content: str) -> MessageProjection:
    """构造带稳定 identity 的 canonical message，专门用于 projection 预算测试。"""

    return MessageProjection(
        internal_message_id=f"budget-session:m{index}",
        session_id="budget-session",
        source_message_id=f"source-{index}",
        sender_user_id="user-1",
        sender_platform_id=None,
        sender_uin=None,
        sender_name="Alice",
        timestamp=1_700_000_000_000 + index,
        seq=index,
        message_type="text",
        normalized_content=content,
        reply_to_source_message_id=None,
        recalled=False,
        system=False,
        session_display="Budget Fixture",
    )


class _TinySearchTool:
    """返回很小的成功 envelope，便于隔离 Runtime 预算记账而不引入检索变量。"""

    name = "search_messages"

    def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
        """保留 typed tool 入口，但不让 fixture 正文影响预算断言。"""

        return ToolEnvelope("ok", None, {"truncated": False}, None)


def _dynamic_settings(context_window_tokens: int = 64_000) -> ModelSettings:
    """构造不需要 provider key 的 injected-runtime dynamic settings。"""

    return ModelSettings(
        api_key="",
        base_url="https://example.test/v1",
        provider="injected",
        model_name="fixture-model",
        max_turns=6,
        tool_result_budget_mode="dynamic",
        model_context_window_tokens=context_window_tokens,
    )


class ToolResultBudgetPolicyTests(unittest.TestCase):
    """覆盖公式、来源、累计扣减和 fixed compatibility。"""

    def test_dynamic_pool_formula_and_absolute_cap(self) -> None:
        expected_run = {
            32_000: 8_000,
            64_000: 16_000,
            128_000: 32_000,
            256_000: 64_000,
            1_000_000: 250_000,
        }
        expected_per_call = {
            32_000: 16_000,
            64_000: 32_000,
            128_000: 64_000,
            256_000: DEFAULT_PER_CALL_TOOL_RESULT_CAP,
            1_000_000: DEFAULT_PER_CALL_TOOL_RESULT_CAP,
        }
        for context_window, run_budget in expected_run.items():
            with self.subTest(context_window=context_window):
                config = ToolResultBudgetConfig(
                    mode="dynamic",
                    context_window_tokens=context_window,
                )
                self.assertEqual(config.run_tool_evidence_budget, run_budget)
                self.assertEqual(config.per_call_ceiling, expected_per_call[context_window])
                self.assertEqual(config.context_window_source, "explicit_config")
                self.assertEqual(config.budget_resolution, "dynamic_configured")

    def test_explicit_run_pool_is_independent_from_per_call_ceiling(self) -> None:
        for run_pool in (128_000, 256_000):
            with self.subTest(run_pool=run_pool):
                config = ToolResultBudgetConfig(
                    mode="dynamic",
                    context_window_tokens=1_000_000,
                    run_tool_evidence_budget_override=run_pool,
                )
                self.assertEqual(config.per_call_ceiling, DEFAULT_PER_CALL_TOOL_RESULT_CAP)
                self.assertEqual(config.run_tool_evidence_budget, run_pool)

    def test_context_resolution_uses_verified_registry_before_fallback(self) -> None:
        official = resolve_context_window(
            explicit_context_window_tokens=None,
            provider="deepseek",
            model_name="deepseek-flash",
        )
        self.assertEqual(official.context_window_tokens, 1_000_000)
        self.assertEqual(official.source, "verified_model_registry")
        self.assertEqual(
            resolve_reasoning_effort(provider="deepseek", model_name="deepseek-flash"),
            "low",
        )

        verified = resolve_context_window(
            explicit_context_window_tokens=None,
            provider="opencode-go",
            model_name="deepseek-v4-flash",
        )
        self.assertEqual(verified.context_window_tokens, 1_000_000)
        self.assertEqual(verified.source, "verified_model_registry")
        self.assertEqual(
            resolve_reasoning_effort(provider="opencode-go", model_name="deepseek-v4-flash"),
            "low",
        )
        self.assertIsNone(
            resolve_reasoning_effort(provider="deepseek", model_name="deepseek-flash-preview")
        )

        explicit = resolve_context_window(
            explicit_context_window_tokens=128_000,
            provider="opencode-go",
            model_name="deepseek-v4-flash",
        )
        self.assertEqual(explicit.context_window_tokens, 128_000)
        self.assertEqual(explicit.source, "explicit_config")

    def test_unknown_dynamic_context_uses_safe_fixed_run_pool(self) -> None:
        config = ToolResultBudgetConfig(mode="dynamic")
        self.assertIsNone(config.context_window_tokens)
        self.assertEqual(config.context_window_source, "fallback")
        self.assertEqual(config.budget_resolution, "dynamic_fallback")
        self.assertEqual(config.run_tool_evidence_budget, DEFAULT_TOOL_RESULT_TOKEN_BUDGET)
        self.assertEqual(config.per_call_ceiling, DEFAULT_TOOL_RESULT_TOKEN_BUDGET)

        reservation = config.new_policy().begin_call()
        self.assertEqual(reservation.effective_per_call_budget, DEFAULT_TOOL_RESULT_TOKEN_BUDGET)

    def test_fixed_mode_preserves_previous_per_call_budget(self) -> None:
        policy = ToolResultBudgetConfig(mode="fixed").new_policy()
        first = policy.begin_call()
        snapshot = policy.complete_call(
            first,
            projected_tool_result_tokens=123,
            truncated=False,
            omitted_context_messages=0,
            omitted_hit_messages=0,
        )

        self.assertEqual(snapshot.budget_mode, "fixed")
        self.assertEqual(snapshot.effective_per_call_tool_result_budget, DEFAULT_TOOL_RESULT_TOKEN_BUDGET)
        self.assertIsNone(snapshot.run_tool_evidence_budget)
        self.assertIsNone(snapshot.remaining_run_tool_evidence_budget_before_call)
        self.assertIsNone(snapshot.remaining_run_tool_evidence_budget_after_call)
        self.assertEqual(snapshot.context_window_source, "not_used")

    def test_dynamic_pool_accounts_actual_projection_not_reserved_ceiling(self) -> None:
        policy = ToolResultBudgetConfig(mode="dynamic", context_window_tokens=64_000).new_policy()
        first = policy.begin_call()
        self.assertEqual(first.remaining_run_tool_evidence_budget_before, 16_000)
        self.assertEqual(first.effective_per_call_budget, 16_000)
        first_snapshot = policy.complete_call(
            first,
            projected_tool_result_tokens=4_000,
            truncated=True,
            omitted_context_messages=7,
            omitted_hit_messages=11,
        )
        self.assertEqual(first_snapshot.remaining_run_tool_evidence_budget_after_call, 12_000)

        second = policy.begin_call()
        self.assertEqual(second.remaining_run_tool_evidence_budget_before, 12_000)
        self.assertEqual(second.effective_per_call_budget, 12_000)
        second_snapshot = policy.complete_call(
            second,
            projected_tool_result_tokens=6_000,
            truncated=False,
            omitted_context_messages=0,
            omitted_hit_messages=0,
        )
        self.assertEqual(second_snapshot.remaining_run_tool_evidence_budget_after_call, 6_000)
        self.assertEqual(
            first_snapshot.projected_tool_result_tokens + second_snapshot.projected_tool_result_tokens,
            10_000,
        )

    def test_dynamic_pool_reservation_prevents_over_allocation(self) -> None:
        policy = ToolResultBudgetConfig(mode="dynamic", context_window_tokens=32_000).new_policy()
        first = policy.begin_call()
        with self.assertRaises(ToolResultBudgetExhausted):
            policy.begin_call()
        policy.complete_call(
            first,
            projected_tool_result_tokens=8_000,
            truncated=False,
            omitted_context_messages=0,
            omitted_hit_messages=0,
        )
        with self.assertRaises(ToolResultBudgetExhausted):
            policy.begin_call()

    def test_invalid_projection_metrics_are_rejected(self) -> None:
        policy = ToolResultBudgetConfig(mode="dynamic", context_window_tokens=32_000).new_policy()
        reservation = policy.begin_call()
        with self.assertRaises(ToolResultBudgetError):
            policy.complete_call(
                reservation,
                projected_tool_result_tokens=8_001,
                truncated=False,
                omitted_context_messages=0,
                omitted_hit_messages=0,
            )
        # 非法结算不能吞掉 reservation；修正输入后同一调用仍可原子完成。
        snapshot = policy.complete_call(
            reservation,
            projected_tool_result_tokens=8_000,
            truncated=False,
            omitted_context_messages=0,
            omitted_hit_messages=0,
        )
        self.assertEqual(snapshot.remaining_run_tool_evidence_budget_after_call, 0)


class ToolResultBudgetSettingsTests(unittest.TestCase):
    """验证实验开关从 settings/env 进入 typed 配置，非法值显式失败。"""

    def _environ(self) -> dict[str, str]:
        return {
            "TRIVAE_MODEL_PROVIDER": "deepseek",
            "TRIVAE_MODEL_API_KEY": "test-key",
            "TRIVAE_MODEL_BASE_URL": "https://api.example.test/v1",
            "TRIVAE_MODEL_NAME": "test-model",
        }

    def test_dynamic_settings_are_explicit_and_safe(self) -> None:
        settings = load_settings(
            {
                **self._environ(),
                "TRIVAE_TOOL_RESULT_BUDGET_MODE": "dynamic",
                "TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS": "128000",
                "TRIVAE_PER_CALL_TOOL_RESULT_PERCENT": "50",
                "TRIVAE_PER_CALL_TOOL_RESULT_CAP": "64000",
                "TRIVAE_RUN_TOOL_EVIDENCE_PERCENT": "25",
                "TRIVAE_RUN_TOOL_EVIDENCE_CAP": "256000",
                "TRIVAE_RUN_TOOL_EVIDENCE_BUDGET": "128000",
            }
        )
        self.assertEqual(settings.tool_result_budget_mode, "dynamic")
        self.assertEqual(settings.model_context_window_tokens, 128_000)
        self.assertEqual(settings.per_call_tool_result_percent, DEFAULT_PER_CALL_TOOL_RESULT_PERCENT)
        self.assertEqual(settings.per_call_tool_result_cap, 64_000)
        self.assertEqual(settings.run_tool_evidence_percent, DEFAULT_RUN_TOOL_EVIDENCE_PERCENT)
        self.assertEqual(settings.run_tool_evidence_budget, 128_000)
        self.assertEqual(settings.to_safe_dict()["per_call_tool_result_cap"], 64_000)
        self.assertNotIn("test-key", repr(settings))

    def test_budget_settings_default_to_dynamic_without_context_guess(self) -> None:
        settings = load_settings(self._environ())
        self.assertEqual(settings.tool_result_budget_mode, "dynamic")
        self.assertIsNone(settings.model_context_window_tokens)
        self.assertEqual(settings.per_call_tool_result_percent, DEFAULT_PER_CALL_TOOL_RESULT_PERCENT)
        self.assertEqual(settings.per_call_tool_result_cap, DEFAULT_PER_CALL_TOOL_RESULT_CAP)
        self.assertEqual(settings.run_tool_evidence_percent, DEFAULT_RUN_TOOL_EVIDENCE_PERCENT)
        self.assertEqual(settings.run_tool_evidence_cap, DEFAULT_RUN_TOOL_EVIDENCE_CAP)

    def test_budget_settings_reject_invalid_values(self) -> None:
        cases = (
            {"TRIVAE_TOOL_RESULT_BUDGET_MODE": "guess"},
            {"TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS": ""},
            {"TRIVAE_MODEL_CONTEXT_WINDOW_TOKENS": "32000.0"},
            {"TRIVAE_PER_CALL_TOOL_RESULT_PERCENT": "0"},
            {"TRIVAE_RUN_TOOL_EVIDENCE_PERCENT": "101"},
            {"TRIVAE_PER_CALL_TOOL_RESULT_CAP": "-1"},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(SettingsError):
                    load_settings({**self._environ(), **override})


class ToolResultBudgetProjectionTests(unittest.TestCase):
    """验证 dynamic budget 只影响 model projection，不破坏 canonical record 和 handles。"""

    def test_dynamic_projection_truncates_with_visible_handles_and_complete_canonical_record(self) -> None:
        messages = tuple(
            _message(index, f"resource {index} " + ("long evidence " * 80))
            for index in range(500)
        )
        retrieval = RetrievalResult(
            query=LexicalQuery(keyword="resource", limit=500, context_before=0, context_after=0),
            filters={},
            strategy="lexical",
            hits=tuple(MessageHit(message, ("resource",), 1.0, "test") for message in messages),
            expanded_messages=(),
            total_hits=len(messages),
            returned_messages=len(messages),
            coverage=Coverage("complete", "canonical_plus_lexical_index"),
            partial=False,
            truncated=False,
            metadata=RetrievalMetadata(filters={}, ordering="test", latency_ms=0.0),
        )
        envelope = ToolEnvelope("ok", retrieval, {}, None)
        record = build_tool_result_record(
            run_id="run-budget",
            tool_call_id="run-budget/tool-call/1",
            tool_result_id="run-budget/tool-call/1/result",
            tool_name="lexical_search",
            envelope=envelope,
            scope=ExecutionScope(max_results=500),
        )

        projected = project_tool_result_for_model(envelope, record, token_budget=32_000)
        metrics = projected["model_projection"]
        self.assertTrue(metrics["truncated"])
        self.assertGreater(metrics["omitted_hit_messages"], 0)
        self.assertLessEqual(metrics["estimated_tokens"], 32_000)
        self.assertEqual(len(record.message_items), 500)
        self.assertEqual(
            len(projected["provenance"]["message_sources"]),
            len(projected["data"]["hits"]),
        )


class ToolResultBudgetRuntimeTests(unittest.TestCase):
    """覆盖 Runtime adapter 的实际 reserve → project → complete 主链路。"""

    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.registry.register(_TinySearchTool())
        self.scope = ExecutionScope(max_results=5)

    def test_runtime_uses_dynamic_budget_snapshot(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-1",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            settings=_dynamic_settings(64_000),
        )
        result = asyncio.run(
            runtime.run(AgentRunRequest("find alpha", self.scope, available_capabilities=("search_messages",)))
        )

        snapshot = result.tool_calls[0].tool_result_budget
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.budget_mode, "dynamic")
        self.assertEqual(snapshot.context_window_tokens, 64_000)
        self.assertEqual(snapshot.context_window_source, "explicit_config")
        self.assertEqual(snapshot.run_tool_evidence_budget, 16_000)
        # 控制结果预留与数据投影共享同一个 16k 池，数据 ceiling 应扣除控制预留。
        self.assertLess(snapshot.effective_per_call_tool_result_budget, 16_000)
        self.assertGreater(snapshot.effective_per_call_tool_result_budget, 0)
        self.assertIsInstance(snapshot.projected_tool_result_tokens, int)
        self.assertEqual(
            snapshot.remaining_run_tool_evidence_budget_after_call,
            16_000 - snapshot.projected_tool_result_tokens,
        )

    def test_adapter_uses_verified_registry_for_default_1m_context(self) -> None:
        settings = ModelSettings(
            api_key="",
            base_url="https://example.test/v1",
            provider="opencode-go",
            model_name="deepseek-v4-flash",
            max_turns=6,
            tool_result_budget_mode="dynamic",
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=ScriptedModel([]),
            settings=settings,
        )

        config = runtime._tool_result_budget_config
        self.assertEqual(config.context_window_tokens, 1_000_000)
        self.assertEqual(config.context_window_source, "verified_model_registry")
        self.assertEqual(config.per_call_ceiling, 128_000)
        self.assertEqual(config.run_tool_evidence_budget, 250_000)

    def test_trace_records_verified_registry_context_source(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-verified",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        settings = ModelSettings(
            api_key="",
            base_url="https://example.test/v1",
            provider="opencode-go",
            model_name="deepseek-v4-flash",
            max_turns=6,
            tool_result_budget_mode="dynamic",
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model, settings=settings)
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "trace-verified.sqlite3")
            collector = TraceCollector(
                store,
                trace_id="trace-budget-verified",
                request_id="request-budget-verified",
                profile="debug",
            )
            traced = TraceableAgentRuntime(runtime, collector)
            asyncio.run(
                traced.run(
                    AgentRunRequest(
                        "find alpha",
                        self.scope,
                        available_capabilities=("search_messages",),
                    )
                )
            )
            projection = project_trace(store.read_trace("trace-budget-verified"))
            terminal = next(
                item
                for item in projection.timeline
                if item.operation == "runtime.run" and item.phase == "completed"
            )
            self.assertEqual(terminal.payload["context_window_tokens"], 1_000_000)
            self.assertEqual(terminal.payload["context_window_source"], "verified_model_registry")
            self.assertEqual(terminal.payload["run_tool_evidence_budget"], 250_000)
            store.close()

    def test_trace_records_unknown_context_fallback_source(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-fallback",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            provider_name="unknown-provider",
            model_name="unknown-model",
        )
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "trace-fallback.sqlite3")
            collector = TraceCollector(
                store,
                trace_id="trace-budget-fallback",
                request_id="request-budget-fallback",
                profile="debug",
            )
            traced = TraceableAgentRuntime(runtime, collector)
            asyncio.run(
                traced.run(
                    AgentRunRequest(
                        "find alpha",
                        self.scope,
                        available_capabilities=("search_messages",),
                    )
                )
            )
            projection = project_trace(store.read_trace("trace-budget-fallback"))
            terminal = next(
                item
                for item in projection.timeline
                if item.operation == "runtime.run" and item.phase == "completed"
            )
            self.assertIsNone(terminal.payload["context_window_tokens"])
            self.assertEqual(terminal.payload["context_window_source"], "fallback")
            self.assertEqual(terminal.payload["run_tool_evidence_budget"], 16_000)
            store.close()

    def test_runtime_multiple_tool_calls_share_one_run_pool(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-1",
                        )
                    ]
                ),
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "beta", "limit": 5},
                            call_id="budget-call-2",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            settings=_dynamic_settings(64_000),
        )
        result = asyncio.run(
            runtime.run(AgentRunRequest("find messages", self.scope, available_capabilities=("search_messages",)))
        )

        snapshots = [call.tool_result_budget for call in result.tool_calls]
        self.assertEqual(len(snapshots), 2)
        first, second = snapshots
        assert first is not None
        assert second is not None
        self.assertEqual(first.run_tool_evidence_budget, second.run_tool_evidence_budget)
        # 下一调用已预留控制结果，所以可分配余额小于上一调用结算余额。
        self.assertLess(second.remaining_run_tool_evidence_budget_before_call, first.remaining_run_tool_evidence_budget_after_call)
        self.assertEqual(
            second.remaining_run_tool_evidence_budget_after_call,
            16_000 - first.projected_tool_result_tokens - second.projected_tool_result_tokens,
        )
        self.assertGreaterEqual(second.remaining_run_tool_evidence_budget_after_call, 0)

    def test_evaluation_exposes_budget_facts_without_quality_label(self) -> None:
        """Evaluation 只读取 Runtime budget snapshot，不把 truncation 改写成质量结论。"""

        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-eval",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            settings=_dynamic_settings(64_000),
        )
        runtime_result = asyncio.run(
            runtime.run(AgentRunRequest("find alpha", self.scope, available_capabilities=("search_messages",)))
        )
        query_result = QueryResult(
            runtime_result=runtime_result,
            route_decision=RouteDecision("standard_execution", 1.0, "rule", "test"),
        )

        measurements = operational_measurements(query_result, None)
        budget_facts = measurements["tool_result_budget"]
        self.assertIsInstance(budget_facts, tuple)
        assert isinstance(budget_facts, tuple)
        self.assertEqual(len(budget_facts), 1)
        self.assertEqual(budget_facts[0]["run_tool_evidence_budget"], 16_000)
        self.assertEqual(budget_facts[0]["budget_mode"], "dynamic")
        self.assertNotIn("quality", budget_facts[0])

    def test_trace_persists_per_call_and_terminal_budget_facts(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="budget-call-trace",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(
            self.registry,
            model=model,
            settings=_dynamic_settings(128_000),
        )
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteTraceStore(Path(directory) / "trace.sqlite3")
            collector = TraceCollector(
                store,
                trace_id="trace-budget",
                request_id="request-budget",
                profile="debug",
            )
            traced = TraceableAgentRuntime(runtime, collector)
            result = asyncio.run(
                traced.run(
                    AgentRunRequest(
                        "find alpha",
                        self.scope,
                        available_capabilities=("search_messages",),
                    )
                )
            )
            self.assertEqual(result.termination, "completed")
            projection = project_trace(store.read_trace("trace-budget"))
            completed_tool = next(
                item for item in projection.timeline if item.operation == "runtime.tool.completed"
            )
            budget = completed_tool.payload["tool_result_budget"]
            self.assertEqual(budget["budget_mode"], "dynamic")
            self.assertEqual(budget["context_window_tokens"], 128_000)
            self.assertEqual(budget["run_tool_evidence_budget"], 32_000)
            terminal = next(
                item
                for item in projection.timeline
                if item.operation == "runtime.run" and item.phase == "completed"
            )
            self.assertEqual(terminal.payload["budget_mode"], "dynamic")
            self.assertEqual(terminal.payload["context_window_source"], "explicit_config")
            self.assertEqual(terminal.payload["tool_result_budget_call_count"], 1)
            store.close()


if __name__ == "__main__":
    unittest.main()
