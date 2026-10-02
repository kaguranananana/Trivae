"""find_members Capability：通过现有 UserIdentity/Membership 查询候选。"""

from __future__ import annotations

from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityMetadata,
    ExecutionScope,
    FindMembersInput,
)
from trivae.capabilities.scope import effective_member_sessions
from trivae.config.limits import MAX_MEMBER_RESULT_LIMIT
from trivae.retrieval.identity import FindMembersResult, MemberQuery, MemberReadRepository
from trivae.retrieval.structured import ScopeFilters


class FindMembersCapability:
    """返回稳定 UserIdentity 候选，不把昵称歧义强行解析成唯一人物。"""

    metadata = CapabilityMetadata(
        name="find_members",
        description=(
            "Find candidate members by nickname, group card, username/display name, alias-like "
            "remark, platform identity, or UIN. Return every bounded candidate with matching reasons "
            "and session memberships; do not assume a unique person when names are ambiguous."
        ),
        bounded=True,
        input_fields=("query", "session_ids", "limit"),
    )

    def __init__(self, repository: MemberReadRepository) -> None:
        """复用 Canonical read adapter 的身份查询 port。"""

        self.repository = repository

    def execute(self, request: FindMembersInput, scope: ExecutionScope) -> FindMembersResult:
        """先合并 trusted session/time scope，再执行 bounded identity lookup。"""

        if not isinstance(request, FindMembersInput):
            raise CapabilityContractError("find_members received an invalid request type")
        effective_maximum = min(scope.max_results, MAX_MEMBER_RESULT_LIMIT)
        if request.limit > effective_maximum:
            raise CapabilityContractError(
                f"requested member limit exceeds trusted maximum {effective_maximum}"
            )

        effective_sessions = effective_member_sessions(request, scope)
        query = MemberQuery(
            query=request.query,
            scope=ScopeFilters(
                session_ids=effective_sessions,
                start_timestamp=scope.start_timestamp,
                end_timestamp=scope.end_timestamp,
            ),
            limit=request.limit,
        )
        return self.repository.read_member_candidates(query)
