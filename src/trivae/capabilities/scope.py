"""Agent-facing capabilities 共用的 trusted scope enforcement。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityScopeError,
    ExecutionScope,
    FindMembersInput,
    SearchMessagesInput,
    SemanticSearchInput,
)
from trivae.retrieval.structured import ScopeFilters

CapabilitySearchInput = SearchMessagesInput | SemanticSearchInput


def scope_filters(scope: ExecutionScope) -> ScopeFilters:
    """把 Application trusted scope 投影为 Retrieval 共用的只读过滤。"""

    return ScopeFilters(
        session_ids=scope.allowed_session_ids,
        start_timestamp=scope.start_timestamp,
        end_timestamp=scope.end_timestamp,
    )


def effective_sessions(request: CapabilitySearchInput, scope: ExecutionScope) -> tuple[str, ...] | None:
    """显式 session filter 必须是 trusted scope 的子集。"""

    if scope.allowed_session_ids is None:
        return request.session_ids
    if request.session_ids is None:
        return scope.allowed_session_ids
    allowed = set(scope.allowed_session_ids)
    if not set(request.session_ids).issubset(allowed):
        raise CapabilityScopeError("requested session is outside trusted data access scope")
    return request.session_ids


def effective_start(request: CapabilitySearchInput, scope: ExecutionScope) -> int | None:
    """输入时间范围不能向 trusted scope 之前扩展。"""

    start = request.start_timestamp if request.start_timestamp is not None else scope.start_timestamp
    if scope.start_timestamp is not None and (start is None or start < scope.start_timestamp):
        raise CapabilityScopeError("requested start timestamp is outside trusted scope")
    return start


def effective_end(request: CapabilitySearchInput, scope: ExecutionScope) -> int | None:
    """输入时间范围不能向 trusted scope 之后扩展。"""

    end = request.end_timestamp if request.end_timestamp is not None else scope.end_timestamp
    if scope.end_timestamp is not None and (end is None or end > scope.end_timestamp):
        raise CapabilityScopeError("requested end timestamp is outside trusted scope")
    return end


def effective_member_sessions(request: FindMembersInput, scope: ExecutionScope) -> tuple[str, ...] | None:
    """成员查询的 session filter 必须是 trusted access scope 的子集。"""

    if scope.allowed_session_ids is None:
        return request.session_ids
    if request.session_ids is None:
        return scope.allowed_session_ids
    allowed = set(scope.allowed_session_ids)
    if not set(request.session_ids).issubset(allowed):
        raise CapabilityScopeError("requested member session is outside trusted data access scope")
    return request.session_ids
