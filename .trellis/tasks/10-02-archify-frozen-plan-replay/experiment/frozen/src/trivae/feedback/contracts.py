"""用户体验反馈的领域契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Protocol

from trivae.capabilities.contracts import ExecutionScope

FeedbackRating = Literal["good", "bad"]
UserExperientialFeedback = Literal["user_experiential"]
MAX_FEEDBACK_NOTE_CHARS = 1_000


class FeedbackError(ValueError):
    """反馈字段或持久化边界违反契约。"""


class FeedbackNotFoundError(FeedbackError):
    """请求的反馈记录不存在。"""


class FeedbackPersistenceError(FeedbackError):
    """SQLite 反馈 Store 无法完成读写。"""


def _required_text(name: str, value: object) -> str:
    """统一校验反馈关联 identity，避免写入空关联。"""

    if not isinstance(value, str) or not value.strip():
        raise FeedbackError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class FeedbackRecord:
    """一次用户体验评价，不代表 Evaluation Ground Truth。"""

    feedback_id: str
    created_at: str
    updated_at: str
    conversation_id: str
    trace_id: str
    run_id: str
    scope_snapshot: Mapping[str, object]
    rating: FeedbackRating
    note: str | None = None
    feedback_kind: UserExperientialFeedback = "user_experiential"

    def __post_init__(self) -> None:
        # 关联字段必须来自已经完成的 Query 结果，不能由用户输入拼接。
        for name in (
            "feedback_id",
            "created_at",
            "updated_at",
            "conversation_id",
            "trace_id",
            "run_id",
        ):
            object.__setattr__(self, name, _required_text(name, getattr(self, name)))
        if not isinstance(self.scope_snapshot, Mapping):
            raise FeedbackError("scope_snapshot must be a mapping")
        if self.rating not in ("good", "bad"):
            raise FeedbackError("rating must be good or bad")
        if self.note is not None:
            if not isinstance(self.note, str):
                raise FeedbackError("feedback note must be text or None")
            normalized_note = self.note.strip()
            if len(normalized_note) > MAX_FEEDBACK_NOTE_CHARS:
                raise FeedbackError(
                    f"feedback note exceeds {MAX_FEEDBACK_NOTE_CHARS} characters"
                )
            object.__setattr__(self, "note", normalized_note or None)
        if self.feedback_kind != "user_experiential":
            raise FeedbackError("feedback_kind must be user_experiential")


class FeedbackStore(Protocol):
    """Application 使用的独立反馈 Store 接口。"""

    def save(self, record: FeedbackRecord) -> FeedbackRecord:
        """按 conversation/trace upsert 用户体验反馈。"""

    def get(self, conversation_id: str, trace_id: str) -> FeedbackRecord | None:
        """读取一轮 Query 的反馈。"""

    def close(self) -> None:
        """释放反馈连接。"""


def feedback_for_query(
    *,
    conversation_id: str,
    trace_id: str,
    run_id: str,
    scope: ExecutionScope,
    rating: FeedbackRating,
    note: str | None,
) -> FeedbackRecord:
    """构造带当前 Query 关联字段的反馈记录，时间和 id 由 Store 补齐。"""

    # 该函数只负责验证用户体验字段；feedback_id/time 由持久化层分配。
    return FeedbackRecord(
        feedback_id="pending",
        created_at="pending",
        updated_at="pending",
        conversation_id=conversation_id,
        trace_id=trace_id,
        run_id=run_id,
        scope_snapshot={
            "allowed_session_ids": scope.allowed_session_ids,
            "start_timestamp": scope.start_timestamp,
            "end_timestamp": scope.end_timestamp,
            "max_results": scope.max_results,
        },
        rating=rating,
        note=note,
    )
