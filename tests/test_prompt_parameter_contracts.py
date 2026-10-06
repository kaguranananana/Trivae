"""逐轮验证真实SDK参数边界与累计候选；所有Provider成本为零。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from agents.exceptions import ModelBehaviorError
from agents.tool_context import ToolContext

from trivae.capabilities import CapabilityRegistry, ExecutionScope
from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecuteSQLInput,
    FindMembersInput,
    GetRecentMessagesInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
)
from trivae.query.runtime.contracts import RuntimeContext
from trivae.query.runtime.openai_tools import (
    ExecuteSQLSDKToolAdapter,
    FindMembersSDKToolAdapter,
    GetMessageContextSDKToolAdapter,
    GetRecentMessagesSDKToolAdapter,
    GetSchemaSDKToolAdapter,
    LexicalSearchSDKToolAdapter,
    SearchMessagesSDKToolAdapter,
    SemanticSearchSDKToolAdapter,
)
from trivae.query.runtime.prompt import SYSTEM_PROMPT
from trivae.retrieval.context import MAX_CONTEXT_EXPANSION_MESSAGES

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
    # schema/context工具不接收result设置；其余工具使用同一trusted scope。
    tool = (
        adapter(registry).as_sdk_tool()
        if name in {"get_schema", "get_message_context"}
        else adapter(registry).as_sdk_tool(trusted_max_results=10)
    )
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


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p03_dense_candidates_reject_invalid_raw_values(value):
    """真实SDK不得把非法原类型转成合法dense候选数。"""
    tool, wrapper, handler = sdk_boundary(
        SemanticSearchSDKToolAdapter, "semantic_search", {"query": "Agent后训练", "dense_top_k": value}
    )
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p03_dense_candidates_typed_owner_already_rejects(value):
    """直接业务入口也执行相同正整数契约，不只依赖Schema。"""
    with pytest.raises(CapabilityContractError):
        SemanticSearchInput(query="Agent后训练", dense_top_k=value)


@pytest.mark.parametrize("dense_args,expected", [({}, 40), ({"dense_top_k": 1}, 1)])
def test_p03_schema_default_and_legal_dense_count(dense_args, expected):
    """保持既有默认40与合法最小值1，不改候选召回算法或limit。"""
    tool, wrapper, handler = sdk_boundary(
        SemanticSearchSDKToolAdapter, "semantic_search", {"query": "Agent后训练", **dense_args}
    )
    schema = tool.params_json_schema["properties"]["dense_top_k"]
    assert schema["minimum"] == 1 and schema["default"] == 40
    assert "maximum" not in schema
    assert "positive integer" in schema["description"].lower()
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok"
    assert handler.calls[0].dense_top_k == expected


@pytest.mark.parametrize("value", ["", True, 2, ["用户A"]])
def test_p04_member_query_rejects_empty_and_non_string_at_sdk(value):
    """参数类型与空串在真实SDK解析拒绝，不发起身份查找。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


def test_p04_member_query_whitespace_remains_host_error():
    """minLength不证明非空白；原typed input继续负责去空白与错误envelope。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": "  "})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
    assert handler.calls == []


def test_p04_member_schema_and_valid_query_keep_normalization():
    """Schema公开非空约束，合法名称沿用Host规范化，不改变消歧算法。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": " 用户A "})
    schema = tool.params_json_schema["properties"]["query"]
    assert schema["type"] == "string" and schema["minLength"] == 1
    assert "non-empty" in schema["description"]
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].query == "用户A"


@pytest.mark.parametrize("value", ["", True, 2, ["Agent后训练"]])
def test_p05_semantic_query_rejects_empty_and_non_string_at_sdk(value):
    """概念检索的原始参数由真实SDK校验，不发起dense检索。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search", {"query": value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


def test_p05_semantic_query_whitespace_remains_host_error():
    """非空白语义继续交给已有typed input，minLength只表达字符串长度。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search", {"query": "  "})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
    assert handler.calls == []


def test_p05_semantic_schema_and_valid_query_keep_normalization():
    """合法概念文本沿原路径传递；不重新选择路由、不改变召回参数。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search", {"query": " Agent后训练 "})
    schema = tool.params_json_schema["properties"]["query"]
    assert schema["type"] == "string" and schema["minLength"] == 1
    assert "non-empty" in schema["description"]
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].query == "Agent后训练"


def test_p06_schema_extra_arguments_are_rejected_before_registry():
    """复现实际额外table参数，禁止SDK静默忽略后继续读schema。"""
    tool, wrapper, handler = sdk_boundary(GetSchemaSDKToolAdapter, "get_schema", {"table": "messages"})
    with pytest.raises(ModelBehaviorError, match="get_schema accepts no arguments"):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("raw_arguments", ["{}", ""])
def test_p06_no_arguments_keep_sdk_wire_forms(raw_arguments):
    """SDK原有空对象/空串无参数形式都保持成功，不新增业务参数。"""
    tool, wrapper, handler = sdk_boundary(GetSchemaSDKToolAdapter, "get_schema", {})
    schema = tool.params_json_schema
    assert schema["properties"] == {} and schema["additionalProperties"] is False
    assert "accepts no arguments" in tool.description.lower()
    response = asyncio.run(tool.on_invoke_tool(wrapper, raw_arguments))
    assert response["status"] == "ok" and len(handler.calls) == 1


def test_p06_invalid_json_keeps_explicit_error_cause():
    """入口解析失败保持原始异常链，不能静默当作无参数调用。"""
    tool, wrapper, handler = sdk_boundary(GetSchemaSDKToolAdapter, "get_schema", {})
    with pytest.raises(ModelBehaviorError, match="invalid JSON") as caught:
        asyncio.run(tool.on_invoke_tool(wrapper, "{"))
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)
    assert handler.calls == []


@pytest.mark.parametrize(
    "adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")]
)
@pytest.mark.parametrize("value", [True, 2, ["anchor"], {"keyword": "anchor"}])
def test_p07_keyword_is_already_one_string_at_sdk(adapter, name, value):
    """先证明原SDK已拒绝非字符串；本轮不修改任何解析实现。"""
    tool, wrapper, handler = sdk_boundary(adapter, name, {"keyword": value, "limit": 5})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("value", [True, 2, ["anchor"], {"keyword": "anchor"}])
def test_p07_keyword_typed_owner_already_rejects(value):
    """直接业务输入也拒绝多值/非字符串，不仅是对JSON Schema的推测。"""
    with pytest.raises(CapabilityContractError):
        SearchMessagesInput(keyword=value)


@pytest.mark.parametrize(
    "adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")]
)
def test_p07_schema_and_visible_description_keep_single_keyword(adapter, name):
    """单字符串契约已在可见工具层；合法anchor保持原参数与执行链。"""
    tool, wrapper, handler = sdk_boundary(adapter, name, {"keyword": "anchor", "limit": 5})
    assert tool.params_json_schema["properties"]["keyword"]["type"] == "string"
    assert "keyword must be exactly one non-empty string" in tool.description
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].keyword == "anchor"


LEXICAL_ADAPTERS = [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")]
FILTERS = ("session_ids", "sender_user_ids", "message_types")


@pytest.mark.parametrize("adapter,name", LEXICAL_ADAPTERS)
@pytest.mark.parametrize("field", FILTERS)
def test_p08_empty_filters_rejected_before_registry(adapter, name, field):
    """空数组是原明确非法参数；真实SDK应在业务执行前拒绝。"""
    tool, wrapper, handler = sdk_boundary(adapter, name, {"keyword": "anchor", "limit": 5, field: []})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("field", FILTERS)
def test_p08_typed_owner_already_rejects_empty_filters(field):
    """直接业务入口的非空数组规则仍保留，避免只依赖provider校验。"""
    with pytest.raises(CapabilityContractError):
        SearchMessagesInput(keyword="anchor", **{field: ()})


@pytest.mark.parametrize("adapter,name", LEXICAL_ADAPTERS)
def test_p08_schema_exposes_optional_non_empty_filters(adapter, name):
    """数组分支公开minItems=1，null分支和默认None保持原契约。"""
    tool, _, _ = sdk_boundary(adapter, name, {"keyword": "anchor", "limit": 5})
    for field in FILTERS:
        schema = tool.params_json_schema["properties"][field]
        array = next(branch for branch in schema["anyOf"] if branch["type"] == "array")
        assert array["minItems"] == 1
        assert {"type": "null"} in schema["anyOf"] and schema["default"] is None


@pytest.mark.parametrize("adapter,name", LEXICAL_ADAPTERS)
@pytest.mark.parametrize(
    "field,value", [("session_ids", "session:1"), ("sender_user_ids", "qq:user:A"), ("message_types", "text")]
)
@pytest.mark.parametrize("form", ["omit", "null", "array"])
def test_p08_legal_filter_forms_keep_typed_parameters(adapter, name, field, value, form):
    """只检查参数解析；授权与真实filter效果继续由既有Capability回归验证。"""
    arguments = {"keyword": "anchor", "limit": 5}
    if form != "omit":
        arguments[field] = None if form == "null" else [value]
    tool, wrapper, handler = sdk_boundary(adapter, name, arguments)
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok"
    expected = (value,) if form == "array" else None
    assert getattr(handler.calls[0], field) == expected


def test_p09_member_empty_session_filter_rejected_before_registry():
    """同一参数契约在member工具也须真实拒绝，不能由lexical推定。"""
    tool, wrapper, handler = sdk_boundary(
        FindMembersSDKToolAdapter, "find_members", {"query": "用户A", "session_ids": []}
    )
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


def test_p09_member_typed_owner_already_rejects_empty_sessions():
    """Host原有非空数组检查继续存在。"""
    with pytest.raises(CapabilityContractError):
        FindMembersInput(query="用户A", session_ids=())


def test_p09_member_filter_schema_is_optional_non_empty():
    """实际Schema明确minItems，仍允许null及省略。"""
    tool, _, _ = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": "用户A"})
    schema = tool.params_json_schema["properties"]["session_ids"]
    array = next(branch for branch in schema["anyOf"] if branch["type"] == "array")
    assert array["minItems"] == 1
    assert {"type": "null"} in schema["anyOf"] and schema["default"] is None
    assert "non-empty" in schema["description"]


@pytest.mark.parametrize(
    "arguments,expected", [({}, None), ({"session_ids": None}, None), ({"session_ids": ["session:1"]}, ("session:1",))]
)
def test_p09_member_legal_session_forms_keep_parameters(arguments, expected):
    """既有省略/null/正常数组不变；真实授权逻辑仍由Capability验证。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": "用户A", **arguments})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].session_ids == expected


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p10_recent_limit_rejects_invalid_raw_types_before_registry(value):
    """recent独立验证真实SDK，不由lexical的strict字段推定。"""
    tool, wrapper, handler = sdk_boundary(GetRecentMessagesSDKToolAdapter, "get_recent_messages", {"limit": value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p10_recent_typed_owner_already_rejects_invalid_limit(value):
    """Host已有严格正整数规则保持，不新增时间解释。"""
    with pytest.raises(CapabilityContractError):
        GetRecentMessagesInput(limit=value)


@pytest.mark.parametrize("arguments,expected", [({}, 10), ({"limit": 1}, 1), ({"limit": 10}, 10)])
def test_p10_recent_schema_default_and_legal_limit(arguments, expected):
    """省略值保持当前scope推导的默认；缺省时间仍由Host锚定archive_latest。"""
    tool, wrapper, handler = sdk_boundary(GetRecentMessagesSDKToolAdapter, "get_recent_messages", arguments)
    schema = tool.params_json_schema["properties"]["limit"]
    assert schema["minimum"] == 1 and schema["maximum"] == 10 and schema["default"] == 10
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].limit == expected
    time_range = handler.calls[0].time_range
    assert time_range.amount == 2 and time_range.anchor == "archive_latest"


def test_p10_recent_trusted_maximum_rejects_before_retrieval(monkeypatch):
    """Schema上界不是执行保障；实际Capability必须在检索前拒绝。"""
    from tests import test_stage_b_tools as fixtures

    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        called = []
        original = app.structured_retrieval.retrieve_recent_messages

        def track(query):
            called.append(query)
            return original(query)

        monkeypatch.setattr(app.structured_retrieval, "retrieve_recent_messages", track)
        scope = ExecutionScope(max_results=5)
        context = RuntimeContext(
            scope=scope,
            capability_registry=app.capability_registry,
            available_capabilities=("get_recent_messages",),
            run_id="recent-limit",
        )
        context.allocate_tool_call_id("above")
        wrapper = ToolContext(
            context=context, tool_name="get_recent_messages", tool_call_id="above", tool_arguments="{}"
        )
        tool = GetRecentMessagesSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=5)
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"limit": 6})))
        assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
        assert called == []
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("field", ["context_before", "context_after"])
@pytest.mark.parametrize("value", [True, "2", 2.0, -1])
def test_p11_explicit_context_rejects_invalid_raw_windows(field, value):
    """显式context入口独立拒绝，不能依据lexical窗口已经strict就删除规则。"""
    tool, wrapper, handler = sdk_boundary(
        GetMessageContextSDKToolAdapter, "get_message_context", {"message_id": "qq:100:a2", field: value}
    )
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize(
    "windows,expected",
    [
        ({}, (8, 8)),
        ({"context_before": 0, "context_after": 20}, (0, 20)),
        ({"context_before": 0, "context_after": 40}, (0, 40)),
    ],
)
def test_p11_context_schema_and_legal_windows_preserve_defaults(windows, expected):
    """保留默认8/8及20/40合法消息数；不改变模型选择扩展大小的策略。"""
    tool, wrapper, handler = sdk_boundary(
        GetMessageContextSDKToolAdapter, "get_message_context", {"message_id": "qq:100:a2", **windows}
    )
    for field in ("context_before", "context_after"):
        schema = tool.params_json_schema["properties"][field]
        assert schema["minimum"] == 0 and schema["default"] == 8
        assert "maximum" not in schema
        assert "message count" in schema["description"]
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok"
    request = handler.calls[0]
    assert (request.context_before, request.context_after) == expected


@pytest.mark.parametrize(
    "before,after",
    [
        (MAX_CONTEXT_EXPANSION_MESSAGES, 0),
        (MAX_CONTEXT_EXPANSION_MESSAGES // 2, MAX_CONTEXT_EXPANSION_MESSAGES - MAX_CONTEXT_EXPANSION_MESSAGES // 2),
    ],
)
def test_p11_context_host_rejects_total_above_transport_bound(before, after):
    """上界是before+anchor+after共享总量，不能误表达为两个独立max。"""
    tool, wrapper, handler = sdk_boundary(
        GetMessageContextSDKToolAdapter,
        "get_message_context",
        {"message_id": "qq:100:a2", "context_before": before, "context_after": after},
    )
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
    assert str(MAX_CONTEXT_EXPANSION_MESSAGES) in response["error"]["message"]
    assert handler.calls == []


def test_p11_context_total_at_transport_bound_remains_legal():
    """合法总量边界不因新增Schema被缩小；不把scope结果数混作单侧窗口上限。"""
    tool, wrapper, handler = sdk_boundary(
        GetMessageContextSDKToolAdapter,
        "get_message_context",
        {"message_id": "qq:100:a2", "context_before": MAX_CONTEXT_EXPANSION_MESSAGES - 1, "context_after": 0},
    )
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and len(handler.calls) == 1


@pytest.mark.parametrize(
    "arguments", [{}, {"source_id": None, "message_id": None}, {"source_id": "m1-1", "message_id": "qq:100:a2"}]
)
def test_p12_identity_cardinality_host_already_rejects(arguments):
    """正式SDK函数体已在resolver/registry之前确定性拒绝零身份及双身份。"""
    tool, wrapper, handler = sdk_boundary(GetMessageContextSDKToolAdapter, "get_message_context", arguments)
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
    assert handler.calls == []


def test_p12_cardinality_remains_visible_in_tool_and_field_descriptions():
    """互斥公开指导已有；不误称仅两个optional字段就形式化了oneOf。"""
    tool, _, _ = sdk_boundary(GetMessageContextSDKToolAdapter, "get_message_context", {})
    assert "Provide exactly one identity parameter" in tool.description
    for field in ("source_id", "message_id"):
        assert "never both" in tool.params_json_schema["properties"][field]["description"]


def test_p12_real_projection_supports_both_single_identity_forms_and_null():
    """实际search→source resolver→canonical context，覆盖省略/null的四种合法身份参数。"""
    from tests import test_stage_b_tools as fixtures

    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        app.rebuild_lexical_index()
        context = RuntimeContext(
            scope=ExecutionScope(max_results=10),
            capability_registry=app.capability_registry,
            available_capabilities=("lexical_search", "get_message_context"),
            run_id="identity-count",
        )
        wrapper = ToolContext(context=context, tool_name="lexical_search", tool_call_id="anchor", tool_arguments="{}")
        search = LexicalSearchSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=10)
        tool = GetMessageContextSDKToolAdapter(app.capability_registry).as_sdk_tool()

        async def check():
            context.allocate_tool_call_id("anchor")
            projection = await search.on_invoke_tool(
                wrapper, json.dumps({"keyword": "anchor context", "limit": 10, "context_before": 0, "context_after": 0})
            )
            source_id = projection["provenance"]["message_sources"][0]["source_id"]
            canonical = context.resolve_message_source_handle(source_id)
            assert canonical == "qq:100:a2"
            arguments = [
                {"source_id": source_id},
                {"source_id": source_id, "message_id": None},
                {"message_id": canonical},
                {"message_id": canonical, "source_id": None},
            ]
            for index, identity in enumerate(arguments):
                call_id = f"identity-{index}"
                context.allocate_tool_call_id(call_id)
                # 与生产Runner一致，每次调用的ToolContext元信息必须使用当前tool/call。
                wrapper.tool_name = "get_message_context"
                wrapper.tool_call_id = call_id
                wrapper.tool_arguments = json.dumps(identity)
                response = await tool.on_invoke_tool(wrapper, wrapper.tool_arguments)
                assert response["status"] == "ok"
                # 原Host resolver使用当前run的真实投影，不把handle当作canonical ID。
                assert context.resolve_message_source_handle(source_id) == canonical

        asyncio.run(check())
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p13_sql_row_cap_rejects_invalid_raw_values(value):
    """可选row cap必须保留原始类型事实，不能经SDK转换绕过Host。"""
    tool, wrapper, handler = sdk_boundary(
        ExecuteSQLSDKToolAdapter, "execute_sql", {"sql": "SELECT COUNT(*) FROM messages", "max_rows": value}
    )
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_p13_sql_typed_owner_already_rejects_invalid_row_cap(value):
    """直接业务入口原有正整数/null规则保持。"""
    with pytest.raises(CapabilityContractError):
        ExecuteSQLInput(sql="SELECT COUNT(*) FROM messages", max_rows=value)


@pytest.mark.parametrize("sql", [True, 2, ["SELECT COUNT(*) FROM messages"]])
def test_p13_sql_already_rejects_non_string_before_registry(sql):
    """单SQL字符串已由真实SDK承接，本轮不修改sql解析或语句内容。"""
    tool, wrapper, handler = sdk_boundary(ExecuteSQLSDKToolAdapter, "execute_sql", {"sql": sql})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize(
    "arguments,expected", [({}, None), ({"max_rows": None}, None), ({"max_rows": 1}, 1), ({"max_rows": 10}, 10)]
)
def test_p13_sql_schema_and_legal_optional_cap(arguments, expected):
    """省略/null仍交Host推导trusted bound，合法正值保持原参数。"""
    tool, wrapper, handler = sdk_boundary(
        ExecuteSQLSDKToolAdapter, "execute_sql", {"sql": "SELECT COUNT(*) FROM messages", **arguments}
    )
    schema = tool.params_json_schema["properties"]["max_rows"]
    integer = next(branch for branch in schema["anyOf"] if branch["type"] == "integer")
    assert integer["minimum"] == 1 and schema["maximum"] == 10
    assert {"type": "null"} in schema["anyOf"] and schema["default"] is None
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].max_rows == expected
    assert handler.calls[0].sql == "SELECT COUNT(*) FROM messages"


def test_p13_sql_trusted_maximum_rejects_before_repository(monkeypatch):
    """上界继续由Capability拒绝，不拿Schema maximum替代真实执行。"""
    from tests import test_stage_b_tools as fixtures

    fixture = fixtures.StageBToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        called = []
        original = app.read_repository.execute_readonly_sql

        def track(query, scope):
            called.append(query)
            return original(query, scope)

        monkeypatch.setattr(app.read_repository, "execute_readonly_sql", track)
        context = RuntimeContext(
            scope=ExecutionScope(max_results=5),
            capability_registry=app.capability_registry,
            available_capabilities=("execute_sql",),
            run_id="sql-cap",
        )
        context.allocate_tool_call_id("above")
        wrapper = ToolContext(context=context, tool_name="execute_sql", tool_call_id="above", tool_arguments="{}")
        tool = ExecuteSQLSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=5)
        response = asyncio.run(
            tool.on_invoke_tool(wrapper, json.dumps({"sql": "SELECT COUNT(*) FROM messages", "max_rows": 6}))
        )
        assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
        assert called == []
    finally:
        fixture.tearDown()


@pytest.mark.parametrize(
    "sql",
    ["SELECT COUNT(*) FROM messages; SELECT COUNT(*) FROM users", "SELECT COUNT(*) FROM messages; DELETE FROM messages"],
)
def test_p14_sql_driver_rejects_second_statement_through_real_sdk(sql):
    """真实SDK→Capability→SQLite拒绝第二语句，错误不被转换为成功空结果。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        context = RuntimeContext(
            scope=ExecutionScope(max_results=10),
            capability_registry=app.capability_registry,
            available_capabilities=("execute_sql",),
            run_id="single-statement",
        )
        context.allocate_tool_call_id("invalid")
        wrapper = ToolContext(context=context, tool_name="execute_sql", tool_call_id="invalid", tool_arguments="{}")
        tool = ExecuteSQLSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=10)
        # 不在测试中拆分SQL；必须由正式driver拒绝完整模型输入。
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"sql": sql})))
        assert response["status"] == "error" and response["error"]["code"] == "SQL_MALFORMED"
        assert "one statement at a time" in response["error"]["message"]
        # 查询原始fixture总量，证明第二条DELETE未执行；不只断言Finalizer有效。
        count = fixture._execute("SELECT COUNT(*) AS total FROM messages")
        assert count.status == "ok" and count.data.rows == ({"total": 8},)
        assert "one read-only SQL statement" in tool.description
    finally:
        fixture.tearDown()


def test_p14_sql_single_statement_with_literal_semicolon_remains_legal():
    """合法字面量/结尾分号仍由SQLite原生解析，不增加粗糙分号过滤。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        result = fixture._execute("SELECT ';' AS marker, COUNT(*) AS total FROM messages; -- single statement")
        assert result.status == "ok" and result.data.rows == ({"marker": ";", "total": 8},)
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("sql", ["DELETE FROM messages", "CREATE TABLE injected(value TEXT)"])
def test_p15_sql_write_and_ddl_rejected_through_real_sdk(sql):
    """只验证已有只读执行，不新增安全过滤；真实错误码和数据状态必须可观察。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        context = RuntimeContext(
            scope=ExecutionScope(max_results=10),
            capability_registry=app.capability_registry,
            available_capabilities=("execute_sql",),
            run_id="read-only",
        )
        context.allocate_tool_call_id("write")
        wrapper = ToolContext(context=context, tool_name="execute_sql", tool_call_id="write", tool_arguments="{}")
        tool = ExecuteSQLSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=10)
        # SDK不重写SQL；authorizer必须拒绝传入的原始写入或DDL。
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"sql": sql})))
        assert response["status"] == "error" and response["error"]["code"] == "SQL_READ_ONLY_VIOLATION"
        assert "read-only SQL statement was rejected" in response["error"]["message"]
        # 查询所有原消息以及原业务schema，确保失败不是静默执行后伪报。
        count = fixture._execute("SELECT COUNT(*) AS total FROM messages")
        assert count.status == "ok" and count.data.rows == ({"total": 8},)
        schema = app.invoke_tool("get_schema", GetSchemaInput(), ExecutionScope(max_results=10))
        assert tuple(table.name for table in schema.data.tables) == ("chat_sessions", "users", "memberships", "messages")
        # public schema会隐藏未知表，因此还须直接检查fixture库，不能拿投影视图证明DDL未发生。
        database = Path(fixture.temporary.name) / "stage-c.sqlite3"
        connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        try:
            assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'injected'").fetchall() == []
        finally:
            connection.close()
        assert "Writes, DDL" in tool.description
    finally:
        fixture.tearDown()


def test_p16_sql_scope_is_enforced_outside_model_sql_through_real_sdk():
    """SQL未写WHERE也只返回trusted scope，显式main读取不能扩展权限。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        context = RuntimeContext(
            scope=ExecutionScope(allowed_session_ids=("qq:100",), start_timestamp=2_000,
                                 end_timestamp=5_000, max_results=10),
            capability_registry=app.capability_registry,
            available_capabilities=("execute_sql",),
            run_id="sql-scope",
        )
        tool = ExecuteSQLSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=10)
        assert "trusted session/time scope is enforced by the tool" in tool.description

        async def check():
            for call_id, sql, expected in (
                ("scoped", "SELECT COUNT(*) AS total FROM messages", "ok"),
                ("escape", "SELECT COUNT(*) AS total FROM main.messages", "error"),
            ):
                context.allocate_tool_call_id(call_id)
                wrapper = ToolContext(context=context, tool_name="execute_sql", tool_call_id=call_id,
                                      tool_arguments=json.dumps({"sql": sql}))
                # 直接走正式SDK，所有scope只能来自不可由模型参数覆盖的local context。
                response = await tool.on_invoke_tool(wrapper, wrapper.tool_arguments)
                assert response["status"] == expected
                if expected == "ok":
                    assert response["data"]["rows"] == [{"total": 3, "source_id": "s1-1"}]
                else:
                    assert response["error"]["code"] == "SQL_SCOPE_VIOLATION"

        asyncio.run(check())
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_c17_member_limit_rejects_invalid_raw_values(value):
    """Schema integer/minimum必须与实际SDK解析一致，不能靠转换后再验的Host掩盖原类型。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": "Alice", "limit": value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("arguments,expected", [({}, 10), ({"limit": 1}, 1), ({"limit": 10}, 10)])
def test_c17_member_limit_keeps_legal_values_and_scope_default(arguments, expected):
    """scope内默认值不变；不修改身份query或candidate选择。"""
    tool, wrapper, handler = sdk_boundary(FindMembersSDKToolAdapter, "find_members", {"query": "Alice", **arguments})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok" and handler.calls[0].limit == expected
    assert tool.params_json_schema["properties"]["limit"]["minimum"] == 1
    assert tool.params_json_schema["properties"]["limit"]["maximum"] == 10


def test_c17_member_trusted_limit_rejects_before_repository(monkeypatch):
    """真实成员Capability继续执行上界，不拿Schema代替Host授权。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        called = []
        original = app.read_repository.read_member_candidates

        def track(query):
            called.append(query)
            return original(query)

        monkeypatch.setattr(app.read_repository, "read_member_candidates", track)
        context = RuntimeContext(scope=ExecutionScope(max_results=5), capability_registry=app.capability_registry,
                                 available_capabilities=("find_members",), run_id="member-limit")
        context.allocate_tool_call_id("above")
        wrapper = ToolContext(context=context, tool_name="find_members", tool_call_id="above", tool_arguments="{}")
        tool = FindMembersSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=5)
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"query": "Alice", "limit": 6})))
        assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
        assert called == []
        assert tool.params_json_schema["properties"]["limit"]["default"] == 5
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("value", [True, "2", 2.0, 0, -1])
def test_c18_semantic_limit_rejects_invalid_raw_values(value):
    """Schema已声明integer/minimum，实际解析须拒绝原始非法参数。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search", {"query": "learning", "limit": value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("arguments,expected", [({}, 10), ({"limit": 1}, 1), ({"limit": 10}, 10)])
def test_c18_semantic_limit_legal_values_preserve_retrieval_defaults(arguments, expected):
    """本轮只改类型/正值校验，保留dense40与context2/2及原默认limit10。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search", {"query": "learning", **arguments})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    request = handler.calls[0]
    assert response["status"] == "ok" and request.limit == expected
    assert (request.dense_top_k, request.context_before, request.context_after) == (40, 2, 2)
    assert tool.params_json_schema["properties"]["limit"]["minimum"] == 1


def test_c18_semantic_trusted_limit_rejects_before_search(monkeypatch):
    """越界在真实Capability的semantic search之前拒绝，不触发本地embedding加载。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        called = []
        original = app.semantic_retrieval.search

        def track(query):
            called.append(query)
            return original(query)

        monkeypatch.setattr(app.semantic_retrieval, "search", track)
        context = RuntimeContext(scope=ExecutionScope(max_results=5), capability_registry=app.capability_registry,
                                 available_capabilities=("semantic_search",), run_id="semantic-limit")
        context.allocate_tool_call_id("above")
        wrapper = ToolContext(context=context, tool_name="semantic_search", tool_call_id="above", tool_arguments="{}")
        tool = SemanticSearchSDKToolAdapter(app.capability_registry).as_sdk_tool(trusted_max_results=5)
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"query": "learning", "limit": 6})))
        assert response["status"] == "error" and response["error"]["code"] == "INVALID_ARGUMENT"
        assert called == []
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("trusted", [1, 5, 10, 20])
def test_c19_semantic_omitted_limit_matches_published_scope_default(trusted):
    """省略值必须执行Schema真正公布的默认值；不能要求模型补参数绕过SDK缺口。"""
    registry = CapabilityRegistry()
    handler = RecordingHandler("semantic_search")
    registry.register(handler)
    context = RuntimeContext(scope=ExecutionScope(max_results=trusted), capability_registry=registry,
                             available_capabilities=("semantic_search",), run_id="semantic-default")
    context.allocate_tool_call_id("default")
    wrapper = ToolContext(context=context, tool_name="semantic_search", tool_call_id="default", tool_arguments="{}")
    tool = SemanticSearchSDKToolAdapter(registry).as_sdk_tool(trusted_max_results=trusted)
    expected = min(10, trusted)
    assert tool.params_json_schema["properties"]["limit"]["default"] == expected
    response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"query": "learning"})))
    assert response["status"] == "ok" and handler.calls[0].limit == expected
    assert (handler.calls[0].dense_top_k, handler.calls[0].context_before, handler.calls[0].context_after) == (40, 2, 2)


@pytest.mark.parametrize("adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")])
@pytest.mark.parametrize("trusted", [1, 10, 1_000])
def test_c20_lexical_omitted_limit_matches_published_scope_default(adapter, name, trusted):
    """两个名称共用同一个factory；Schema默认值必须是SDK实际执行值。"""
    registry = CapabilityRegistry()
    handler = RecordingHandler(name)
    registry.register(handler)
    context = RuntimeContext(scope=ExecutionScope(max_results=trusted), capability_registry=registry,
                             available_capabilities=(name,), run_id="lexical-default")
    context.allocate_tool_call_id("default")
    wrapper = ToolContext(context=context, tool_name=name, tool_call_id="default", tool_arguments="{}")
    tool = adapter(registry).as_sdk_tool(trusted_max_results=trusted)
    expected = min(1_000, trusted)
    assert tool.params_json_schema["properties"]["limit"]["default"] == expected
    response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"keyword": "first"})))
    assert response["status"] == "ok" and handler.calls[0].limit == expected
    assert (handler.calls[0].context_before, handler.calls[0].context_after) == (2, 2)


@pytest.mark.parametrize("adapter,name", [(LexicalSearchSDKToolAdapter, "lexical_search"), (SearchMessagesSDKToolAdapter, "search_messages")])
def test_c20_real_scoped_lexical_omission_executes_without_contract_error(adapter, name):
    """正式Capability/FTS链路复现：小scope合法省略值不该触发原1000越界错误。"""
    from tests import test_stage_c_tools as fixtures

    fixture = fixtures.StageCToolsTests()
    fixture.setUp()
    try:
        app = fixture.application
        app.rebuild_lexical_index()
        context = RuntimeContext(scope=ExecutionScope(allowed_session_ids=("qq:100",), max_results=5),
                                 capability_registry=app.capability_registry, available_capabilities=(name,), run_id="scoped-default")
        context.allocate_tool_call_id("default")
        wrapper = ToolContext(context=context, tool_name=name, tool_call_id="default", tool_arguments="{}")
        tool = adapter(app.capability_registry).as_sdk_tool(trusted_max_results=5)
        response = asyncio.run(tool.on_invoke_tool(wrapper, json.dumps({"keyword": "first"})))
        assert response["status"] == "ok"
        assert len(response["data"]["hits"]) == 1
    finally:
        fixture.tearDown()


@pytest.mark.parametrize("field", ["context_before", "context_after"])
@pytest.mark.parametrize("value", [True, "2", 2.0, -1])
def test_c21_semantic_context_rejects_invalid_raw_values(field, value):
    """SDK须执行typed input原有的非负整数约束，不能先把非法类型转换成整数。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search",
                                         {"query": "learning", field: value})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("arguments,expected", [({}, (2, 2)),
    ({"context_before": 0, "context_after": 0}, (0, 0)),
    ({"context_before": 0, "context_after": 20}, (0, 20)),
    ({"context_before": 0, "context_after": 40}, (0, 40))])
def test_c21_semantic_context_preserves_default_and_legal_windows(arguments, expected):
    """原默认2/2与合法深窗原值送达；只验证参数，不能推断模型选窗等价。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search",
                                         {"query": "learning", **arguments})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    request = handler.calls[0]
    assert response["status"] == "ok"
    assert (request.context_before, request.context_after) == expected
    assert (request.limit, request.dense_top_k) == (10, 40)
    for field in ("context_before", "context_after"):
        assert tool.params_json_schema["properties"][field]["minimum"] == 0
        assert tool.params_json_schema["properties"][field]["default"] == 2


@pytest.mark.parametrize("field", ["session_ids", "sender_user_ids", "message_types"])
def test_c22_semantic_empty_filters_rejected_by_actual_sdk(field):
    """Host已有非空数组约束，SDK必须同样公开并执行，不依赖工具描述文字。"""
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search",
                                         {"query": "learning", field: []})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("field", ["session_ids", "sender_user_ids", "message_types"])
def test_c22_semantic_typed_owner_already_rejects_empty_filters(field):
    """迁移Schema前证明现有Host实际拒绝；不新增检索语义或filter选择规则。"""
    with pytest.raises(CapabilityContractError):
        SemanticSearchInput(query="learning", **{field: ()})


@pytest.mark.parametrize("form", ["omitted", "null", "non_empty"])
def test_c22_semantic_optional_filter_forms_and_schema_remain_consistent(form):
    """null/省略继续沿原scope继承，合法数组原值送达，默认与可选性不变。"""
    values = {"session_ids": ["qq:100"], "sender_user_ids": ["user:alice"], "message_types": ["text"]}
    arguments = {} if form == "omitted" else {field: None if form == "null" else value
                                             for field, value in values.items()}
    tool, wrapper, handler = sdk_boundary(SemanticSearchSDKToolAdapter, "semantic_search",
                                         {"query": "learning", **arguments})
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert response["status"] == "ok"
    for field, value in values.items():
        assert getattr(handler.calls[0], field) == (tuple(value) if form == "non_empty" else None)
        schema = tool.params_json_schema["properties"][field]
        array = next(branch for branch in schema["anyOf"] if branch["type"] == "array")
        assert array["minItems"] == 1
        assert {"type": "null"} in schema["anyOf"] and schema["default"] is None


@pytest.mark.parametrize("field", ["session_ids", "sender_user_ids"])
def test_c23_recent_empty_filters_rejected_before_registry(field):
    """非空数组是已有Host/description契约，SDK应直接拒绝空数组。"""
    tool, wrapper, handler = sdk_boundary(GetRecentMessagesSDKToolAdapter, "get_recent_messages", {field: []})
    with pytest.raises(ModelBehaviorError):
        asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    assert handler.calls == []


@pytest.mark.parametrize("field", ["session_ids", "sender_user_ids"])
def test_c23_recent_typed_owner_already_rejects_empty_filters(field):
    """先验证真实typed input owner，不凭Schema推断非法参数已被承接。"""
    with pytest.raises(CapabilityContractError):
        GetRecentMessagesInput(**{field: ()})


@pytest.mark.parametrize("form", ["omitted", "null", "non_empty"])
def test_c23_recent_filter_schema_and_legal_forms_preserve_time_defaults(form):
    """公开minItems不改变可选参数、scope继承、两天archive_latest或cursor。"""
    values = {"session_ids": ["qq:100"], "sender_user_ids": ["user:alice"]}
    arguments = {} if form == "omitted" else {field: None if form == "null" else value
                                             for field, value in values.items()}
    tool, wrapper, handler = sdk_boundary(GetRecentMessagesSDKToolAdapter, "get_recent_messages", arguments)
    response = asyncio.run(tool.on_invoke_tool(wrapper, wrapper.tool_arguments))
    request = handler.calls[0]
    assert response["status"] == "ok" and request.limit == 10
    assert request.cursor is None and request.start_timestamp is None and request.end_timestamp is None
    assert (request.time_range.amount, request.time_range.unit, request.time_range.anchor) == (2, "day", "archive_latest")
    for field, value in values.items():
        assert getattr(request, field) == (tuple(value) if form == "non_empty" else None)
        schema = tool.params_json_schema["properties"][field]
        array = next(branch for branch in schema["anyOf"] if branch["type"] == "array")
        assert array["minItems"] == 1
        assert {"type": "null"} in schema["anyOf"] and schema["default"] is None
