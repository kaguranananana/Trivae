"""Canonical UserIdentity/Membership 的只读查询契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from trivae.config.limits import MAX_MEMBER_RESULT_LIMIT
from trivae.retrieval.structured import Coverage, RetrievalMetadata, ScopeFilters

MemberMatchField = Literal[
    "platform_user_id",
    "platform_uin",
    "display_name",
    "nickname",
    "group_card",
    "remark",
]
MemberMatchKind = Literal["exact", "partial"]


@dataclass(frozen=True)
class MemberQuery:
    """成员查询的业务字段；trusted scope 已在 Capability 层合并后传入。"""

    query: str
    scope: ScopeFilters
    limit: int

    def __post_init__(self) -> None:
        """在 Retrieval boundary 校验 bounded 成员查询。"""

        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("member query must be a non-empty string")
        # 直接调用 Retrieval port 时也保持与 Tool input 相同的查询规范化语义。
        object.__setattr__(self, "query", self.query.strip())
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit <= 0:
            raise ValueError("member query limit must be positive")
        if self.limit > MAX_MEMBER_RESULT_LIMIT:
            raise ValueError(f"member query limit must not exceed {MAX_MEMBER_RESULT_LIMIT}")

    def to_dict(self) -> dict[str, object]:
        """返回不含数据库对象的查询快照。"""

        return {"query": self.query, "scope": self.scope.scope_dict(), "limit": self.limit}


@dataclass(frozen=True)
class MemberMatch:
    """候选命中的字段、字段归属和 exact/partial 依据。"""

    field: MemberMatchField
    owner: Literal["user", "membership"]
    kind: MemberMatchKind
    value: str

    def to_dict(self) -> dict[str, str]:
        """投影模型可理解的匹配依据。"""

        # remark 是现有物理模型承载 alias-like 标签的字段，显式保留这一事实。
        label = "alias/remark" if self.field == "remark" else self.field
        return {
            "field": self.field,
            "label": label,
            "owner": self.owner,
            "kind": self.kind,
            "value": self.value,
        }


@dataclass(frozen=True)
class MemberSession:
    """一个 UserIdentity 在指定 ChatSession 内的 Membership 快照。"""

    session_id: str
    session_display: str
    display_name: str | None
    nickname: str | None
    group_card: str | None
    remark: str | None
    first_seen_timestamp: int | None
    last_seen_timestamp: int | None

    def to_dict(self) -> dict[str, object]:
        """投影群内局部身份和可观测时间范围。"""

        return {
            "session_id": self.session_id,
            "session_display": self.session_display,
            "display_name": self.display_name,
            "nickname": self.nickname,
            "group_card": self.group_card,
            "remark": self.remark,
            "first_seen_timestamp": self.first_seen_timestamp,
            "last_seen_timestamp": self.last_seen_timestamp,
        }


@dataclass(frozen=True)
class MemberCandidate:
    """一个稳定 UserIdentity 及其 scope 内 Membership 候选。"""

    user_id: str
    platform: str
    platform_user_id: str
    platform_uin: str | None
    display_name: str | None
    nickname: str | None
    remark: str | None
    memberships: tuple[MemberSession, ...]
    matches: tuple[MemberMatch, ...]

    @property
    def alias(self) -> str | None:
        """提供 Agent-facing alias 语义；当前物理 schema 仍由 remark 承载该值。"""

        return self.remark

    def to_dict(self) -> dict[str, object]:
        """生成 bounded、可进入 Tool Result/Evidence 的候选投影。"""

        return {
            "user_id": self.user_id,
            "platform": self.platform,
            "platform_user_id": self.platform_user_id,
            "platform_uin": self.platform_uin,
            "display_name": self.display_name,
            "nickname": self.nickname,
            # 当前 schema 没有独立 alias 列；remark 是 UserIdentity 的 alias-like 来源。
            "alias": self.remark,
            "remark": self.remark,
            "memberships": [membership.to_dict() for membership in self.memberships],
            "matches": [match.to_dict() for match in self.matches],
        }


@dataclass(frozen=True)
class FindMembersResult:
    """成员候选结果；多候选和 no-result 都是正常的可解释结果。"""

    query: MemberQuery
    strategy: Literal["identity"]
    candidates: tuple[MemberCandidate, ...]
    total_candidates: int
    coverage: Coverage
    partial: bool
    truncated: bool
    metadata: RetrievalMetadata

    def to_dict(self) -> dict[str, object]:
        """返回 Agent-facing 的成员候选与匹配依据。"""

        return {
            "strategy": self.strategy,
            "query": self.query.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "total_candidates": self.total_candidates,
            "returned_candidates": len(self.candidates),
            "coverage": {"status": self.coverage.status, "basis": self.coverage.basis},
            "partial": self.partial,
            "truncated": self.truncated,
            "metadata": {
                "filters": dict(self.metadata.filters),
                "ordering": self.metadata.ordering,
                "latency_ms": self.metadata.latency_ms,
                "details": dict(self.metadata.details),
            },
        }


class MemberReadRepository(Protocol):
    """Identity Capability 只依赖成员候选读取 port。"""

    def read_member_candidates(self, query: MemberQuery) -> FindMembersResult:
        """读取 scope 内的去重 UserIdentity 候选及 Membership 关联。"""
