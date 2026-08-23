"""把 search_messages 映射为唯一的 OpenAI Agents SDK Function Tool。"""

from __future__ import annotations

from typing import Any

from agents import RunContextWrapper, function_tool

from trivae.capabilities.contracts import (
    CapabilityContractError,
    SearchMessagesInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.registry import CapabilityRegistry
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

    def __init__(self, registry: CapabilityRegistry) -> None:
        self.registry = registry

    def as_sdk_tool(self, *, trusted_max_results: int | None = None) -> Any:
        """创建 SDK Function Tool；scope 和 registry 只通过 local context 注入。"""

        if trusted_max_results is not None:
            # 这里仅把本次执行的结果数量上限表达给模型，真正的 scope enforcement 仍在 Capability 内完成。
            if isinstance(trusted_max_results, bool) or not isinstance(trusted_max_results, int):
                raise TypeError("trusted_max_results must be an integer when provided")
            if trusted_max_results <= 0:
                raise ValueError("trusted_max_results must be positive when provided")

        description = (
            "Search Trivae messages with a bounded local context window. "
            "Use this when the answer needs evidence from chat messages. "
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
            name_override="search_messages",
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
            limit: int = 20,
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
            if "search_messages" not in runtime_context.available_capabilities:
                # 工具不可见时仍被调用属于 Runtime invariant，不能伪装成普通结果。
                raise RuntimeError("search_messages was invoked outside the allowed capability set")

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
                    trace_context.emit(
                        stage="tool",
                        operation="tool.call.failed",
                        phase="failed",
                        operation_id=f"tool:{tool_call_id}",
                        parent_operation_id=getattr(trace_context, "parent_operation_id", None),
                        outcome="error",
                        payload={"tool_name": "search_messages", "error_code": exc.error_code},
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
                        "search_messages",
                        request,
                        runtime_context.scope,
                        trace_context=trace_context,
                    )
                except Exception:
                    # 未分类异常必须继续冒泡；这里只记录失败状态供 terminal result 诊断。
                    runtime_context.tool_calls.append(
                        RuntimeToolCall(
                            "search_messages",
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
                tool_name="search_messages",
                envelope=envelope,
                scope=runtime_context.scope,
            )
            runtime_context.tool_results.append(record)
            # 这里记录一次 tool call；同一模型回合的多个调用由 Runtime hook 统一计为一轮。
            runtime_context.tool_calls.append(
                RuntimeToolCall(
                    "search_messages",
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
                raise TypeError("search_messages schema did not expose limit")
            # 只增强 provider-facing schema，不把 schema 约束当成 trusted enforcement 的替代品。
            limit_schema["minimum"] = 1
            limit_schema["maximum"] = trusted_max_results
            limit_schema["default"] = min(20, trusted_max_results)

        return search_messages
