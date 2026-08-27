"""把 lexical/semantic retrieval 映射为独立的 OpenAI Agents SDK Function Tool。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from agents import RunContextWrapper, function_tool

from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecuteSQLInput,
    FindMembersInput,
    GetMessageContextInput,
    GetRecentMessagesInput,
    GetSchemaInput,
    SearchMessagesInput,
    SemanticSearchInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.registry import CapabilityRegistry
from trivae.config.limits import (
    DEFAULT_LEXICAL_RESULT_LIMIT,
    DEFAULT_MEMBER_RESULT_LIMIT,
    DEFAULT_RECENT_MESSAGES_LIMIT,
    DEFAULT_SEMANTIC_RESULT_LIMIT,
    MAX_LEXICAL_RESULT_LIMIT,
    MAX_MEMBER_RESULT_LIMIT,
    MAX_RECENT_MESSAGES_LIMIT,
    MAX_SEMANTIC_RESULT_LIMIT,
)
from trivae.observability.contracts import FailureInfo
from trivae.query.evidence import build_tool_result_record, project_tool_result_for_model
from trivae.query.runtime.budget import ToolResultBudgetCall
from trivae.query.runtime.contracts import RuntimeContext, RuntimeToolCall
from trivae.retrieval.sql import MAX_SQL_RESULT_ROWS

if TYPE_CHECKING:
    # 仅类型引用，避免与 observability.collector 的运行时依赖成环。
    from trivae.observability.collector import TraceOperationContext


def _contract_error_envelope(error: CapabilityContractError) -> ToolEnvelope:
    """将 SDK 参数解码阶段产生的已知 contract 错误投影为统一 envelope。"""

    return ToolEnvelope(
        status="error",
        data=None,
        meta={"truncated": False},
        error=ToolError(code=error.error_code, message=str(error)),
    )


def _model_projection_metrics(
    payload: dict[str, object],
) -> tuple[int | None, bool | None, int | None, int | None, int | None, int | None]:
    """读取 Host projection 的 estimate、可见消息数和各类 omission。"""

    metrics = payload.get("model_projection")
    if not isinstance(metrics, dict):
        return None, None, None, None, None, None
    estimated_tokens = metrics.get("estimated_tokens")
    truncated = metrics.get("truncated")
    omitted_context = metrics.get("omitted_context_messages")
    omitted_hits = metrics.get("omitted_hit_messages")
    projected_messages = metrics.get("projected_messages")
    omitted_messages = metrics.get("omitted_messages")
    return (
        estimated_tokens if isinstance(estimated_tokens, int) and not isinstance(estimated_tokens, bool) else None,
        truncated if isinstance(truncated, bool) else None,
        omitted_context
        if isinstance(omitted_context, int) and not isinstance(omitted_context, bool)
        else None,
        omitted_hits if isinstance(omitted_hits, int) and not isinstance(omitted_hits, bool) else None,
        projected_messages
        if isinstance(projected_messages, int) and not isinstance(projected_messages, bool)
        else None,
        omitted_messages
        if isinstance(omitted_messages, int) and not isinstance(omitted_messages, bool)
        else None,
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
                "When filtering by a person, sender_user_ids must contain the canonical user_id from "
                "find_members, never a QQ number/UIN, nickname, group card, or display name. "
                "keyword must be exactly one non-empty string. "
                "Omit optional filters, or use null; do not send empty arrays. "
                "limit must be a positive integer within the current trusted result limit. "
                "For a broad inventory or resource-list question, set limit to the current trusted maximum, not a smaller convenience value. "
                "context_before and context_after must be non-negative integers. "
                "Use the short source_id handle from the current Tool Result for each citation; do not copy full provenance."
            )
        else:
            # legacy 名称保留原 contract，并明确它不是正常 Agent surface 的 canonical 名称。
            description = (
                "Legacy compatibility entry point for exact lexical search in Trivae messages, "
                "with a bounded local context window. Prefer lexical_search for the normal Agent surface. "
                "When filtering by a person, sender_user_ids must contain the canonical user_id from "
                "find_members, never a QQ number/UIN, nickname, group card, or display name. "
                "keyword must be exactly one non-empty string. "
                "Omit optional filters, or use null; do not send empty arrays. "
                "limit must be a positive integer within the current trusted result limit. "
                "context_before and context_after must be non-negative integers. "
                "Use the short source_id handle from the current Tool Result for each citation; do not copy full provenance."
            )
        if trusted_max_results is not None:
            # 让 schema 与描述同时携带动态 bound，减少模型先生成越界 limit 再恢复的无效回合。
            description += (
                f" The current lexical result limit is {min(trusted_max_results, MAX_LEXICAL_RESULT_LIMIT)}. For broad inventory or resource-list"
                f" recall, pass limit={min(trusted_max_results, MAX_LEXICAL_RESULT_LIMIT)} exactly; do not use a smaller limit such as 20 or 30."
            )

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
            time_range: dict[str, object] | None = None,
            sender_user_ids: list[str] | None = None,
            message_types: list[str] | None = None,
            limit: int = DEFAULT_LEXICAL_RESULT_LIMIT,
            context_before: int = 2,
            context_after: int = 2,
        ) -> dict[str, object]:
            """只接受 typed 字段；scope、registry 和 call identity 都来自 local context。

            Args:
                keyword: Exactly one non-empty search string, not an array.
                session_ids: Optional non-empty session ID array; use null when unused.
                start_timestamp: Optional integer inclusive lower bound in milliseconds.
                end_timestamp: Optional integer exclusive upper bound in milliseconds.
                time_range: Optional relative range object anchored to archive_latest; Host resolves absolute timestamps.
                sender_user_ids: Optional non-empty canonical user_id array from find_members; use null when unused. Never pass a QQ number/UIN, nickname, group card, or display name.
                message_types: Optional non-empty message type array; use null when unused.
                limit: Positive result count not greater than the trusted result limit.
                context_before: Non-negative number of messages before each hit.
                context_after: Non-negative number of messages after each hit.
            """

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                self.tool_name,
            )

            try:
                # 只把模型可控的搜索字段转换为既有业务 input；scope 不从模型参数读取。
                request = SearchMessagesInput(
                    keyword=keyword,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    time_range=time_range,
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": self.tool_name, "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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

            # 这里记录一次 tool call；同一模型回合的多个调用由 Runtime hook 统一计为一轮。
            return _append_runtime_tool_result(
                runtime_context,
                self.tool_name,
                tool_call_id,
                envelope,
                budget_call,
            )

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
            # Provider schema 只展示 lexical 自己的 hard cap；Capability 仍会再次检查 scope。
            effective_maximum = min(trusted_max_results, MAX_LEXICAL_RESULT_LIMIT)
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = min(DEFAULT_LEXICAL_RESULT_LIMIT, effective_maximum)

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
            "When filtering by a person, sender_user_ids must contain the canonical user_id from "
            "find_members, never a QQ number/UIN, nickname, group card, or display name. "
            "Omit optional filters, or use null; do not send empty arrays. "
            "The semantic index must be explicitly built and may report partial coverage."
            " For a broad inventory or resource-list question, set limit to the current trusted maximum, not a smaller convenience value."
        )
        if trusted_max_results is not None:
            description += (
                f" The current semantic result limit is {min(trusted_max_results, MAX_SEMANTIC_RESULT_LIMIT)}. For broad inventory or resource-list"
                f" recall, pass limit={min(trusted_max_results, MAX_SEMANTIC_RESULT_LIMIT)} exactly; do not use a smaller limit such as 20 or 30."
            )

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
            time_range: dict[str, object] | None = None,
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

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "semantic_search",
            )

            try:
                request = SemanticSearchInput(
                    query=query,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    time_range=time_range,
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "semantic_search", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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

            # semantic candidate details 与 citation bookkeeping 分离，避免重复复制 full message provenance。
            return _append_runtime_tool_result(
                runtime_context,
                "semantic_search",
                tool_call_id,
                envelope,
                budget_call,
            )

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
            # semantic 不继承 lexical umbrella，schema maximum 固定收紧到 20。
            effective_maximum = min(trusted_max_results, MAX_SEMANTIC_RESULT_LIMIT)
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = min(DEFAULT_SEMANTIC_RESULT_LIMIT, effective_maximum)

        return semantic_search


def _tool_runtime_context(
    context: RunContextWrapper[RuntimeContext],
    tool_name: str,
) -> tuple[RuntimeContext, str, TraceOperationContext | None, ToolResultBudgetCall]:
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
        # trace 树的 Tool 节点直接使用 Trivae-owned call id 命名。
        # 这样 normalized tool.call.* facts 与 RuntimeEvent 携带同一 identity 字符串，
        # 下游（TUI projection 等）不需要任何跨源格式翻译，也不会出现同调用的重复行。
        trace_context = child(tool_call_id)
    if tool_name not in runtime_context.available_capabilities:
        # Tool 不可见时属于 Runtime invariant failure，不能返回普通 Agent 可恢复结果。
        raise RuntimeError(f"{tool_name} was invoked outside the allowed capability set")
    # 预留发生在 capability invoke 前，确保同一 run 的并发/连续 Tool 调用不会重置共享池。
    budget_call = runtime_context.tool_result_budget_policy.begin_call()
    return runtime_context, tool_call_id, trace_context, budget_call


def _append_runtime_tool_result(
    runtime_context: RuntimeContext,
    tool_name: str,
    tool_call_id: str,
    envelope: ToolEnvelope,
    budget_call: ToolResultBudgetCall,
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
    result_payload = project_tool_result_for_model(
        envelope,
        record,
        token_budget=budget_call.effective_per_call_budget,
    )
    (
        model_result_estimated_tokens,
        model_result_truncated,
        model_result_omitted_context_messages,
        model_result_omitted_hit_messages,
        model_result_projected_messages,
        model_result_omitted_messages,
    ) = _model_projection_metrics(result_payload)
    if (
        model_result_estimated_tokens is None
        or model_result_truncated is None
        or model_result_omitted_context_messages is None
        or model_result_omitted_hit_messages is None
        or model_result_projected_messages is None
        or model_result_omitted_messages is None
    ):
        raise RuntimeError("model projection did not expose complete budget metrics")
    budget_snapshot = runtime_context.tool_result_budget_policy.complete_call(
        budget_call,
        projected_tool_result_tokens=model_result_estimated_tokens,
        truncated=model_result_truncated,
        omitted_context_messages=model_result_omitted_context_messages,
        omitted_hit_messages=model_result_omitted_hit_messages,
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
            model_result_estimated_tokens=model_result_estimated_tokens,
            model_result_truncated=model_result_truncated,
            model_result_omitted_context_messages=model_result_omitted_context_messages,
            model_result_omitted_hit_messages=model_result_omitted_hit_messages,
            model_result_projected_messages=model_result_projected_messages,
            model_result_omitted_messages=model_result_omitted_messages,
            tool_result_budget=budget_snapshot,
        )
    )
    return result_payload


class GetMessageContextSDKToolAdapter:
    """把 get_message_context 接入现有 Runtime/Trace/Evidence 主链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self) -> Any:
        """创建接受 legacy message_id 或当前 Tool Result source_id 的 bounded context tool。"""

        description = (
            "Recover a larger but still bounded same-conversation context around one message_id or source_id "
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
            message_id: str | None = None,
            source_id: str | None = None,
            context_before: int = 8,
            context_after: int = 8,
        ) -> dict[str, object]:
            """恢复由 Search 结果公开的 source handle，兼容旧的 canonical message_id。"""

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "get_message_context",
            )
            try:
                if message_id is not None and source_id is not None:
                    raise CapabilityContractError("message_id and source_id cannot both be provided")
                resolved_message_id = (
                    runtime_context.resolve_message_source_handle(source_id)
                    if source_id is not None
                    else message_id
                )
                if not isinstance(resolved_message_id, str):
                    raise CapabilityContractError("message_id or source_id is required")
                request = GetMessageContextInput(
                    message_id=resolved_message_id,
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "get_message_context", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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
            return _append_runtime_tool_result(
                runtime_context,
                "get_message_context",
                tool_call_id,
                envelope,
                budget_call,
            )

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
        effective_maximum = MAX_MEMBER_RESULT_LIMIT if trusted_max_results is None else min(
            trusted_max_results, MAX_MEMBER_RESULT_LIMIT
        )
        default_limit = min(DEFAULT_MEMBER_RESULT_LIMIT, effective_maximum)

        description = (
            "Find candidate members by nickname, group card, username/display name, alias-like "
            "remark, platform user ID, or UIN. Use before filtering retrieval by a person when the "
            "identity is unclear. Return candidates and matching reasons; multiple candidates are "
            "normal, so do not claim a unique person without resolving the ambiguity. Use the "
            "returned candidate's canonical user_id for sender_user_ids; never pass its UIN or display name."
        )
        if trusted_max_results is not None:
            description += f" The current member candidate limit is {min(trusted_max_results, MAX_MEMBER_RESULT_LIMIT)}."

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

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "find_members",
            )
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "find_members", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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
            return _append_runtime_tool_result(
                runtime_context,
                "find_members",
                tool_call_id,
                envelope,
                budget_call,
            )

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
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = default_limit

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

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "get_schema",
            )
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "get_schema", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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
            return _append_runtime_tool_result(
                runtime_context,
                "get_schema",
                tool_call_id,
                envelope,
                budget_call,
            )

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
            "PRAGMA, internal tables, and scope escape are rejected. For sender statistics, filter "
            "messages.sender_user_id by canonical users.user_id; a QQ UIN belongs to users.platform_uin "
            "and must be resolved through users rather than compared directly to messages.sender_user_id. "
            "No query rewrite or retrieval fallback is performed. Respect returned_rows and truncated in the result when citing rows."
        )
        if trusted_max_results is not None:
            description += f" The current SQL result row limit is {min(trusted_max_results, MAX_SQL_RESULT_ROWS)}."

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

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "execute_sql",
            )
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
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "execute_sql", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
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
            return _append_runtime_tool_result(
                runtime_context,
                "execute_sql",
                tool_call_id,
                envelope,
                budget_call,
            )

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
            max_rows_schema["maximum"] = min(trusted_max_results, MAX_SQL_RESULT_ROWS)

        return execute_sql


class GetRecentMessagesSDKToolAdapter:
    """把 get_recent_messages 的 typed temporal browsing 输入接入同一主链路。"""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建 temporal browsing Function Tool；scope 仍由 RuntimeContext 注入。"""

        if trusted_max_results is not None:
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        effective_maximum = (
            MAX_RECENT_MESSAGES_LIMIT if trusted_max_results is None else min(
                trusted_max_results, MAX_RECENT_MESSAGES_LIMIT
            )
        )
        default_limit = min(DEFAULT_RECENT_MESSAGES_LIMIT, effective_maximum)

        description = (
            "Read the most recent messages inside a time range for temporal browsing: use it as the "
            "first call when the candidate set is determined mainly by time and the user asks for an "
            "overview, summary, topic discovery, or what people talked about recently (for example "
            "'最近两天聊了什么', '最近有什么值得看的', '昨天发生了什么'). Do NOT guess topics and search "
            "them with lexical_search or semantic_search for this kind of question; read the real "
            "recent window first, then analyze and cite. Calling it without any time argument defaults "
            "to the most recent 2 days anchored at archive_latest (never machine current time). The "
            "tool returns the latest `limit` canonical messages of the resolved window in natural "
            "chronological reading order, plus returned/total counts and truncated. Zero results is a "
            "normal outcome when the window truly has no messages. Prefer limit at or near the schema "
            "maximum for broad recent-activity questions so a two-day overview is not needlessly "
            "partial. If has_more is true, call this tool again with the exact next_cursor returned "
            "by the host; the cursor keeps the original absolute window and session scope, and must not "
            "be edited or combined with a new time range. Do not repeat a cursor already used. The "
            "trusted session/time scope is enforced by the host and cannot be expanded by arguments. "
            "When the question contains a "
            "precise lexical target such as a URL, repository name, code identifier, error message, "
            "nickname, or exact phrase, use lexical_search instead; for concept paraphrases without "
            "precise wording use semantic_search."
        )

        @function_tool(
            name_override="get_recent_messages",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def get_recent_messages(
            context: RunContextWrapper[RuntimeContext],
            time_range: dict[str, object] | None = None,
            start_timestamp: int | None = None,
            end_timestamp: int | None = None,
            session_ids: list[str] | None = None,
            cursor: dict[str, object] | None = None,
            limit: int = default_limit,
        ) -> dict[str, object]:
            """只接受 typed 时间窗字段；trusted scope 不从模型参数读取。

            Args:
                time_range: Relative range object anchored to archive_latest, e.g.
                    {"kind":"relative","amount":2,"unit":"day","anchor":"archive_latest"};
                    Host resolves absolute timestamps and records them in Trace.
                start_timestamp: Optional integer inclusive lower bound in milliseconds;
                    cannot be combined with time_range.
                end_timestamp: Optional integer exclusive upper bound in milliseconds;
                    cannot be combined with time_range.
                session_ids: Optional non-empty session ID array; use null when unused.
                cursor: Optional host-issued continuation cursor. When present, pass it back exactly;
                    do not combine it with time_range or edit its scope/position.
                limit: Positive message count no greater than the trusted result bound.
            """

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "get_recent_messages",
            )
            try:
                request = GetRecentMessagesInput(
                    time_range=time_range,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    session_ids=None if session_ids is None else tuple(session_ids),
                    cursor=cursor,
                    limit=limit,
                )
            except CapabilityContractError as exc:
                envelope = _contract_error_envelope(exc)
                if trace_context is not None:
                    cast(Any, trace_context).emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=trace_context.operation_id,
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "get_recent_messages", "error_code": exc.error_code},
                        failure=FailureInfo(
                            error_code=exc.error_code,
                            origin_stage="tool",
                            observed_stage="tool",
                            category="contract",
                            handling="returned_to_agent",
                            cause_operation_id=trace_context.operation_id,
                        ),
                    )
            else:
                try:
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        "get_recent_messages",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "get_recent_messages",
                            "failed",
                            tool_call_id=tool_call_id,
                            round=runtime_context.current_tool_round,
                        )
                    )
                    raise
            return _append_runtime_tool_result(
                runtime_context,
                "get_recent_messages",
                tool_call_id,
                envelope,
                budget_call,
            )

        if trusted_max_results is not None:
            # 与其他工具一致：provider schema 只表达当前 dynamic bound，真实 enforcement 在 Capability。
            schema = getattr(get_recent_messages, "params_json_schema", None)
            if not isinstance(schema, dict):
                raise TypeError("SDK Function Tool did not expose params_json_schema")
            properties = schema.get("properties")
            if not isinstance(properties, dict):
                raise TypeError("SDK Function Tool schema did not expose properties")
            limit_schema = properties.get("limit")
            if not isinstance(limit_schema, dict):
                raise TypeError("get_recent_messages schema did not expose limit")
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = default_limit

        return get_recent_messages
