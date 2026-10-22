"""把 lexical/semantic retrieval 映射为独立的 OpenAI Agents SDK Function Tool。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, cast

from agents import RunContextWrapper, function_tool
from agents.exceptions import ModelBehaviorError
from agents.tool_context import ToolContext
from pydantic import Field

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
from trivae.query.evidence import ToolResultProjectionError, build_tool_result_record, project_tool_result_for_model
from trivae.query.runtime.budget import ToolResultBudgetCall, ToolResultBudgetExhausted
from trivae.query.runtime.contracts import RuntimeContext, RuntimeToolCall
from trivae.retrieval.sql import MAX_SQL_RESULT_ROWS, SQL_QUERY_TIMEOUT_SECONDS

if TYPE_CHECKING:
    # 仅类型引用，避免与 observability.collector 的运行时依赖成环。
    from trivae.observability.collector import TraceOperationContext


def _budget_stop_envelope(reason: str = "ToolResultBudgetExhausted") -> ToolEnvelope:
    """预算限制是显式工具错误，绝不能伪装成检索零结果。"""

    return ToolEnvelope(
        status="error", data=None,
        meta={"truncated": False, "budget_failure_type": reason},
        error=ToolError(
            code="TOOL_RESULT_BUDGET_EXHAUSTED",
            message="Tool Result budget exhausted. Use existing evidence and state this limitation.",
        ),
    )


def minimum_budget_stop_tokens(context: RuntimeContext, name: str, call_id: str) -> int:
    """用真实投影器计算控制结果开销，避免手写一个与协议漂移的 Token 常数。"""

    envelope = _budget_stop_envelope()
    record = build_tool_result_record(
        run_id=context.run_id, tool_call_id=call_id, tool_result_id=f"{call_id}/result",
        tool_name=name, envelope=envelope, scope=context.scope,
    )
    payload = project_tool_result_for_model(
        envelope, record, token_budget=context.tool_result_budget_policy.config.per_call_ceiling,
    )
    metrics = cast(dict[str, Any], payload["model_projection"])
    return cast(int, metrics["estimated_tokens"])


def reserve_budget_stop_results(context: RuntimeContext, calls: list[tuple[str, str]]) -> None:
    """执行同轮任何调用前，为全部调用保留可返回的控制结果。"""

    if context.tool_result_budget_policy.config.mode == "fixed":
        return
    required: list[tuple[str, int]] = []
    for name, provider_id in calls:
        # 与后续 SDK hooks 共用映射；预分配不会导致同一调用出现两个 identity。
        call_id = context.resolve_tool_call_id(provider_id)
        minimum = minimum_budget_stop_tokens(context, name, call_id)
        required.append((call_id, minimum))
    remaining = context.tool_result_budget_policy.remaining_run_tool_evidence_budget
    total = sum(minimum for _, minimum in required)
    if remaining is not None and total > remaining:
        # 同步准入先核对整轮总额；拒绝时既不执行工具，也不遗留半轮控制预留。
        raise ToolResultBudgetExhausted(
            f"Tool Result batch requires {total} control tokens; available {remaining}"
        )
    for call_id, minimum in required:
        context.budget_stop_reservations[call_id] = context.tool_result_budget_policy.begin_call(
            minimum_budget=minimum, maximum_budget=minimum,
        )
    if len(calls) > 1 and all(name == "get_recent_messages" for name, _ in calls):
        # 控制结果已逐个预留；这里只均分本轮剩余的数据额度，不扩大共享池。
        available = context.tool_result_budget_policy.remaining_run_tool_evidence_budget
        if available is not None:
            # 固定每窗上限，避免执行顺序影响哪个时间段能获得证据。
            per_window = max(1, available // len(calls))
            context.temporal_result_budget_limits.update({call_id: per_window for call_id, _ in required})


def protect_tool_result_budget(tool: Any) -> None:
    """在 SDK 调用边界闭合预算失败；不改变 Capability 的业务职责。"""

    invoke = tool.on_invoke_tool

    async def invoke_with_budget(context: Any, arguments: str) -> object:
        """控制预留独立于数据预留，失败数据投影释放后仍能返回合法工具错误。"""

        runtime = context.context
        call_id = runtime.resolve_tool_call_id(getattr(context, "tool_call_id", None))
        control = runtime.budget_stop_reservations.get(call_id)
        if control is None:
            # fixed 模式以及直接 SDK adapter 调用保持原有显式失败合同。
            return await invoke(context, arguments)
        policy = runtime.tool_result_budget_policy
        remaining = policy.remaining_run_tool_evidence_budget
        reason = "ToolResultBudgetExhausted"
        if not runtime.tool_result_budget_exhausted and remaining is not None and remaining >= control.effective_per_call_budget:
            try:
                result = await invoke(context, arguments)
            except (ToolResultProjectionError, ToolResultBudgetExhausted) as exc:
                # _append 已释放未发送的数据预留；只把真实投影失败转换为预算控制结果。
                reason = type(exc).__name__
            except Exception:
                # 无关异常继续显式抛出，不能把能力/参数/存储错误当成预算停止。
                policy.cancel_call(control)
                runtime.budget_stop_reservations.pop(call_id)
                raise
            else:
                return result
        # 剩余数据预算不足时不运行 Capability；同轮后续调用也会获得自己的控制结果。
        runtime.tool_result_budget_exhausted = True
        if runtime.trace_context is not None:
            # 预算控制事实独立于 Capability 检索事实，保留根因与是否执行，避免错误被视为零召回。
            trace = runtime.trace_context.child(call_id)
            trace.emit(
                stage="runtime", operation="runtime.tool.budget_stopped", phase="failed",
                operation_id=trace.operation_id, parent_operation_id=trace.parent_operation_id,
                outcome="error", payload={
                    "tool_name": tool.name, "budget_failure_type": reason,
                    "capability_executed": reason == "ToolResultProjectionError",
                    "remaining_data_budget": policy.remaining_run_tool_evidence_budget,
                },
                failure=FailureInfo(
                    error_code="TOOL_RESULT_BUDGET_EXHAUSTED", origin_stage="runtime",
                    observed_stage="runtime", category="budget", handling="returned_to_agent",
                    cause_operation_id=trace.operation_id,
                ),
            )
        return _append_runtime_tool_result(runtime, tool.name, call_id, _budget_stop_envelope(reason), control)

    tool.on_invoke_tool = invoke_with_budget


def _contract_error_envelope(error: CapabilityContractError) -> ToolEnvelope:
    """将 SDK 参数解码阶段产生的已知 contract 错误投影为统一 envelope。"""

    return ToolEnvelope(
        status="error",
        data=None,
        meta={"truncated": False},
        error=ToolError(code=error.error_code, message=str(error)),
    )


def _clamp_context_window(
    runtime_context: RuntimeContext,
    context_before: int,
    context_after: int,
) -> tuple[int, int]:
    """按 trusted context window 上限钳制模型可控的邻居窗口。

    ``context_window_limit`` 是 evaluation-only override（ExecutionOverride 传入）；
    None 表示生产默认行为，不做任何修改。get_message_context 的显式 deepening
    不走该钳制，其可用性由 available_capabilities 控制。
    """

    limit = runtime_context.context_window_limit
    if limit is None:
        return context_before, context_after
    return min(context_before, limit), min(context_after, limit)


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

        # 共用factory先计算公开默认值，canonical/legacy省略参数时都执行同一scope内值。
        effective_maximum = MAX_LEXICAL_RESULT_LIMIT if trusted_max_results is None else min(
            trusted_max_results, MAX_LEXICAL_RESULT_LIMIT
        )
        default_limit = min(DEFAULT_LEXICAL_RESULT_LIMIT, effective_maximum)
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
                "For an explicit broad inventory or resource-list question, set limit to the current trusted maximum, not a smaller convenience value. "
                "For an explicit resource inventory, a non-empty github.com result is sufficient for URL-bearing recall: do not call get_recent_messages or execute_sql to enumerate or recount the same resources. "
                "A generic learning-material inventory may add one semantic_search for non-URL materials, but must not prefetch a broad recent window; a discussion question about one recommendation should keep its named anchor and use context instead of this inventory rule. "
                "Do not apply the github.com-first inventory rule merely because a discussion message contains a link. "
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
            # SDK公开并拒绝空filter数组；省略/null仍沿用原Host scope继承。
            session_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            start_timestamp: int | None = None,
            end_timestamp: int | None = None,
            time_range: dict[str, object] | None = None,
            sender_user_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            message_types: Annotated[list[str] | None, Field(min_length=1)] = None,
            # limit 的严格类型与正值由真实SDK解析执行，拒绝bool/字符串/float的隐式转换。
            # trusted scope 上界继续由Capability验证，Schema maximum仅公开当前上限。
            limit: Annotated[int, Field(strict=True, ge=1)] = default_limit,
            # SDK先检查原始类型及非负值，避免隐式转换掩盖非法窗口参数。
            # 默认窗口仍为2；如何扩大讨论上下文继续由原Prompt策略决定。
            context_before: Annotated[int, Field(strict=True, ge=0)] = 2,
            context_after: Annotated[int, Field(strict=True, ge=0)] = 2,
        ) -> dict[str, object]:
            """只接受 typed 字段；scope、registry 和 call identity 都来自 local context。

            Args:
                keyword: Exactly one non-empty search string, not an array. Whitespace-separated terms use AND matching and need not be adjacent.
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
            context_before, context_after = _clamp_context_window(
                runtime_context, context_before, context_after
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
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = default_limit

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

        # 参数执行与Schema共用同一个默认值，避免小scope省略limit时落入固定10。
        effective_maximum = MAX_SEMANTIC_RESULT_LIMIT if trusted_max_results is None else min(
            trusted_max_results, MAX_SEMANTIC_RESULT_LIMIT
        )
        default_limit = min(DEFAULT_SEMANTIC_RESULT_LIMIT, effective_maximum)
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
            # SDK公开并执行原非空字符串约束；非空白判断仍由SemanticSearchInput负责。
            query: Annotated[str, Field(
                strict=True, min_length=1, description="One non-empty semantic query string."
            )],
            # SDK公开并执行原非空数组约束，omit/null继续保留Host scope语义。
            session_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            start_timestamp: int | None = None,
            end_timestamp: int | None = None,
            time_range: dict[str, object] | None = None,
            # 这里只约束数组形状；canonical身份与授权仍由原Host执行。
            sender_user_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            message_types: Annotated[list[str] | None, Field(min_length=1)] = None,
            source_message_id: str | None = None,
            reply_to_source_message_id: str | None = None,
            # SDK拒绝原始非法类型；省略值使用上方按scope推导的公开默认值。
            limit: Annotated[int, Field(strict=True, ge=1)] = default_limit,
            # 非负整数在SDK解析时直接校验，保留默认2/2及Host原有窗口语义。
            context_before: Annotated[int, Field(strict=True, ge=0)] = 2,
            context_after: Annotated[int, Field(strict=True, ge=0)] = 2,
            # 候选数先由SDK检查严格正整数，保留原默认40与既有检索算法。
            # 字段描述公开原Prompt参数约束；Host仍保留业务入口校验。
            dense_top_k: Annotated[int, Field(
                strict=True, ge=1, description="Positive integer count of dense candidates before reranking."
            )] = 40,
        ) -> dict[str, object]:
            """将模型字段投影为 SemanticSearchInput，scope 仍由 RuntimeContext 注入。"""

            runtime_context, tool_call_id, trace_context, budget_call = _tool_runtime_context(
                context,
                "semantic_search",
            )
            context_before, context_after = _clamp_context_window(
                runtime_context, context_before, context_after
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
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = effective_maximum
            limit_schema["default"] = default_limit

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
    minimum = minimum_budget_stop_tokens(runtime_context, tool_name, tool_call_id)
    # 时间窗批次使用Host分配的份额；单次及其他工具沿用原有上限。
    maximum = runtime_context.temporal_result_budget_limits.pop(tool_call_id, None)
    budget_call = runtime_context.tool_result_budget_policy.begin_call(minimum_budget=minimum, maximum_budget=maximum)
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
    try:
        result_payload = project_tool_result_for_model(
            envelope,
            record,
            token_budget=budget_call.effective_per_call_budget,
        )
    except ToolResultProjectionError:
        # 模型没有收到失败投影；退回预留，再由 SDK 边界决定返回控制结果或显式终止。
        runtime_context.tool_result_budget_policy.cancel_call(budget_call)
        raise
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
    # 未执行Capability而直接返回预算控制结果时，也完成该窗口份额的生命周期。
    runtime_context.temporal_result_budget_limits.pop(tool_call_id, None)
    control = runtime_context.budget_stop_reservations.pop(tool_call_id, None)
    if control is not None and control != budget_call:
        # 数据投影已成功，可以先退回本调用控制预留，再生成准确的结算快照。
        runtime_context.tool_result_budget_policy.cancel_call(control)
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
            "Recover a larger but still bounded same-conversation context around one returned message. "
            "Prefer source_id for a run-local mN-K handle (for example m1-1) from a ToolResult. "
            "Use message_id only for a canonical internal message ID, never for a source handle. "
            "Provide exactly one identity parameter. Call only when the search result's local "
            "context is insufficient, especially when a hit is a question and the user asks about a "
            "reply, later reaction, recommendation, or material that followed. The context_before and "
            "context_after parameters are message counts, not minutes or seconds; a small window cannot "
            "prove that nobody replied. It never crosses the trusted session/time scope and may return "
            "truncated=true."
            " Set include_replies=true to retrieve explicit direct replies even when they are far outside "
            "the neighbor window; replies take priority within the same total result bound. "
            "With context_before=0 and context_after=0, return only the anchor and its direct replies. "
            "This follows exported reply links, not all possible reactions or recursive reply threads."
        )

        @function_tool(
            name_override="get_message_context",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def get_message_context(
            context: RunContextWrapper[RuntimeContext],
            # 字段说明进入 SDK/Pydantic 生成的真实 schema；短 handle 必须显式填 source_id。
            source_id: Annotated[str | None, Field(description=(
                "A run-local message source handle in mN-K form, for example m1-1 or m2-3, "
                "copied exactly from a current ToolResult source_id. Prefer this parameter for returned messages. "
                "Provide source_id or message_id, never both."
            ))] = None,
            # canonical ID 保持原有直接查询能力，不将误填的 handle 静默转换成别名。
            message_id: Annotated[str | None, Field(description=(
                "Legacy canonical internal message ID, for example qq:1039179741:7670742957499269309. "
                "Do not put a run-local mN-K source handle such as m1-1 here; use source_id for that. "
                "Provide message_id or source_id, never both."
            ))] = None,
            # SDK仅落实原非负整数契约；默认8/8、消息单位与选窗description逐字保留。
            # before+anchor+after共享上界仍由typed input执行，不新增单侧maximum。
            context_before: Annotated[int, Field(strict=True, ge=0, description=(
                "Number of messages before the anchor to include; this is a message count, not a "
                "duration in minutes or seconds. Use 0 when earlier context is unnecessary."
            ))] = 8,
            context_after: Annotated[int, Field(strict=True, ge=0, description=(
                "Number of messages after the anchor to include; this is a message count, not a "
                "duration in minutes or seconds. Increase it when checking later replies or advice; "
                "a small value cannot establish that no reply exists."
            ))] = 8,
            # 只有 Agent 明确请求回复调查时才跨越局部邻居窗口。
            include_replies: Annotated[bool, Field(strict=True, description=(
                "Retrieve explicit direct replies to the anchor in the trusted session/time scope, "
                "regardless of distance. Does not recursively follow replies. Default false."
            ))] = False,
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
                    include_replies=include_replies,
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
            # 字段公开单个非空字符串，SDK负责空串/类型；空白串仍由typed input拒绝。
            query: Annotated[str, Field(
                strict=True, min_length=1, description="One non-empty identity query string."
            )],
            # 非空数组由SDK公开执行，省略/null仍继承原trusted scope。
            session_ids: Annotated[list[str] | None, Field(
                min_length=1, description="Optional non-empty session ID array; omit when unused."
            )] = None,
            # 已公开的integer/minimum必须由SDK真正执行，不能先转换原始类型。
            # 保留按trusted scope推导的默认值；Capability继续执行授权上界。
            limit: Annotated[int, Field(strict=True, ge=1)] = default_limit,
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
            "Call this when the available table or column names are not already known. Accepts no arguments."
        )

        @function_tool(
            name_override="get_schema",
            description_override=description,
            failure_error_function=None,
            # 空参数Schema明确禁止额外属性，真实执行检查仍在下面入口完成。
            strict_mode=True,
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

        # SDK默认忽略额外字段；仅改Schema不足以落实无参数契约。
        invoke_schema = get_schema.on_invoke_tool

        async def invoke_without_arguments(
            context: ToolContext[RuntimeContext], arguments: str,
        ) -> Any:
            # 保留SDK原有空串/空对象形式；不存在降级或新的业务参数。
            try:
                parsed = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError as exc:
                # 解析错误显式暴露为SDK模型输入错误，保留原异常链便于Trace定位。
                raise ModelBehaviorError("get_schema accepts no arguments: invalid JSON") from exc
            # 必须在SDK忽略字段前拒绝，确保任何额外参数都不会到达registry。
            if parsed != {}:
                raise ModelBehaviorError("get_schema accepts no arguments")
            # 合法调用仍走原typed input、scope、registry、Evidence与Trace链路。
            return await invoke_schema(context, arguments)

        get_schema.on_invoke_tool = invoke_without_arguments
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
            "No query rewrite or retrieval fallback is performed. Never use this tool to recount URL/resource retrieval results. If a statement reports an error, do not repeat the same or a near-identical statement; use existing evidence or state the limitation. Respect returned_rows and truncated in the result when citing rows."
        )
        if trusted_max_results is not None:
            description += f" The current SQL result row limit is {min(trusted_max_results, MAX_SQL_RESULT_ROWS)}."
        # 在模型发起查询前告知真实执行限制，超时仍由SQLite而不是模型自觉遵守。
        description += f" SQL execution has a {SQL_QUERY_TIMEOUT_SECONDS:g}-second time limit; timeout is an explicit error."

        @function_tool(
            name_override="execute_sql",
            description_override=description,
            failure_error_function=None,
            strict_mode=False,
        )
        async def execute_sql(
            context: RunContextWrapper[RuntimeContext],
            sql: str,
            # 保留原始参数类型，防止SDK先把布尔、字符串或浮点数转换为整数。
            # 省略/null仍由Host推导可信上界，正整数约束在真实解析入口执行。
            max_rows: Annotated[int | None, Field(strict=True, ge=1)] = None,
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
            "'最近两天聊了什么', '昨天发生了什么'). For a repository, GitHub-link, Skill, or URL-bearing "
            "resource inventory explicitly requested as a list, even when it says '最近', use lexical_search with keyword 'github.com' as the "
            "first retrieval call instead of prefetching this broad recent window. For a generic learning-material "
            "inventory, use lexical_search for links and semantic_search for non-URL materials; do not use this "
            "tool merely to broaden an inventory after retrieval. For a discussion question about a reply, "
            "recommendation, or material, follow its returned source_id with get_message_context instead of "
            "prefetching a broad recent window. Do NOT guess topics and search "
            "them with lexical_search or semantic_search for this kind of question; read the real "
            "recent window first, then analyze and cite. Calling it without any time argument defaults "
            "to the most recent 2 days anchored at archive_latest (never machine current time). The "
            "tool returns the latest `limit` canonical messages of the resolved window in natural "
            "chronological reading order, plus returned/total counts and truncated. Zero results is a "
            # 中文注释：先读实际数量，再决定全读或分段；短时间也可能包含大量消息。
            "normal outcome when the window truly has no messages. For time-window overviews, start "
            "with limit=20 to resolve the window and total count. If the remaining messages fit the "
            "evidence budget, continue with the host cursor; otherwise inspect a few disjoint "
            "subwindows across the resolved range with modest limits, reserving room for context. "
            "Decide from the returned count and message sizes, not the duration alone: even one day "
            "can exceed the budget. Distinguish sampling from complete coverage. If has_more is true "
            "and you continue the same window, call this tool with the exact next_cursor returned "
            "by the host; the cursor keeps the original absolute window and session scope, and must not "
            "be edited or combined with a new time range. Do not repeat a cursor already used. The "
            "trusted session/time scope is enforced by the host and cannot be expanded by arguments. "
            "For a question about what one person recently discussed, first use find_members when the "
            "identity is ambiguous, then pass the returned canonical user_id in sender_user_ids; for "
            "a topic-wide recent overview, omit sender_user_ids. Never pass a display name, nickname, "
            "group card, or platform UIN as sender_user_ids. "
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
            # 只公开并执行已有非空数组约束；scope、时间和cursor逻辑原样保留。
            session_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            sender_user_ids: Annotated[list[str] | None, Field(min_length=1)] = None,
            cursor: dict[str, object] | None = None,
            # SDK在类型转换前拒绝非法limit；trusted上界继续由Capability执行。
            # default_limit仍按原scope推导，时间窗与cursor不参与本轮修改。
            limit: Annotated[int, Field(strict=True, ge=1)] = default_limit,
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
                sender_user_ids: Optional non-empty canonical user_id array from find_members; use
                    null for a topic-wide query. Never pass a display name, nickname, group card, or UIN.
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
                    # sender_user_ids 只把 find_members 的 canonical identity 传给 Capability。
                    sender_user_ids=None if sender_user_ids is None else tuple(sender_user_ids),
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
