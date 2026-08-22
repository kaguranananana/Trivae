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

    def as_sdk_tool(self) -> Any:
        """创建 SDK Function Tool；scope 和 registry 只通过 local context 注入。"""

        @function_tool(
            name_override="search_messages",
            description_override=(
                "Search Trivae messages with a bounded local context window. "
                "Use this when the answer needs evidence from chat messages."
            ),
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
            """只接受 typed 字段；scope、registry 和 call identity 都来自 local context。"""

            runtime_context = context.context
            # SDK 版本可能把 call id 放在 wrapper 或 typed local context 上，二者都只投影为安全字符串。
            provider_tool_call_id = getattr(context, "tool_call_id", None)
            if not isinstance(provider_tool_call_id, str):
                provider_tool_call_id = None
            # SDK ID 只用于 local mapping；正式 contract 使用由 Runtime 分配的 Trivae ID。
            tool_call_id = runtime_context.resolve_tool_call_id(provider_tool_call_id)
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
            else:
                try:
                    # trusted scope 由 RuntimeContext 持有，registry 是 composition root 注入的实例。
                    if runtime_context.capability_registry is not self.registry:
                        raise RuntimeError("SDK local context registry does not match the registered tool adapter")
                    envelope = runtime_context.capability_registry.invoke(
                        "search_messages",
                        request,
                        runtime_context.scope,
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

        return search_messages
