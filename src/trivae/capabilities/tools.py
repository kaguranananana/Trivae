"""Retrieval-facing Tool wrapper。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    ExecutionScope,
    SearchMessagesInput,
    ToolEnvelope,
    ToolError,
)
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.retrieval.structured import InvalidRetrievalQuery, LexicalIndexError, RetrievalError


class SearchMessagesTool:
    """只负责 Tool envelope；SQL/FTS/context/order 全部留在 Retrieval Core。"""

    name = "search_messages"

    def __init__(self, capability: SearchMessagesCapability) -> None:
        self.capability = capability

    def invoke(self, request: SearchMessagesInput, scope: ExecutionScope) -> ToolEnvelope:
        """把已分类的 contract/retrieval 错误投影为统一状态，未知异常继续暴露。"""

        try:
            result = self.capability.execute(request, scope)
        except CapabilityContractError as exc:
            return ToolEnvelope(
                status="error",
                data=None,
                meta={"truncated": False},
                error=ToolError(code=exc.error_code, message=str(exc)),
            )
        except InvalidRetrievalQuery as exc:
            return ToolEnvelope(
                status="error",
                data=None,
                meta={"truncated": False},
                error=ToolError(code="INVALID_ARGUMENT", message=str(exc)),
            )
        except LexicalIndexError as exc:
            return ToolEnvelope(
                status="error",
                data=None,
                meta={"truncated": False},
                error=ToolError(code="CAPABILITY_UNAVAILABLE", message=str(exc)),
            )
        except RetrievalError as exc:
            return ToolEnvelope(
                status="error",
                data=None,
                meta={"truncated": False},
                error=ToolError(code="EXECUTION_ERROR", message=str(exc)),
            )

        return ToolEnvelope(
            status="partial" if result.partial else "ok",
            data=result,
            meta={
                "truncated": result.truncated,
                "total_hits": result.total_hits,
                "returned_messages": result.returned_messages,
            },
            error=None,
        )
