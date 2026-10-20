"""P01 lexical limit：非法输入须拒绝，不能只依赖 Schema 的样子。"""

from __future__ import annotations

import asyncio
import json
import runpy
from pathlib import Path

import pytest
from agents.exceptions import ModelBehaviorError
from agents.tool_context import ToolContext

from tests import test_stage_b_tools as fixtures
from trivae.capabilities import ExecutionScope
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import LexicalSearchSDKToolAdapter, SearchMessagesSDKToolAdapter

# 原实验候选必须对照当时冻结的生产基线（8def8d7），避免后续策略演进改写历史比较。
HISTORICAL_PROMPT = runpy.run_path(str(Path(__file__).parent / "fixtures/prompt-policy-audit-baseline.py"))[
    "SYSTEM_PROMPT"
]

REMOVED_LIMIT_RULE = (
    "limit must be a positive integer no greater than the trusted result limit\n"
    "shown by the tool schema, and "
)
CANDIDATE_PATH = Path(__file__).parents[1] / ".trellis/tasks/10-05-prompt-policy-audit/research/prompt-p01.txt"


@pytest.fixture
def limit_tool(monkeypatch):
    """真实 application registry；无效输入必须在 retrieval 之前失败。"""
    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    fixture.application.rebuild_lexical_index()
    app = fixture.application
    called = []
    original = app.lexical_retrieval.search

    def track(query):
        called.append(query)
        return original(query)
    monkeypatch.setattr(app.lexical_retrieval, "search", track)
    context = RuntimeContext(scope=ExecutionScope(max_results=5), capability_registry=app.capability_registry,
                             available_capabilities=("lexical_search", "search_messages"), run_id="limit-contract")
    wrapper = ToolContext(context=context, tool_name="lexical_search", tool_call_id="limit", tool_arguments="{}")
    try:
        yield app.capability_registry, context, wrapper, called
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("adapter", [LexicalSearchSDKToolAdapter, SearchMessagesSDKToolAdapter])
@pytest.mark.parametrize("value", [True, "2", 2.0, 1.5, 0, -1])
def test_sdk_rejects_invalid_limit_without_retrieval(limit_tool, adapter, value):
    """SDK 不能先把bool/string/float转成合法int；主契约在执行前拒绝。"""
    registry, context, wrapper, called = limit_tool
    tool = adapter(registry).as_sdk_tool(trusted_max_results=5)
    context.allocate_tool_call_id("invalid")
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"keyword": "anchor", "limit": value})))
    assert called == []


@pytest.mark.parametrize("adapter", [LexicalSearchSDKToolAdapter, SearchMessagesSDKToolAdapter])
def test_host_rejects_limit_above_schema_maximum_without_retrieval(limit_tool, adapter):
    """JSON Schema maximum本身不执行：Host Capability必须仍拒绝模型越上限。"""
    registry, context, wrapper, called = limit_tool
    tool = adapter(registry).as_sdk_tool(trusted_max_results=5)
    schema = tool.params_json_schema["properties"]["limit"]
    assert schema["type"] == "integer" and schema["minimum"] == 1 and schema["maximum"] == 5
    context.allocate_tool_call_id("above")
    response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"keyword": "anchor", "limit": 6})))
    assert response["status"] == "error"
    assert response["error"]["code"] == "INVALID_ARGUMENT"
    assert called == []


@pytest.mark.parametrize("value", [1, 5])
def test_valid_limit_boundaries_keep_actual_retrieval(limit_tool, value):
    """合法边界继续走原retrieval，不改变limit默认或清单选择语义。"""
    registry, context, wrapper, called = limit_tool
    tool = LexicalSearchSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=5)
    context.allocate_tool_call_id("valid")
    response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"keyword": "anchor", "limit": value})))
    assert response["status"] == "ok"
    assert len(called) == 1 and called[0].limit == value
    assert "For an explicit broad inventory" in tool.description


def test_candidate_is_exactly_one_parameter_fragment_removal():
    """整串相等比保护子段更强：所有非目标文字、顺序和空白都不变。"""
    assert HISTORICAL_PROMPT.count(REMOVED_LIMIT_RULE) == 1
    assert CANDIDATE_PATH.read_text() == HISTORICAL_PROMPT.replace(REMOVED_LIMIT_RULE, "", 1)
