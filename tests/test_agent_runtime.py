from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope, ToolError
from trivae.config.settings import DEFAULT_DEEPSEEK_BASE_URL, SettingsError, load_settings
from trivae.query.runtime.contracts import AgentRunRequest, AgentRuntimeContractError, RuntimeEvent
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter, _RuntimeHooks
from trivae.query.runtime.prompt import SYSTEM_PROMPT


class _RecordingSearchTool:
    """仅用于验证 SDK 工具把 typed input 和 trusted scope 原样交给 registry。"""

    name = "search_messages"

    def __init__(self) -> None:
        self.requests: list[tuple[object, ExecutionScope]] = []

    def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
        self.requests.append((request, scope))
        return ToolEnvelope("ok", None, {"truncated": False}, None)


async def _collect_runtime_events(
    runtime: OpenAIAgentsRuntimeAdapter,
    request: AgentRunRequest,
) -> list[RuntimeEvent]:
    """完整消费 Runtime stream，确保 hook 事件已经进入可断言的顺序。"""

    return [event async for event in runtime.stream(request)]


class SettingsTests(unittest.TestCase):
    """配置读取必须有默认值、明确校验和 secret-safe 投影。"""

    def test_load_settings_defaults_and_redacts_key(self) -> None:
        settings = load_settings(
            {
                "DEEPSEEK_API_KEY": "test-secret-value",
                "TRIVAE_MODEL_NAME": "deepseek-chat-test",
            }
        )

        self.assertEqual(settings.base_url, DEFAULT_DEEPSEEK_BASE_URL)
        self.assertEqual(settings.provider, "deepseek")
        self.assertEqual(settings.max_turns, 8)
        self.assertEqual(settings.max_output_tokens, 16384)
        self.assertEqual(settings.completion_max_tokens, 2048)
        self.assertNotIn("test-secret-value", repr(settings))
        self.assertNotIn("test-secret-value", str(settings.to_safe_dict()))
        self.assertTrue(settings.to_safe_dict()["api_key_configured"])

    def test_load_settings_rejects_missing_required_values_and_provider(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings({"TRIVAE_MODEL_NAME": "deepseek-chat-test"})
        with self.assertRaises(SettingsError):
            load_settings({"DEEPSEEK_API_KEY": "secret"})
        with self.assertRaises(SettingsError):
            load_settings(
                {
                    "DEEPSEEK_API_KEY": "secret",
                    "TRIVAE_MODEL_NAME": "model",
                    "TRIVAE_MODEL_PROVIDER": "other",
                }
            )

    def test_load_settings_rejects_invalid_provider_budgets(self) -> None:
        base = {
            "DEEPSEEK_API_KEY": "secret",
            "TRIVAE_MODEL_NAME": "model",
        }
        for name in ("TRIVAE_MAX_OUTPUT_TOKENS", "TRIVAE_COMPLETION_MAX_TOKENS"):
            with self.subTest(name=name):
                values = {**base, name: "0"}
                with self.assertRaises(SettingsError):
                    load_settings(values)


class RuntimeAdapterTests(unittest.TestCase):
    """用 SDK ScriptedModel 验证真实 tool pipeline 和 max_turns 边界。"""

    def setUp(self) -> None:
        self.registry = CapabilityRegistry()
        self.tool = _RecordingSearchTool()
        self.registry.register(self.tool)
        self.scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)

    def test_runtime_request_rejects_invalid_scope_and_capability_container(self) -> None:
        with self.assertRaises(AgentRuntimeContractError):
            AgentRunRequest("query", None, ("search_messages",))
        with self.assertRaises(AgentRuntimeContractError):
            AgentRunRequest("query", self.scope, None)

    def test_deepseek_chat_completions_model_is_constructed_without_network(self) -> None:
        settings = load_settings(
            {
                "DEEPSEEK_API_KEY": "test-secret-value",
                "TRIVAE_MODEL_NAME": "deepseek-chat-test",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            }
        )

        # 只验证 provider client/model 的构造边界；构造阶段不能发起真实网络请求。
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, settings=settings, max_turns=3)

        self.assertIsInstance(runtime._model, OpenAIChatCompletionsModel)
        self.assertEqual(runtime._provider_name, "deepseek")
        self.assertEqual(runtime._model_name, "deepseek-chat-test")
        self.assertEqual(runtime.max_turns, 3)

    def test_agent_requests_provider_json_mode_for_final_synthesis(self) -> None:
        """验证 final synthesis 使用 provider JSON mode，而不是依赖裸 prompt。"""

        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=ScriptedModel([]))
        request = AgentRunRequest("What supports alpha?", self.scope)
        context = runtime._build_context(request)
        agent = runtime._build_agent(request, context, object())

        self.assertEqual(
            agent.model_settings.extra_args["response_format"],
            {"type": "json_object"},
        )
        self.assertEqual(agent.model_settings.max_tokens, 16384)

    def test_final_synthesis_prompt_requests_compact_artifact(self) -> None:
        self.assertIn("Keep the JSON artifact compact", SYSTEM_PROMPT)
        self.assertIn("Do not repeat the same", SYSTEM_PROMPT)

    def test_provider_completion_uses_json_mode_and_explicit_budget(self) -> None:
        """Router/Planner completion 必须走 provider JSON contract 和有界预算。"""

        class RecordingCompletions:
            def __init__(self) -> None:
                self.kwargs: dict[str, object] | None = None

            async def create(self, **kwargs: object) -> object:
                self.kwargs = kwargs
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))]
                )

        completions = RecordingCompletions()
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=ScriptedModel([]))
        runtime._provider_client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )

        result = asyncio.run(runtime.complete_text("return a JSON object"))

        self.assertEqual(result, '{"ok":true}')
        assert completions.kwargs is not None
        self.assertEqual(completions.kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(completions.kwargs["max_tokens"], 2048)

    def test_search_tool_schema_exposes_trusted_result_bound(self) -> None:
        """验证 provider schema 暴露本次 trusted result bound，但仍保留 Capability 校验。"""

        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=ScriptedModel([]))
        request = AgentRunRequest("find alpha", self.scope)
        context = runtime._build_context(request)
        agent = runtime._build_agent(request, context, object())

        tool = agent.tools[0]
        limit_schema = tool.params_json_schema["properties"]["limit"]
        self.assertFalse(tool.strict_json_schema)
        self.assertEqual(limit_schema["minimum"], 1)
        self.assertEqual(limit_schema["maximum"], 5)
        self.assertEqual(limit_schema["default"], 5)
        self.assertIn("keyword must be exactly one non-empty string", tool.description)
        self.assertIn("empty arrays", tool.description)
        self.assertIn("trusted result limit", tool.description)

    def test_scripted_model_runs_tool_then_final_answer(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="call-1",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("The messages support alpha.")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model, max_turns=4)

        result = asyncio.run(
            runtime.run(
                AgentRunRequest(
                    query="What supports alpha?",
                    scope=self.scope,
                    available_capabilities=("search_messages",),
                )
            )
        )

        self.assertEqual(result.termination, "completed")
        self.assertEqual(result.final_answer, "The messages support alpha.")
        self.assertEqual(result.tool_count, 1)
        self.assertEqual(result.tool_calls[0].status, "ok")
        self.assertEqual(self.tool.requests[0][1], self.scope)
        self.assertEqual(self.tool.requests[0][0].keyword, "alpha")
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(len(model.calls[0].tools), 1)
        self.assertNotIn("qq:100", str(model.calls[0].input))

    def test_model_visible_projector_keeps_tool_items_and_omits_reasoning(self) -> None:
        """模型输入投影保留真实 tool item，但不复制 hidden reasoning/SDK 字段。"""

        class TypedToolResult:
            """模拟 SDK typed input item；adapter 只读取公开 model_dump。"""

            type = "function_call_output"

            def model_dump(self, **_: object) -> dict[str, object]:
                return {
                    "type": "function_call_output",
                    "call_id": "call-typed",
                    "output": "typed result",
                    "internal_sdk_field": "must not be copied",
                }

        projected = _RuntimeHooks._project_model_visible_context(
            "system prompt",
            [
                {"role": "user", "content": "question"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "previous answer"}],
                    "id": "sdk-message-id",
                },
                {
                    "type": "function_call",
                    "name": "search_messages",
                    "arguments": '{"keyword":"alpha"}',
                    "call_id": "call-1",
                    "id": "sdk-call-id",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "actual tool result",
                },
                {"type": "reasoning", "summary": [{"text": "hidden reasoning"}]},
                TypedToolResult(),
            ],
        )

        assert projected is not None
        self.assertEqual(projected[0], {"role": "system", "content": "system prompt"})
        self.assertEqual(projected[1], {"role": "user", "content": "question"})
        self.assertEqual(projected[2], {"role": "assistant", "content": [{"type": "output_text", "text": "previous answer"}]})
        self.assertEqual(projected[3]["type"], "function_call")
        self.assertEqual(projected[4]["output"], "actual tool result")
        self.assertEqual(projected[5]["output"], "typed result")
        serialized = str(projected)
        self.assertNotIn("hidden reasoning", serialized)
        self.assertNotIn("sdk-message-id", serialized)
        self.assertNotIn("internal_sdk_field", serialized)

    def test_runtime_trace_captures_next_turn_model_input_exact_tool_result(self) -> None:
        """下一轮 input 的 function_call_output 必须和 SDK model call 收到的内容一致。"""

        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "limit": 5},
                            call_id="call-visible",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("answer")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model, max_turns=4)
        events = asyncio.run(
            _collect_runtime_events(
                runtime,
                AgentRunRequest("question", self.scope),
            )
        )

        turn_started = [event for event in events if event.type == "turn_started"]
        self.assertEqual(len(turn_started), 2)
        first_context = turn_started[0].model_visible_context
        second_context = turn_started[1].model_visible_context
        assert first_context is not None
        assert second_context is not None
        self.assertEqual(first_context[0]["role"], "system")
        self.assertEqual(first_context[1], {"role": "user", "content": "question"})

        second_result = next(
            item for item in second_context if item.get("type") == "function_call_output"
        )
        actual_model_input_result = next(
            item for item in model.calls[1].input if item.get("type") == "function_call_output"
        )
        self.assertEqual(second_result["output"], actual_model_input_result["output"])
        self.assertIsInstance(second_result["output_projection"], dict)
        self.assertEqual(
            next(item for item in second_context if item.get("type") == "function_call")["arguments"],
            '{"keyword":"alpha","limit":5}',
        )

        model_outputs = [event for event in events if event.type == "model_output"]
        self.assertEqual(model_outputs[0].observable_output[0]["type"], "function_call")
        self.assertEqual(model_outputs[-1].observable_output[0]["content"], [{"type": "output_text", "text": "answer"}])
        self.assertNotIn("reasoning", str(second_context).lower())

    def test_scope_violation_is_explicit_tool_result(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "search_messages",
                            {"keyword": "alpha", "session_ids": ["qq:200"]},
                            call_id="call-1",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("The requested session is outside the scope.")]),
            ]
        )

        class ScopeTool:
            name = "search_messages"

            def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
                return ToolEnvelope(
                    "error",
                    None,
                    {"truncated": False},
                    error=ToolError("SCOPE_VIOLATION", "requested session is outside trusted data access scope"),
                )

        registry = CapabilityRegistry()
        registry.register(ScopeTool())
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, max_turns=4)
        result = asyncio.run(runtime.run(AgentRunRequest("find alpha", self.scope)))

        self.assertEqual(result.termination, "completed")
        self.assertEqual(result.tool_calls[0].error_code, "SCOPE_VIOLATION")

    def test_sdk_max_turns_is_visible_terminal_result(self) -> None:
        model = ScriptedModel(
            [
                ModelStep(output=[function_call("search_messages", {"keyword": "alpha"}, call_id="call-1")]),
                ModelStep(output=[function_call("search_messages", {"keyword": "alpha"}, call_id="call-2")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(self.registry, model=model, max_turns=2)

        result = asyncio.run(runtime.run(AgentRunRequest("keep searching", self.scope)))

        self.assertEqual(result.termination, "max_turns_exceeded")
        self.assertEqual(result.error.code, "MAX_TURNS_EXCEEDED")
        self.assertEqual(result.tool_count, 2)

    def test_unclassified_tool_exception_is_terminal(self) -> None:
        class ExplodingTool:
            name = "search_messages"

            def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
                raise RuntimeError("retrieval invariant failed")

        registry = CapabilityRegistry()
        registry.register(ExplodingTool())
        model = ScriptedModel(
            [ModelStep(output=[function_call("search_messages", {"keyword": "alpha"}, call_id="call-1")])]
        )
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, max_turns=2)

        result = asyncio.run(runtime.run(AgentRunRequest("query", self.scope)))

        self.assertEqual(result.termination, "failed")
        self.assertEqual(result.error.code, "RUNTIME_ERROR")
        self.assertEqual(result.tool_calls[0].status, "failed")


class ApplicationRuntimeIntegrationTests(unittest.TestCase):
    """验证 Application 惰性 composition 与 SQLite → capability → SDK 全链路。"""

    def test_application_injected_runtime_preserves_retrieval_only_construction(self) -> None:
        with self.subTest("construction_without_provider"):
            with self._temporary_application() as application:
                self.assertIsNotNone(application.capability_registry)

    def test_sqlite_retrieval_reaches_sdk_tool_and_final_answer(self) -> None:
        with self._temporary_application() as application:
            model = ScriptedModel(
                [
                    ModelStep(
                        output=[
                            function_call(
                                "search_messages",
                                {"keyword": "alpha", "limit": 5},
                                call_id="call-1",
                            )
                        ]
                    ),
                    ModelStep(output=[assistant_message("Alpha was found in the messages.")]),
                ]
            )
            runtime = OpenAIAgentsRuntimeAdapter(
                application.capability_registry,
                model=model,
                max_turns=4,
            )
            application._agent_runtime = runtime
            result = asyncio.run(
                application.run_agent(
                    AgentRunRequest(
                        "Where is alpha?",
                        ExecutionScope(allowed_session_ids=("qq:100",), max_results=5),
                    )
                )
            )

            self.assertEqual(result.final_answer, "Alpha was found in the messages.")
            self.assertEqual(result.tool_calls[0].status, "ok")
            self.assertEqual(result.tool_calls[0].name, "search_messages")

    def _temporary_application(self) -> object:
        """构造已导入且已建 lexical index 的小型 SQLite application。"""

        import tempfile

        directory = Path(tempfile.mkdtemp())
        raw = directory / "raw"
        raw.mkdir()
        write_export(
            raw,
            "runtime(100).json",
            [make_message("m1", 1, 1_768_435_200_000, "alpha message")],
            chat_name="Runtime",
            peer_uid=None,
            version="5.5.64",
        )
        application = create_application(directory / "runtime.sqlite3")
        application.import_directory(raw)
        application.rebuild_lexical_index()
        return _ApplicationContext(application, directory)


class _ApplicationContext:
    """测试专用 context manager，确保临时目录和 Application lifecycle 都释放。"""

    def __init__(self, application: object, directory: Path) -> None:
        self.application = application
        self.directory = directory

    def __enter__(self) -> object:
        return self.application

    def __exit__(self, *_: object) -> None:
        self.application.close()
        import shutil

        shutil.rmtree(self.directory)
