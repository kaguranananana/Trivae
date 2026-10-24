"""日报的普通值契约，不依赖邮件客户端或模型 SDK。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from trivae.retrieval.structured import MessageProjection

TIMEZONE = ZoneInfo("Asia/Shanghai")
CATEGORIES = {"tools": "工具与开源资源", "practice": "技术实战与踩坑", "discussion": "有价值的讨论", "career": "求职与面试"}


@dataclass(frozen=True)
class DigestSnapshot:
    """同一 Canonical 读事务取得的数据与修订水位。"""

    revision: int
    start_timestamp: int
    end_timestamp: int
    root_count: int
    messages: tuple[MessageProjection, ...]
    context_ids: frozenset[str]
    missing_forward_paths: tuple[str, ...]


@dataclass(frozen=True)
class DigestExcerpt:
    """长原文分段后的模型输入；偏移始终指向原始正文。"""

    handle: str
    message: MessageProjection
    offset: int
    text: str
    context_only: bool

    def to_dict(self) -> dict[str, object]:
        """保留回复与转发归属，避免把上下文误报为今日的新发言。"""

        return {
            "id": self.handle,
            "message_id": self.message.internal_message_id,
            "source_message_id": self.message.source_message_id,
            "group": self.message.session_display,
            "session_id": self.message.session_id,
            "time": local_time(self.message.timestamp),
            "sender": self.message.sender_name,
            "reply_to": self.message.reply_to_source_message_id,
            "forward": None if self.message.forward is None else {
                "root_message_id": self.message.forward.root_message_id,
                "original_timestamp": self.message.forward.original_timestamp,
                "path": self.message.forward.path,
            },
            "context_only": self.context_only,
            "content_offset": self.offset,
            "text": self.text,
        }


def local_time(timestamp: int) -> str:
    """邮件统一使用北京时间，不读取执行机器的默认时区。"""

    return datetime.fromtimestamp(timestamp / 1000, TIMEZONE).isoformat(timespec="seconds")
