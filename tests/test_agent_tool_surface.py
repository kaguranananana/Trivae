from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from trivae.bootstrap.application import create_application
from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope
from trivae.observability.collector import TraceCollector
from trivae.observability.projection import project_trace
from trivae.query.contracts import QueryRequest
from trivae.query.runtime.contracts import AgentRunRequest
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT


class _RecordingTool:
    """测试两个独立 retrieval Tool 是否共享同一个 Runtime 调用链。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[object, ExecutionScope]] = []

    def invoke(self, request: object, scope: ExecutionScope) -> ToolEnvelope:
        # Tool 只返回最小 envelope；测试重点是名称、顺序、scope 和 Tool Result identity。
        self.calls.append((request, scope))
        return ToolEnvelope(status="ok", data=None, meta={"truncated": False}, error=None)


class AgentToolSurfaceTests(unittest.TestCase):
    """验证 Stage A 的默认 surface、selection guidance 和同一 Runtime 的多 Tool 行为。"""

    def test_query_default_exposes_dual_retrieval_and_legacy_is_explicit(self) -> None:
        scope = ExecutionScope(max_results=5)
        request = QueryRequest("谁提到过 sqlite-vec？", scope)
        self.assertEqual(
            request.available_capabilities,
            (
                "lexical_search",
                "semantic_search",
                "get_recent_messages",
                "get_message_context",
                "find_members",
                "get_schema",
                "execute_sql",
            ),
        )

        legacy = QueryRequest(
            "legacy caller",
            scope,
            available_capabilities=("search_messages",),
        )
        self.assertEqual(legacy.available_capabilities, ("search_messages",))

    def test_visible_tool_descriptions_guide_selection_without_legacy_tool(self) -> None:
        registry = CapabilityRegistry()
        registry.register(_RecordingTool("lexical_search"))
        registry.register(_RecordingTool("semantic_search"))
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]))
        request = AgentRunRequest(
            "之前是否讨论过 Agent 框架太重？",
            ExecutionScope(max_results=5),
            available_capabilities=("lexical_search", "semantic_search"),
        )

        agent = runtime._build_agent(request, runtime._build_context(request), object())
        tools = {tool.name: tool for tool in agent.tools}

        self.assertEqual(set(tools), {"lexical_search", "semantic_search"})
        self.assertIn("exact lexical matching", tools["lexical_search"].description)
        self.assertIn("Normally call this first", tools["lexical_search"].description)
        self.assertIn("Do not call both just to hedge", tools["lexical_search"].description)
        self.assertIn("after no hits", tools["lexical_search"].description)
        self.assertIn("multi-query expansion", tools["lexical_search"].description)
        self.assertIn("semantic_search", tools["lexical_search"].description)
        self.assertIn("canonical user_id", tools["lexical_search"].description)
        self.assertIn("wording differs", tools["semantic_search"].description)
        self.assertIn("Normally call this first", tools["semantic_search"].description)
        self.assertIn("Do not call both just to hedge", tools["semantic_search"].description)
        self.assertIn("after no hits", tools["semantic_search"].description)
        self.assertIn("multi-query expansion", tools["semantic_search"].description)
        self.assertIn("lexical_search", tools["semantic_search"].description)
        self.assertIn("canonical user_id", tools["semantic_search"].description)
        self.assertIn("lexical_search", SYSTEM_PROMPT)
        self.assertIn("semantic_search", SYSTEM_PROMPT)
        self.assertIn("Normally make lexical_search the first retrieval call", SYSTEM_PROMPT)
        self.assertIn("Do not call the other", SYSTEM_PROMPT)
        self.assertIn("Do not repeat the same retrieval tool", SYSTEM_PROMPT)
        self.assertIn("multi-query expansion loop", SYSTEM_PROMPT)
        self.assertIn("do not silently", SYSTEM_PROMPT)
        self.assertIn("find_members.candidates[]", SYSTEM_PROMPT)
        self.assertIn("never compare `messages.sender_user_id` directly to a QQ UIN", SYSTEM_PROMPT)

    def test_shared_runtime_keeps_named_entity_and_follow_up_context_anchors(self) -> None:
        """Planner 仅给软指导；Runtime 对 Standard 与 Planned 共用实体及上下文锚点规则。"""

        registry = CapabilityRegistry()
        registry.register(_RecordingTool("lexical_search"))
        registry.register(_RecordingTool("get_message_context"))
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]))
        request = AgentRunRequest(
            "Investigate the named resource and its later user feedback",
            ExecutionScope(max_results=5),
            available_capabilities=("lexical_search", "get_message_context"),
            plan_guidance=(
                "Soft plan guidance only; inspect the named resource and the discussion that follows."
            ),
        )

        agent = runtime._build_agent(
            request,
            runtime._build_context(request),
            # 用与生产 state 相同的预算字段，验证动态 instructions 的初始事实。
            SimpleNamespace(finalizing=False, tool_rounds=0),
        )
        instructions = agent.instructions
        self.assertTrue(callable(instructions))
        runtime_prompt = instructions(None, agent)

        self.assertIn("Plan tool suggestions and step wording are guidance", runtime_prompt)
        self.assertIn("retain its most discriminative name", runtime_prompt)
        self.assertIn("do not replace it with a generic category word alone", runtime_prompt)
        self.assertIn("use `get_message_context`", runtime_prompt)
        self.assertIn("that best anchors that discussion", runtime_prompt)
        self.assertIn("distinct requested evidence need remains uncovered", runtime_prompt)
        self.assertIn("Soft plan guidance only; inspect the named resource", runtime_prompt)
        self.assertIn("0 consumed, 3 remaining", runtime_prompt)
        self.assertIn("Multiple tool calls from one model turn consume one round", runtime_prompt)

    def test_context_tool_schema_explains_message_count_units(self) -> None:
        """get_message_context 的 before/after 必须明确是消息条数而不是时间。"""

        registry = CapabilityRegistry()
        registry.register(_RecordingTool("get_message_context"))
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]))
        request = AgentRunRequest(
            "检查问题后续回复",
            ExecutionScope(max_results=5),
            available_capabilities=("get_message_context",),
        )

        agent = runtime._build_agent(request, runtime._build_context(request), object())
        schema = agent.tools[0].params_json_schema
        properties = schema["properties"]
        self.assertIn("message count", properties["context_before"]["description"])
        self.assertIn("message count", properties["context_after"]["description"])
        self.assertIn("minutes or seconds", properties["context_after"]["description"])
        self.assertEqual(properties["context_before"]["default"], 8)
        self.assertEqual(properties["context_after"]["default"], 8)

    def test_resource_inventory_guidance_separates_url_and_non_url_evidence(self) -> None:
        """资源清单的 URL 与非 URL 证据走不同检索路径，不回退到宽泛 recent/SQL。"""

        registry = CapabilityRegistry()
        for name in ("lexical_search", "semantic_search", "get_recent_messages", "execute_sql"):
            registry.register(_RecordingTool(name))
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]))
        request = AgentRunRequest(
            "最近有哪些 Agent 学习资源？",
            ExecutionScope(max_results=100),
            available_capabilities=("lexical_search", "semantic_search", "get_recent_messages", "execute_sql"),
        )

        agent = runtime._build_agent(request, runtime._build_context(request), object())
        tools = {tool.name: tool for tool in agent.tools}

        self.assertIn("non-empty github.com result is sufficient for URL-bearing recall", tools["lexical_search"].description)
        self.assertIn("one semantic_search for non-URL materials", tools["lexical_search"].description)
        self.assertIn("must not prefetch a broad recent window", tools["lexical_search"].description)
        self.assertIn("resource inventory", tools["get_recent_messages"].description)
        self.assertIn("get_recent_messages or execute_sql merely", SYSTEM_PROMPT)
        self.assertIn("semantic_search may add that distinct conceptual evidence", SYSTEM_PROMPT)
        self.assertIn("Never use this tool to recount URL/resource retrieval results", tools["execute_sql"].description)
        self.assertIn("do not repeat the same or a near-identical statement", tools["execute_sql"].description)
        self.assertIn("near-identical SQL statement again", SYSTEM_PROMPT)

    def test_temporal_selection_boundary_is_declared(self) -> None:
        """B6：temporal overview 必须由 description+prompt 引导优先 get_recent_messages。"""

        registry = CapabilityRegistry()
        registry.register(_RecordingTool("get_recent_messages"))
        registry.register(_RecordingTool("lexical_search"))
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=ScriptedModel([]))
        request = AgentRunRequest(
            "最近一两天大家都在聊什么？",
            ExecutionScope(max_results=100),
            available_capabilities=("get_recent_messages", "lexical_search"),
        )
        agent = runtime._build_agent(request, runtime._build_context(request), object())
        recent = {tool.name: tool for tool in agent.tools}["get_recent_messages"]
        # description 绑定 question shape，而不是关键词匹配；空参默认语义必须写明。
        self.assertIn("temporal browsing", recent.description)
        self.assertIn(
            "Do NOT guess topics and search them with lexical_search or semantic_search",
            recent.description,
        )
        self.assertIn(
            "without any time argument defaults to the most recent 2 days anchored at archive_latest",
            recent.description,
        )
        self.assertIn("Zero results is a normal outcome", recent.description)
        self.assertIn("sender_user_ids", recent.description)
        self.assertIn("what one person recently discussed", recent.description)
        self.assertIn("resource inventory", recent.description)
        self.assertIn("instead of prefetching this broad recent window", recent.description)
        # prompt 层 tool selection boundary 与 zero-result 出口同样被锁定。
        self.assertIn(
            "Use get_recent_messages when the candidate set is determined mainly by time",
            SYSTEM_PROMPT,
        )
        self.assertIn('{"kind": "no_result"', SYSTEM_PROMPT)
        self.assertIn("An SQL COUNT alone cannot establish the complete empty retrieval proof", SYSTEM_PROMPT)
        self.assertIn("otherwise finalization fails", SYSTEM_PROMPT)
        self.assertIn("canonical `user_id` in `sender_user_ids`", SYSTEM_PROMPT)
        self.assertIn("topic-wide recent overview", SYSTEM_PROMPT)
        self.assertIn("resource inventories", SYSTEM_PROMPT)
        self.assertIn('"github.com" the FIRST retrieval call', SYSTEM_PROMPT)

    def test_agent_can_continue_from_lexical_to_semantic_in_one_runtime(self) -> None:
        lexical = _RecordingTool("lexical_search")
        semantic = _RecordingTool("semantic_search")
        registry = CapabilityRegistry()
        registry.register(lexical)
        registry.register(semantic)
        model = ScriptedModel(
            [
                ModelStep(
                    output=[
                        function_call(
                            "lexical_search",
                            {"keyword": "sqlite-vec", "limit": 2},
                            call_id="lexical-call",
                        )
                    ]
                ),
                ModelStep(
                    output=[
                        function_call(
                            "semantic_search",
                            {"query": "讨论 Agent 框架过重", "limit": 2},
                            call_id="semantic-call",
                        )
                    ]
                ),
                ModelStep(output=[assistant_message("继续调查后得到的结果")]),
            ]
        )
        runtime = OpenAIAgentsRuntimeAdapter(registry, model=model, max_turns=4)
        request = AgentRunRequest(
            "先查明确术语，再查可能的语义讨论",
            ExecutionScope(max_results=2),
            available_capabilities=("lexical_search", "semantic_search"),
            request_id="stage-a-multi-tool",
        )

        result = asyncio.run(runtime.run(request))

        self.assertEqual(result.termination, "completed")
        self.assertEqual([call.name for call in result.tool_calls], ["lexical_search", "semantic_search"])
        self.assertEqual(len(result.tool_results), 2)
        self.assertEqual({record.run_id for record in result.tool_results}, {result.run_id})
        self.assertEqual(
            [record.tool_name for record in result.tool_results],
            ["lexical_search", "semantic_search"],
        )
        self.assertIs(lexical.calls[0][1], semantic.calls[0][1])

    def test_trace_keeps_selected_tools_and_explicit_semantic_failure(self) -> None:
        """真实 Capability registry 的 Trace 能区分两次选择和 semantic unavailable。"""

        with tempfile.TemporaryDirectory() as directory:
            application = create_application(Path(directory) / "trace.sqlite3")
            try:
                # 测试只关注 semantic unavailable；lexical 的 derived index 前置条件显式建立。
                application.rebuild_lexical_index()
                collector = TraceCollector(
                    application._trace_store,
                    trace_id="trace-stage-a",
                    request_id="request-stage-a",
                )
                model = ScriptedModel(
                    [
                        ModelStep(
                            output=[
                                function_call(
                                    "lexical_search",
                                    {"keyword": "sqlite-vec", "limit": 2},
                                    call_id="lexical-call",
                                )
                            ]
                        ),
                        ModelStep(
                            output=[
                                function_call(
                                    "semantic_search",
                                    {"query": "讨论 Agent 框架过重", "limit": 2},
                                    call_id="semantic-call",
                                )
                            ]
                        ),
                        ModelStep(output=[assistant_message("没有可用的语义索引证据")]),
                    ]
                )
                runtime = OpenAIAgentsRuntimeAdapter(
                    application.capability_registry,
                    model=model,
                    max_turns=4,
                )
                result = asyncio.run(
                    runtime.run(
                        AgentRunRequest(
                            "先查术语，再调查语义讨论",
                            ExecutionScope(max_results=2),
                            available_capabilities=("lexical_search", "semantic_search"),
                            trace_context=collector.operation_context("query"),
                        )
                    )
                )
                projection = project_trace(application._trace_store.read_trace("trace-stage-a"))
            finally:
                application.close()

        tool_events = [item for item in projection.timeline if item.stage == "tool"]
        started = [item for item in tool_events if item.operation == "tool.call.started"]
        completed = [item for item in tool_events if item.operation == "tool.call.completed"]
        failed = [item for item in tool_events if item.operation == "tool.call.failed"]
        self.assertEqual(result.termination, "completed")
        self.assertEqual([item.payload["tool_name"] for item in started], ["lexical_search", "semantic_search"])
        self.assertEqual([item.payload["tool_name"] for item in completed], ["lexical_search"])
        self.assertEqual([item.payload["tool_name"] for item in failed], ["semantic_search"])
        self.assertEqual(failed[0].payload["error_code"], "SEMANTIC_INDEX_NOT_READY")


if __name__ == "__main__":
    unittest.main()
