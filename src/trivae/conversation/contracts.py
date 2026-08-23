"""Conversation Store 的领域契约与历史上下文编译。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from trivae.query.evidence import AnswerArtifact
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


def _required_text(name: str, value: object) -> str:
    """统一校验 identity、内容和时间字段，避免下游重复处理空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ConversationError(f"{name} must be a non-empty string")
    return value.strip()


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
        return ModelContextMessage(role="assistant", content="\n".join(lines))


@dataclass(frozen=True)
class Conversation:
    """Conversation Store 的可回放聚合。"""

    conversation_id: str
    created_at: str
    updated_at: str
    messages: tuple[ConversationMessage, ...] = ()

    def __post_init__(self) -> None:
        # 聚合自身先校验 identity 和生命周期字段，再校验子消息归属。
        object.__setattr__(self, "conversation_id", _required_text("conversation_id", self.conversation_id))
        object.__setattr__(self, "created_at", _required_text("created_at", self.created_at))
        object.__setattr__(self, "updated_at", _required_text("updated_at", self.updated_at))
        if not isinstance(self.messages, tuple):
            raise ConversationError("messages must be a tuple")

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


class ConversationStore(Protocol):
    """Application 使用的最小 Conversation Store 接口。"""

    def create_conversation(self) -> Conversation:
        """创建一个空 conversation。"""

    def get_conversation(self, conversation_id: str) -> Conversation:
        """读取完整、稳定排序的 conversation。"""

    def commit_turn(
        self,
        conversation_id: str,
        user_content: str,
        answer_artifact: AnswerArtifact,
    ) -> Conversation:
        """原子追加 User + completed Assistant turn。"""

    def close(self) -> None:
        """释放 Store 连接。"""
