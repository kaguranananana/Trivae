"""逐轮验证真实SDK参数边界与累计候选；所有Provider成本为零。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents.exceptions import ModelBehaviorError
from agents.tool_context import ToolContext

from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import ToolEnvelope
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import LexicalSearchSDKToolAdapter, SearchMessagesSDKToolAdapter
from trivae.query.runtime.prompt import SYSTEM_PROMPT

TASK = Path(__file__).parents[1] / ".trellis/tasks/10-05-prompt-policy-audit"


class RecordingHandler:
    """仅记录到达registry的typed request，不创建网络、检索或第二套Agent。"""

    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, request, scope):
        self.calls.append(request)
        return ToolEnvelope(status="ok", data=None, meta={"truncated": False}, error=None)


def sdk_boundary(adapter, name, arguments):
    """实际FunctionTool解析/typed input执行后才可能调用记录器。"""
    registry = CapabilityRegistry()
    handler = RecordingHandler(name)
    registry.register(handler)
    context = RuntimeContext(
        scope=ExecutionScope(max_results=10),
        capability_registry=registry,
        available_capabilities=(name,),
        run_id="parameter-contract",
    )
    context.allocate_tool_call_id("parameter")
    wrapper = ToolContext(
        context=context, tool_name=name, tool_call_id="parameter", tool_arguments=json.dumps(arguments)
    )
    tool = adapter(registry).as_sdk_tool(trusted_max_results=10)
    return tool, wrapper, handler


@pytest.mark.parametrize(
    "adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")]
)
@pytest.mark.parametrize("field", ["context_before", "context_after"])
@pytest.mark.parametrize("value", [True, "2", 2.0, -1])
def test_p02_rejects_invalid_lexical_context_before_registry(adapter, name, field, value):
    """先拒绝原始非法类型，避免SDK转换后typed input失去原输入事实。"""
    tool, wrapper, handler = sdk_boundary(adapter, name, {"keyword": "anchor", "limit": 5, field: value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize(
    "adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")]
)
def test_p02_schema_and_valid_context_keep_message_counts(adapter, name):
    """零窗口与普通窗口均有效；Schema不新增未经证明的单侧上界。"""
    args = {"keyword": "anchor", "limit": 5, "context_before": 0, "context_after": 20}
    tool, wrapper, handler = sdk_boundary(adapter, name, args)
    for field in ("context_before", "context_after"):
        schema = tool.params_json_schema["properties"][field]
        assert schema["minimum"] == 0 and schema["default"] == 2
        assert "maximum" not in schema
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok"
    assert handler.calls[0].context_before == 0 and handler.calls[0].context_after == 20


def test_all_iteration_candidates_only_remove_declared_fragments():
    """每一步都从前一候选精确删一片段；其余正文、空白与顺序整体相等。"""
    manifest = json.loads((TASK / "research/optimization-candidates.json").read_text())
    previous = SYSTEM_PROMPT
    for item in manifest:
        assert previous.count(item["removed"]) == 1
        expected = previous.replace(item["removed"], "", 1)
        assert (TASK / "research" / item["file"]).read_text() == expected
        previous = expected
