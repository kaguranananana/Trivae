"""把 lexical/semantic retrieval 映射为独立的 OpenAI Agents SDK Function Tool。"""

from __future__ import annotations

from typing import Any, cast

from agents import RunContextWrapper, function_tool

from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecuteSQLInput,
    FindMembersInput,
    GetMessageContextInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.registry import CapabilityRegistry
from trivae.config.limits import DEFAULT_RESULT_LIMIT
from trivae.observability.contracts import FailureInfo
from trivae.query.evidence import build_tool_result_record
from trivae.query.runtime.contracts import RuntimeContext, RuntimeToolCall


def _contract_error_envelope(error: CapabilityContractError) -> ToolEnvelope:
    """将 SDK 参数解码阶段产生的已知 contract 错误投影为统一 envelope。"""

    return ToolEnvelope(
        status="error",
        data=None,
        meta={"truncated": False},
        error=ToolError(code=error.error_code, message=str(error)),
    )


class SearchMessagesSDKToolAdapter:
    """只做 typed input 转换与安全 envelope 投影，不实现检索逻辑。"""

    def __init__(self, registry: CapabilityRegistry, *, tool_name: str = "search_messages") -> None:
        self.registry = registry
        self.tool_name = tool_name

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建 SDK Function Tool；scope 和 registry 只通过 local context 注入。"""

        if trusted_max_results is not None:
            # 这里仅把本次执行的结果数量上限表达给模型，真正的 scope enforcement 仍在 Capability 内完成。
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        if self.tool_name == "lexical_search":
            # canonical lexical tool 只提供选择提示；实际是否继续 semantic 由 Agent 自主判断。
            description = (
                "Search Trivae messages with exact lexical matching and a bounded local context window. "
                "Normally call this first for repository names, URLs, code, error messages, nicknames, "
                "exact phrases, or other precise terms. For a paraphrase or conceptual description "
                "without a precise term, normally call semantic_search first instead. Do not call both "
                "just to hedge; do not repeat this tool with the same or nearly identical arguments "
                "after no hits, and do not use translation, synonym, punctuation, or near-duplicate "
                "queries as multi-query expansion. Use the other tool only when the first result is "
                "weak or insufficient. "
                "keyword must be exactly one non-empty string. "
                "Omit optional filters, or use null; do not send empty arrays. "
                "limit must be a positive integer within the current trusted result limit. "
                "context_before and context_after must be non-negative integers. "
                "Use one complete provenance message source entry for each citation."
            )
        else:
            # legacy 名称保留原 contract，并明确它不是正常 Agent surface 的 canonical 名称。
            description = (
                "Legacy compatibility entry point for exact lexical search in Trivae messages, "
                "with a bounded local context window. Prefer lexical_search for the normal Agent surface. "
                "keyword must be exactly one non-empty string. "
                "Omit optional filters, or use null; do not send empty arrays. "
                "limit must be a positive integer within the current trusted result limit. "
                "context_before and context_after must be non-negative integers. "
                "Use one complete provenance message source entry for each citation."
            )
        if trusted_max_results is not None:
            # 让 schema 与描述同时携带动态 bound，减少模型先生成越界 limit 再恢复的无效回合。
            description += f" The current trusted result limit is {trusted_max_results}."

        @function_tool(
            name_override=self.tool_name,
            description_override=description,
            # 已知 contract 错误已经投影为 envelope；未知异常必须让 Runner 终止并暴露根因。
            failure_error_function=None,
            strict_mode=False,
        )
        async def search_messages(
            context: RunContextWrapper[RuntimeContext],
            keyword: str,
            session_ids: list[str] | None = None,
            start_timestamp: int | None = None,
            end_timestamp: int | None = None,
            sender_user_ids: list[str] | None = None,
            message_types: list[str] | None = None,
            limit: int = DEFAULT_RESULT_LIMIT,
            context_before: int = 2,
            context_after: int = 2,
        ) -> dict[str, object]:
            """只接受 typed 字段；scope、registry 和 call identity 都来自 local context。

            Args:
                keyword: Exactly one non-empty search string, not an array.
                session_ids: Optional non-empty session ID array; use null when unused.
                start_timestamp: Optional integer inclusive lower bound in milliseconds.
                end_timestamp: Optional integer exclusive upper bound in milliseconds.
                sender_user_ids: Optional non-empty sender ID array; use null when unused.
                message_types: Optional non-empty message type array; use null when unused.
                limit: Positive result count not greater than the trusted result limit.
                context_before: Non-negative number of messages before each hit.
                context_after: Non-negative number of messages after each hit.
            """

            runtime_context = context.context
            # SDK 版本可能把 call id 放在 wrapper 或 typed local context 上，二者都只投影为安全字符串。
            provider_tool_call_id = getattr(context, "tool_call_id", None)
            if not isinstance(provider_tool_call_id, str):
                provider_tool_call_id = None
            # SDK ID 只用于 local mapping；正式 contract 使用由 Runtime 分配的 Trivae ID。
            tool_call_id = runtime_context.resolve_tool_call_id(provider_tool_call_id)
            trace_context = runtime_context.trace_context
            if trace_context is not None:
                child = getattr(trace_context, "child", None)
                if not callable(child):
                    raise TypeError("runtime trace_context must provide child()")
                trace_context = child(f"tool:{tool_call_id}")
            if self.tool_name not in runtime_context.available_capabilities:
                # 工具不可见时仍被调用属于 Runtime invariant，不能伪装成普通结果。
                raise RuntimeError(f"{self.tool_name} was invoked outside the allowed capability set")

            try:
                # 只把模型可控的搜索字段转换为既有业务 input；scope 不从模型参数读取。
                request = SearchMessagesInput(
                    keyword=keyword,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    sender_user_ids=None if sender_user_ids is None else tuple(sender_user_ids),
                    message_types=None if message_types is None else tuple(message_types),
                    limit=limit,
                    context_before=context_before,
                    context_after=context_after,
                )
            except CapabilityContractError as exc:
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": self.tool_name, "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                try:
                    # trusted scope 由 RuntimeContext 持有，registry 是 composition root 注入的实例。
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        self.tool_name,
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    # 未分类异常必须继续冒泡；这里只记录失败状态供 terminal result 诊断。
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            self.tool_name,
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise

            error_code = envelope.error.code if envelope.error is not None else None
            # 一个已知 ToolEnvelope 一定对应一个 Trivae-owned Tool Result identity。
            tool_result_id = f"{tool_call_id}/result"
            record = build_tool_result_record(
                run_id=runtime_context.run_id,
                tool_call_id=tool_call_id,
                tool_result_id=tool_result_id,
                tool_name=self.tool_name,
                envelope=envelope,
                scope=runtime_context.scope,
            )
            runtime_context.tool_results.append(record)
            # 这里记录一次 tool call；同一模型回合的多个调用由 Runtime hook 统一计为一轮。
            runtime_context.tool_calls.append(
                RuntimeToolCall(
                    self.tool_name,
                    envelope.status,
                    error_code,
                    tool_call_id=tool_call_id,
                    tool_result_id=tool_result_id,
                    round=runtime_context.current_tool_round,
                )
            )
            # Tool Result 除既有数据外只增加安全 locator，供 final synthesis 提出可验证引用。
            result_payload = envelope.to_dict()
            result_payload["provenance"] = record.to_model_provenance()
            return result_payload

        if trusted_max_results is not None:
            # SDK 0.22 使用该 JSON Schema 给 provider 描述参数边界；业务层仍会再次校验实际输入。
            schema = getattr(search_messages, "params_json_schema", None)
            if not isinstance(schema, dict):
                raise TypeError("SDK Function Tool did not expose params_json_schema")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("SDK Function Tool schema did not expose properties")
            limit_schema = properties.get("limit")
            if not isinstance(limit_schema, dict):
                raise TypeError(f"{self.tool_name} schema did not expose limit")
            # 只增强 provider-facing schema，不把 schema 约束当成 trusted enforcement 的替代品。
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = trusted_max_results
            limit_schema["default"] = min(DEFAULT_RESULT_LIMIT, trusted_max_results)

        return search_messages


class LexicalSearchSDKToolAdapter(SearchMessagesSDKToolAdapter):
    """canonical lexical_search SDK 名称，共用既有 keyword 输入与 evidence 主链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__(registry, tool_name="lexical_search")


class SemanticSearchSDKToolAdapter:
    """把 semantic_search 的 typed input 接到同一 RuntimeContext/Trace/Evidence 主链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建独立 semantic tool；模型不能通过参数切换为 lexical。"""

        if trusted_max_results is not None:
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        description = (
            "Search Trivae conversation meaning with the local semantic embedding index. "
            "Normally call this first when the user's wording differs from the wording in the chat, "
            "including paraphrases, conceptual descriptions, or vague memories without a precise term. "
            "For exact names, codes, or phrases, normally call lexical_search first instead. Do not call "
            "both just to hedge; do not repeat this tool with the same or nearly identical arguments "
            "after no hits, and do not use translation, synonym, punctuation, or near-duplicate "
            "queries as multi-query expansion. Use the other tool only when the first result is weak "
            "or insufficient. "
            "Omit optional filters, or use null; do not send empty arrays. "
            "The semantic index must be explicitly built and may report partial coverage."
        )
        if trusted_max_results is not None:
            description += f" The current trusted result limit is {trusted_max_results}."

        @function_tool(
            name_override="semantic_search",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def semantic_search(
            context: RunContextWrapper[RuntimeContext],
            query: str,
            session_ids: list[str] | None = None,
            start_timestamp: int | None = None,
            end_timestamp: int | None = None,
            sender_user_ids: list[str] | None = None,
            message_types: list[str] | None = None,
            source_message_id: str | None = None,
            reply_to_source_message_id: str | None = None,
            limit: int = 10,
            context_before: int = 2,
            context_after: int = 2,
            dense_top_k: int = 40,
        ) -> dict[str, object]:
            """将模型字段投影为 SemanticSearchInput，scope 仍由 RuntimeContext 注入。"""

            runtime_context = context.context
            provider_tool_call_id = getattr(context, "tool_call_id", None)
            if not isinstance(provider_tool_call_id, str):
                provider_tool_call_id = None
            tool_call_id = runtime_context.resolve_tool_call_id(provider_tool_call_id)
            trace_context = runtime_context.trace_context
            if trace_context is not None:
                child = getattr(trace_context, "child", None)
                if not callable(child):
                    raise TypeError("runtime trace_context must provide child()")
                trace_context = child(f"tool:{tool_call_id}")
            if "semantic_search" not in runtime_context.available_capabilities:
                raise RuntimeError("semantic_search was invoked outside the allowed capability set")

            try:
                request = SemanticSearchInput(
                    query=query,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    sender_user_ids=None if sender_user_ids is None else tuple(sender_user_ids),
                    message_types=None if message_types is None else tuple(message_types),
                    source_message_id=source_message_id,
                    reply_to_source_message_id=reply_to_source_message_id,
                    limit=limit,
                    context_before=context_before,
                    context_after=context_after,
                    dense_top_k=dense_top_k,
                )
            except CapabilityContractError as exc:
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "semantic_search", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                if runtime_context.capability_registry is not self.registry:
                    raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                try:
                    envelope = runtime_context.capability_registry.invoke(
                        "semantic_search",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "semantic_search",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise

            error_code = envelope.error.code if envelope.error is not None else None
            tool_result_id = f"{tool_call_id}/result"
            record = build_tool_result_record(
                run_id=runtime_context.run_id,
                tool_call_id=tool_call_id,
                tool_result_id=tool_result_id,
                tool_name="semantic_search",
                envelope=envelope,
                scope=runtime_context.scope,
            )
            runtime_context.tool_results.append(record)
            runtime_context.tool_calls.append(
                RuntimeToolCall(
                    "semantic_search",
                    envelope.status,
                    error_code,
                    tool_call_id=tool_call_id,
                    tool_result_id=tool_result_id,
                    round=runtime_context.current_tool_round,
                )
            )
            result_payload = envelope.to_dict()
            result_payload["provenance"] = record.to_model_provenance()
            return result_payload

        if trusted_max_results is not None:
            schema = getattr(semantic_search, "params_json_schema", None)
            if not isinstance(schema, dict):
                raise TypeError("SDK Function Tool did not expose params_json_schema")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("SDK Function Tool schema did not expose properties")
            limit_schema = properties.get("limit")
            if not isinstance(limit_schema, dict):
                raise TypeError("semantic_search schema did not expose limit")
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = trusted_max_results
            limit_schema["default"] = min(10, trusted_max_results)

        return semantic_search


def _tool_runtime_context(
    context: RunContextWrapper[RuntimeContext],
    tool_name: str,
) -> tuple[RuntimeContext, str, object | None]:
    """统一解析 Runtime local context、Trivae Tool ID 和 Trace child。"""

    runtime_context = context.context
    provider_tool_call_id = getattr(context, "tool_call_id", None)
    if not isinstance(provider_tool_call_id, str):
        provider_tool_call_id = None
    tool_call_id = runtime_context.resolve_tool_call_id(provider_tool_call_id)
    trace_context = runtime_context.trace_context
    if trace_context is not None:
        child = getattr(trace_context, "child", None)
        if not callable(child):
            raise TypeError("runtime trace_context must provide child()")
        trace_context = child(f"tool:{tool_call_id}")
    if tool_name not in runtime_context.available_capabilities:
        # Tool 不可见时属于 Runtime invariant failure，不能返回普通 Agent 可恢复结果。
        raise RuntimeError(f"{tool_name} was invoked outside the allowed capability set")
    return runtime_context, tool_call_id, trace_context


def _append_runtime_tool_result(
    runtime_context: RuntimeContext,
    tool_name: str,
    tool_call_id: str,
    envelope: ToolEnvelope,
) -> dict[str, object]:
    """把同一 Tool Result 同时写入 Evidence provenance 和 Runtime action projection。"""

    error_code = envelope.error.code if envelope.error is not None else None
    tool_result_id = f"{tool_call_id}/result"
    record = build_tool_result_record(
        run_id=runtime_context.run_id,
        tool_call_id=tool_call_id,
        tool_result_id=tool_result_id,
        tool_name=tool_name,
        envelope=envelope,
        scope=runtime_context.scope,
    )
    runtime_context.tool_results.append(record)
    runtime_context.tool_calls.append(
        RuntimeToolCall(
            tool_name,
            envelope.status,
            error_code,
            tool_call_id=tool_call_id,
            tool_result_id=tool_result_id,
            round=runtime_context.current_tool_round,
        )
    )
    result_payload = envelope.to_dict()
    result_payload["provenance"] = record.to_model_provenance()
    return result_payload


class GetMessageContextSDKToolAdapter:
    """把 get_message_context 接入现有 Runtime/Trace/Evidence 主链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self) -> Any:
        """创建只接受稳定 message_id 和 bounded 窗口的 Function Tool。"""

        description = (
            "Recover a larger but still bounded same-conversation context around one message_id "
            "returned by lexical_search or semantic_search. Call only when the search result's local "
            "context is insufficient; do not call this mechanically for every hit. It never crosses "
            "the trusted session/time scope and may return truncated=true."
        )

        @function_tool(
            name_override="get_message_context",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def get_message_context(
            context: RunContextWrapper[RuntimeContext],
            message_id: str,
            context_before: int = 8,
            context_after: int = 8,
        ) -> dict[str, object]:
            """恢复已由 Search 结果公开的 stable message locator。"""

            runtime_context, tool_call_id, trace_context = _tool_runtime_context(context, "get_message_context")
            try:
                request = GetMessageContextInput(
                    message_id=message_id,
                    context_before=context_before,
                    context_after=context_after,
                )
            except CapabilityContractError as exc:
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "get_message_context", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                try:
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        "get_message_context",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "get_message_context",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise
            return _append_runtime_tool_result(runtime_context, "get_message_context", tool_call_id, envelope)

        return get_message_context


class FindMembersSDKToolAdapter:
    """把 find_members 的候选/歧义结果接入同一 ToolResultRecord。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建 scope-bounded member lookup Function Tool。"""

        if trusted_max_results is not None:
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        # provider 省略 limit 时也必须落在当前 scope 内，不能使用静态 20 触发无意义的 contract round。
        default_limit = 20 if trusted_max_results is None else min(20, trusted_max_results)

        description = (
            "Find candidate members by nickname, group card, username/display name, alias-like "
            "remark, platform user ID, or UIN. Use before filtering retrieval by a person when the "
            "identity is unclear. Return candidates and matching reasons; multiple candidates are "
            "normal, so do not claim a unique person without resolving the ambiguity."
        )
        if trusted_max_results is not None:
            description += f" The current trusted candidate limit is {trusted_max_results}."

        @function_tool(
            name_override="find_members",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def find_members(
            context: RunContextWrapper[RuntimeContext],
            query: str,
            session_ids: list[str] | None = None,
            limit: int = default_limit,
        ) -> dict[str, object]:
            """只将模型身份查询字段转换成 FindMembersInput。"""

            runtime_context, tool_call_id, trace_context = _tool_runtime_context(context, "find_members")
            try:
                request = FindMembersInput(
                    query=query,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    limit=limit,
                )
            except CapabilityContractError as exc:
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "find_members", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                if runtime_context.capability_registry is not self.registry:
                    raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                try:
                    envelope = runtime_context.capability_registry.invoke(
                        "find_members",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "find_members",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise
            return _append_runtime_tool_result(runtime_context, "find_members", tool_call_id, envelope)

        if trusted_max_results is not None:
            schema = getattr(find_members, "params_json_schema", None)
            if not isinstance(schema, dict):
                raise TypeError("SDK Function Tool did not expose params_json_schema")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("SDK Function Tool schema did not expose properties")
            limit_schema = properties.get("limit")
            if not isinstance(limit_schema, dict):
                raise TypeError("find_members schema did not expose limit")
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = trusted_max_results
            limit_schema["default"] = min(20, trusted_max_results)

        return find_members


class GetSchemaSDKToolAdapter:
    """把 public Physical SQLite schema inspection 接入同一 Runtime/Evidence 链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self) -> Any:
        """创建无模型参数的 schema inspection Function Tool。"""

        description = (
            "Inspect the exposed physical canonical SQLite schema before writing SQL. "
            "Returns public tables, columns, and relationships only; it does not return message rows, "
            "does not change the trusted scope, and does not expose internal ingestion or derived tables. "
            "Call this when the available table or column names are not already known."
        )

        @function_tool(
            name_override="get_schema",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def get_schema(context: RunContextWrapper[RuntimeContext]) -> dict[str, object]:
            """读取 schema；模型不能通过参数选择未公开的表或列。"""

            runtime_context, tool_call_id, trace_context = _tool_runtime_context(context, "get_schema")
            try:
                request = GetSchemaInput()
            except CapabilityContractError as exc:
                # 保留统一 contract envelope，未知异常仍不会被吞掉。
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "get_schema", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                try:
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        "get_schema",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "get_schema",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise
            return _append_runtime_tool_result(runtime_context, "get_schema", tool_call_id, envelope)

        return get_schema


class ExecuteSQLSDKToolAdapter:
    """把原始 read-only SQL 接入 trusted scope、bounded result 和现有 evidence。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建 provider-facing SQL tool；最终权限仍由 Capability/SQLite adapter enforcement。"""

        if trusted_max_results is not None:
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        description = (
            "Execute one read-only SQL statement against the exposed canonical SQLite tables for exact "
            "counts, GROUP BY, time-range totals, sender/session aggregation, and other deterministic "
            "structured questions. Call get_schema first when table or column names are uncertain. "
            "The trusted session/time scope is enforced by the tool and cannot be expanded by SQL WHERE. "
            "Do not add a LIMIT just for safety; max_rows is bounded by the tool. Writes, DDL, ATTACH, "
            "PRAGMA, internal tables, and scope escape are rejected. No query rewrite or retrieval fallback "
            "is performed. Respect returned_rows and truncated in the result when citing rows."
        )
        if trusted_max_results is not None:
            description += f" The current trusted maximum result rows is {trusted_max_results}."

        @function_tool(
            name_override="execute_sql",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def execute_sql(
            context: RunContextWrapper[RuntimeContext],
            sql: str,
            max_rows: int | None = None,
        ) -> dict[str, object]:
            """执行一条模型 SQL；scope 不从 SQL 文本或模型参数读取。"""

            runtime_context, tool_call_id, trace_context = _tool_runtime_context(context, "execute_sql")
            try:
                request = ExecuteSQLInput(sql=sql, max_rows=max_rows)
            except CapabilityContractError as exc:
                # 参数形状错误返回可诊断 envelope，不静默改写 SQL。
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "execute_sql", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=f"tool:{tool_call_id}",
                        ),
                    )
            else:
                try:
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        "execute_sql",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "execute_sql",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise
            return _append_runtime_tool_result(runtime_context, "execute_sql", tool_call_id, envelope)

        if trusted_max_results is not None:
            # Provider schema 只是减少无效调用；Capability 仍使用 trusted scope 再次判断上限。
            schema = getattr(execute_sql, "params_json_schema", None)
            if not isinstance(schema, dict):
                raise TypeError("SDK Function Tool did not expose params_json_schema")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("SDK Function Tool schema did not expose properties")
            max_rows_schema = properties.get("max_rows")
            if not isinstance(max_rows_schema, dict):
                raise TypeError("execute_sql schema did not expose max_rows")
            max_rows_schema["minimum"] = 1
            max_rows_schema["maximum"] = trusted_max_results

        return execute_sql
