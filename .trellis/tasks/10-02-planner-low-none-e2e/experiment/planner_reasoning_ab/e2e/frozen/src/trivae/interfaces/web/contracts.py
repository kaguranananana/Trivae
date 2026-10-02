"""Local Web API 的请求/响应 DTO 与 scope 编译。

scope 只能由后端从 bounded DTO 构造，前端不能传任意 ExecutionScope 字段。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from trivae.capabilities.contracts import CapabilityContractError, ExecutionScope
from trivae.config.limits import DEFAULT_TRUSTED_RESULT_LIMIT

MAX_WEB_CONVERSATION_LIMIT = 100


class ScopeRequest(BaseModel):
    """Web scope 选择；``all`` 表示全部聊天，``sessions`` 必须携带非空 session ids。"""

    mode: Literal["all", "sessions"] = "all"
    session_ids: list[str] | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    max_results: int | None = Field(default=None, gt=0)

    @field_validator("session_ids")
    @classmethod
    def _validate_session_ids(cls, value: list[str] | None) -> list[str] | None:
        """只接受非空字符串 id 列表；禁止伪造通配符。"""

        if value is None:
            return None
        normalized = [item.strip() for item in value]
        if not normalized or any(not item for item in normalized):
            raise ValueError("session_ids must contain non-empty strings when mode is 'sessions'")
        return normalized

    def to_scope(self) -> ExecutionScope:
        """编译为 trusted ExecutionScope；非法取值显式失败，不猜测默认权限。"""

        if self.mode == "all":
            allowed: tuple[str, ...] | None = None
        else:
            if not self.session_ids:
                raise WebScopeError("mode 'sessions' requires session_ids")
            allowed = tuple(self.session_ids)
        try:
            return ExecutionScope(
                allowed_session_ids=allowed,
                start_timestamp=self.start_timestamp,
                end_timestamp=self.end_timestamp,
                max_results=self.max_results if self.max_results is not None else DEFAULT_TRUSTED_RESULT_LIMIT,
            )
        except (CapabilityContractError, TypeError, ValueError) as exc:
            raise WebScopeError(f"scope request violates its contract: {exc}") from exc


class WebScopeError(ValueError):
    """Web scope DTO 无法编译为 trusted ExecutionScope。"""


class ConversationCreateRequest(BaseModel):
    """New Chat 请求：先创建 conversation，再在其上发送 query。"""

    scope: ScopeRequest


class ConversationRenameRequest(BaseModel):
    """Rename 请求；title 与 Conversation Store 的 bounded 语义一致。"""

    title: str = Field(min_length=1, max_length=120)


class QueryStreamRequest(BaseModel):
    """流式 Query 请求；scope/conversation 与 Application 契约一一对应。"""

    query: str = Field(min_length=1)
    scope: ScopeRequest
    conversation_id: str | None = Field(default=None, min_length=1)
    request_id: str | None = Field(default=None, min_length=1)

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must be a non-empty string")
        return normalized


class QueryStopRequest(BaseModel):
    """Stop 请求：按 request_id 取消运行中的 query。"""

    request_id: str = Field(min_length=1)
