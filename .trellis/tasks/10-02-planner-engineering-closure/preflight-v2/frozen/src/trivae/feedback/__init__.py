"""用户体验反馈的独立持久化边界。"""

from trivae.feedback.contracts import (
    FeedbackError,
    FeedbackNotFoundError,
    FeedbackPersistenceError,
    FeedbackRating,
    FeedbackRecord,
    UserExperientialFeedback,
)
from trivae.feedback.sqlite import SQLiteFeedbackStore

__all__ = [
    "FeedbackError",
    "FeedbackNotFoundError",
    "FeedbackPersistenceError",
    "FeedbackRating",
    "FeedbackRecord",
    "SQLiteFeedbackStore",
    "UserExperientialFeedback",
]
