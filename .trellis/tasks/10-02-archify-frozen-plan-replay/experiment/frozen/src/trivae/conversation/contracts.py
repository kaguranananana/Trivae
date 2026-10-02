"""Conversation Store 的领域契约与历史上下文编译。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from trivae.capabilities.contracts import ExecutionScope
from trivae.query.evidence import AnswerArtifact, StructuredSource
from trivae.query.runtime.contracts import ModelContextMessage

ConversationRole = Literal["user", "assistant"]


class ConversationError(ValueError):
    """Conversation 领域对象或持久化数据违反契约。"""


class ConversationNotFoundError(ConversationError):
    """请求的 conversation 不存在。"""


class ConversationPersistenceError(ConversationError):
    """SQLite Conversation Store 无法完成读写。"""


class ConversationCodecError(ConversationError):
    """AnswerArtifact 持久化 JSON 无法解析或不符合领域结构。"""


class ConversationScopeError(ConversationError):
    """Conversation 缺少 scope 或与当前 trusted scope 不一致。"""


def _required_text(name: str, value: object) -> str:
    """统一校验 identity、内容和时间字段，避免下游重复处理空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ConversationError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_snapshot_text(value: object) -> str | None:
    """读取成员身份快照中的可选文本字段，避免把无效值带入下一轮上下文。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _historical_member_identity_context(artifact: AnswerArtifact) -> tuple[str, ...]:
    """从已验证的 find_members 行提取可复用身份，但不复用旧 Evidence locator。"""

    identities: dict[str, dict[str, str | None]] = {}
    for evidence_item in artifact.evidence_items:
        # 一个 finding 可能绑定多个来源，因此必须遍历每个 EvidenceSource。
        for evidence_source in evidence_item.sources:
            reference = evidence_source.reference
            # 只有 find_members 的 candidates[N] structured row 承载成员身份。
            if not isinstance(reference, StructuredSource):
                continue
            if reference.locator_kind != "row" or not reference.locator.startswith("candidates["):
                continue
            snapshot = reference.value_snapshot
            # Finalizer 保存的是 bounded mapping；其他 structured 值不是身份候选。
            if not isinstance(snapshot, Mapping):
                continue
            if not isinstance(snapshot.get("memberships"), list) or not isinstance(snapshot.get("matches"), list):
                continue

            user_id_value = snapshot.get("user_id")
            platform_value = snapshot.get("platform")
            platform_user_id_value = snapshot.get("platform_user_id")
            # Canonical user_id、platform 和 platform_user_id 缺一不可，避免拼出不完整身份。
            if (
                not isinstance(user_id_value, str)
                or not user_id_value.strip()
                or not isinstance(platform_value, str)
                or not platform_value.strip()
                or not isinstance(platform_user_id_value, str)
                or not platform_user_id_value.strip()
            ):
                continue

            user_id = user_id_value.strip()
            # 同一个 UserIdentity 只保留一份，避免历史答案中的重复 citation 放大上下文。
            identities.setdefault(
                user_id,
                {
                    "platform": platform_value.strip(),
                    "platform_user_id": platform_user_id_value.strip(),
                    "platform_uin": _optional_snapshot_text(snapshot.get("platform_uin")),
                    "display_name": _optional_snapshot_text(snapshot.get("display_name")),
                    "nickname": _optional_snapshot_text(snapshot.get("nickname")),
                    "remark": _optional_snapshot_text(snapshot.get("remark")),
                },
            )

    if not identities:
        # 没有成员候选时不额外制造上下文；当前回答仍按原有历史语义回放。
        return ()
    if len(identities) > 1:
        # 多个候选不能由 Host 替模型猜一个，必须让下一轮重新确认语义指代。
        return (
            "Historical member identity context is ambiguous: a previous member lookup returned "
            "multiple canonical candidates. Call find_members again before applying a sender filter; "
            "do not choose a candidate silently.",
        )

    user_id, fields = next(iter(identities.items()))
    identity_fields = [
        f"user_id={user_id}",
        f"platform={fields['platform']}",
        f"platform_user_id={fields['platform_user_id']}",
    ]
    # UIN/昵称只作为确认指代的别名展示，真正过滤仍必须使用 user_id。
    for field_name in ("platform_uin", "display_name", "nickname", "remark"):
        field_value = fields[field_name]
        if field_value is not None:
            identity_fields.append(f"{field_name}={field_value}")
    return (
        "Historical member identity context (identity bookkeeping only; not fresh evidence):",
        "A previous find_members result resolved the referenced member to this canonical identity:",
        f"- {'; '.join(identity_fields)}",
        "For sender filters, pass the exact user_id above to sender_user_ids. "
        "Never pass platform_uin/QQ number, nickname, group card, or display name as sender_user_ids.",
    )


@dataclass(frozen=True)
class ConversationMessage:
    """一个已经完成、可以参与历史回放的 User 或 Assistant message。"""

    message_id: str
    conversation_id: str
    ordinal: int
    role: ConversationRole
    content: str
    created_at: str
    answer_artifact: AnswerArtifact | None = None
    # assistant turn 的可选 replay 引用：trace 拥有完整过程事实，message 只保存 identity。
    trace_id: str | None = None
    # bounded 过程摘要（router/plan/tool/retrieval/usage 的普通值 JSON），
    # 由 interface 层消费；这里只保证它是普通值 mapping。
    process_projection: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        # 先校验稳定 identity，确保恢复的 message 不能漂移到另一个 conversation。
        object.__setattr__(self, "message_id", _required_text("message_id", self.message_id))
        object.__setattr__(self, "conversation_id", _required_text("conversation_id", self.conversation_id))
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ConversationError("ordinal must be a non-negative integer")
        if self.role not in ("user", "assistant"):
            raise ConversationError("role must be user or assistant")
        object.__setattr__(self, "content", _required_text("content", self.content))
        object.__setattr__(self, "created_at", _required_text("created_at", self.created_at))
        if self.trace_id is not None:
            object.__setattr__(self, "trace_id", _required_text("trace_id", self.trace_id))
        if self.process_projection is not None and not isinstance(self.process_projection, Mapping):
            raise ConversationError("process_projection must be a mapping when provided")

        # User turn 不得携带 Artifact；Assistant turn 必须携带已经验证过的 Artifact。
        if self.role == "user" and self.answer_artifact is not None:
            raise ConversationError("user message cannot contain an answer artifact")
        if self.role == "assistant" and not isinstance(self.answer_artifact, AnswerArtifact):
            raise ConversationError("assistant message requires an answer artifact")
        if self.role == "assistant" and self.answer_artifact is not None:
            if self.content != self.answer_artifact.answer_text:
                raise ConversationError("assistant content must match answer artifact text")

    def to_model_context(self) -> ModelContextMessage:
        """把 completed message 编译成模型可见历史，并隔离旧 Evidence 的 fresh 语义。"""

        if self.role == "user":
            return ModelContextMessage(role="user", content=self.content)

        # 旧 Evidence 只提供指代理解所需的 finding/criterion 摘要，不暴露旧 source locator。
        # 因此模型即使看到历史证据，也只能在新一轮 Tool Result 中取得可引用来源。
        artifact = self.answer_artifact
        if artifact is None:
            raise ConversationError("assistant message is missing an answer artifact")
        lines = [
            "[Historical assistant answer; its evidence is context only and is not fresh evidence for this run.]",
            artifact.answer_text,
        ]
        if artifact.evidence_items:
            lines.append("Historical evidence findings:")
            for item in artifact.evidence_items:
                relation_names = ", ".join(source.relation for source in item.sources) or "none"
                lines.append(
                    f"- finding={item.finding}; criterion={item.criterion}; "
                    f"sufficiency={item.sufficiency}; relations={relation_names}"
                )
                if item.limitations:
                    lines.append(f"  limitations={'; '.join(item.limitations)}")
        if artifact.limitations:
            lines.append(f"Historical answer limitations: {'; '.join(artifact.limitations)}")
        if artifact.resolved_time_range:
            start = artifact.resolved_time_range.get("resolved_start_utc")
            end = artifact.resolved_time_range.get("resolved_end_utc")
            lines.append(f"Historical Host-resolved time range: [{start or '-'}, {end or '-'})")
        if artifact.retrieval_coverage:
            # 历史上下文只携带 coverage 事实，不把旧页的消息来源伪装成本轮新证据。
            status = artifact.retrieval_coverage.get("status")
            retrieved = artifact.retrieval_coverage.get("retrieved_count")
            eligible = artifact.retrieval_coverage.get("eligible_units")
            lines.append(
                f"Historical retrieval coverage: status={status}, "
                f"retrieved={retrieved}, eligible={eligible}"
            )
        # 只回放已验证的 canonical 身份字段，不回放旧 Tool Result 的 source locator。
        lines.extend(_historical_member_identity_context(artifact))
        return ModelContextMessage(role="assistant", content="\n".join(lines))


@dataclass(frozen=True)
class Conversation:
    """Conversation Store 的可回放聚合。"""

    conversation_id: str
    created_at: str
    updated_at: str
    messages: tuple[ConversationMessage, ...] = ()
    scope: ExecutionScope | None = None

    def __post_init__(self) -> None:
        # 聚合自身先校验 identity 和生命周期字段，再校验子消息归属。
        object.__setattr__(self, "conversation_id", _required_text("conversation_id", self.conversation_id))
        object.__setattr__(self, "created_at", _required_text("created_at", self.created_at))
        object.__setattr__(self, "updated_at", _required_text("updated_at", self.updated_at))
        if not isinstance(self.messages, tuple):
            raise ConversationError("messages must be a tuple")
        if self.scope is not None and not isinstance(self.scope, ExecutionScope):
            raise ConversationError("scope must be an ExecutionScope or None")

        previous_ordinal = -1
        for message in self.messages:
            if not isinstance(message, ConversationMessage):
                raise ConversationError("messages must contain ConversationMessage values")
            if message.conversation_id != self.conversation_id:
                raise ConversationError("message belongs to a different conversation")
            if message.ordinal <= previous_ordinal:
                raise ConversationError("messages must be ordered by unique ordinal")
            previous_ordinal = message.ordinal

    def to_model_context(self) -> tuple[ModelContextMessage, ...]:
        """只把已完成的结构化历史编译给 Runtime，不读取 provider 私有 Session。"""

        return tuple(message.to_model_context() for message in self.messages)


@dataclass(frozen=True)
class ConversationSummary:
    """历史列表使用的 bounded metadata，不加载完整回答正文。"""

    conversation_id: str
    created_at: str
    updated_at: str
    title: str
    message_count: int
    scope: ExecutionScope | None
    # 最后一条 message 的 bounded 预览；空 conversation 为 None。
    preview: str | None = None

    def __post_init__(self) -> None:
        # 历史标题来自首个 User query，仍限制长度避免列表被单条输入撑大。
        object.__setattr__(self, "conversation_id", _required_text("conversation_id", self.conversation_id))
        object.__setattr__(self, "created_at", _required_text("created_at", self.created_at))
        object.__setattr__(self, "updated_at", _required_text("updated_at", self.updated_at))
        object.__setattr__(self, "title", _required_text("title", self.title)[:120])
        if isinstance(self.message_count, bool) or not isinstance(self.message_count, int) or self.message_count < 0:
            raise ConversationError("message_count must be a non-negative integer")
        if self.scope is not None and not isinstance(self.scope, ExecutionScope):
            raise ConversationError("scope must be an ExecutionScope or None")


@dataclass(frozen=True)
class ConversationScopeSelector:
    """list_summaries 的最小不可变 scope identity selector。

    它不是 ExecutionScope，也不携带时间/容量等 Retrieval 参数；只描述 persisted
    scope snapshot 的 selectable identity：``allowed_session_ids=None`` 表示创建时
    scope.mode=all，非空 tuple 表示精确的 session 集合 identity。
    """

    allowed_session_ids: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if self.allowed_session_ids is None:
            return
        if isinstance(self.allowed_session_ids, (str, bytes)) or not isinstance(
            self.allowed_session_ids, (tuple, list)
        ):
            raise ConversationError("selector session identity must be a tuple of session ids or None")
        normalized = [_required_text("selector session id", item) for item in self.allowed_session_ids]
        if not normalized:
            raise ConversationError("selector session identity must be a non-empty tuple or None")
        # 去重 + 排序保证集合 identity 与传入顺序无关。
        object.__setattr__(self, "allowed_session_ids", tuple(sorted(set(normalized))))


class ConversationStore(Protocol):
    """Application 使用的最小 Conversation Store 接口。"""

    def create_conversation(self, scope: ExecutionScope | None = None) -> Conversation:
        """创建一个带可选 trusted scope 的空 conversation。"""

    def get_conversation(self, conversation_id: str) -> Conversation:
        """读取完整、稳定排序的 conversation。"""

    def list_summaries(
        self,
        limit: int = 20,
        selector: ConversationScopeSelector | None = None,
    ) -> tuple[ConversationSummary, ...]:
        """按更新时间读取 bounded history metadata。

        ``selector`` 是正式 scope identity selector；None 表示既有全局列表行为
        （CLI/TUI），Web 界面必须显式传入 selector，由 Store 在 SQL 层先过滤再 limit。
        """

    def rename_conversation(self, conversation_id: str, title: str) -> Conversation:
        """显式 rename conversation title，不改变消息或 scope。"""

    def delete_conversation(self, conversation_id: str) -> None:
        """删除 AI conversation 聚合本身；canonical chat 数据不属于该接口。"""

    def commit_turn(
        self,
        conversation_id: str,
        user_content: str,
        answer_artifact: AnswerArtifact,
        *,
        trace_id: str | None = None,
        process_projection: Mapping[str, object] | None = None,
    ) -> Conversation:
        """原子追加 User + completed Assistant turn。"""

    def close(self) -> None:
        """释放 Store 连接。"""
