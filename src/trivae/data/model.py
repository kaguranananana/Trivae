"""Trivae ingestion vertical slice 使用的 Canonical Model。

这些 dataclass 只表达跨 Adapter/Importer/Store 的业务语义，不携带 SQLite
连接或 CLI 类型。这样 QQ 导出格式的差异可以在 Adapter 内被消化。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar


class IngestionError(Exception):
    """导入链路中可以向用户明确展示的已分类错误。"""

    # 机器可读错误码由异常类型拥有，与面向人的错误消息保持独立。
    error_code: ClassVar[str] = "INGESTION_INVALID"


class SourceFormatError(IngestionError):
    """外部文件不是当前支持的 QQ 导出结构。"""

    error_code: ClassVar[str] = "SOURCE_FORMAT_INVALID"


class SourceIdentityError(IngestionError):
    """无法从来源中取得稳定的群身份。"""

    error_code: ClassVar[str] = "SOURCE_ID_INVALID"


class RecordValidationError(IngestionError):
    """单条消息不能转换为 Canonical Message。"""

    error_code: ClassVar[str] = "RECORD_INVALID"


@dataclass(frozen=True)
class SourceDescriptor:
    """描述一个实际输入文件及其来源身份。"""

    source_id: str
    file_name: str
    adapter: str
    format_version: str
    platform: str
    external_chat_id: str
    chat_name: str
    chat_type: str
    self_uid: str | None
    self_uin: str | None


@dataclass(frozen=True)
class ChatSession:
    """一个逻辑聊天空间；群名不是稳定身份。"""

    platform: str
    external_chat_id: str
    name: str
    chat_type: str
    self_uid: str | None
    self_uin: str | None

    @property
    def session_id(self) -> str:
        """用平台和外部群号构造可重建的内部 session identity。"""

        return f"{self.platform}:{self.external_chat_id}"


@dataclass(frozen=True)
class ParsedExport:
    """Adapter 读取后的文件级结果，消息仍保持 source raw dict。"""

    source: SourceDescriptor
    session: ChatSession
    messages: list[dict[str, Any]]


@dataclass(frozen=True)
class CanonicalMessage:
    """Importer 写入 Store 的 source-independent message。"""

    internal_message_id: str
    session_id: str
    platform: str
    source_message_id: str | None
    fallback_identity_key: str | None
    # seq 是可缺省的排序提示；缺失时由 timestamp 与内部 ID 提供确定性顺序。
    seq: int | None
    timestamp: int
    message_type: str
    content_text: str
    content_json: str
    raw_payload_json: str
    sender_user_id: str | None
    sender_platform_id: str | None
    sender_uin: str | None
    sender_name: str | None
    sender_nickname: str | None
    sender_group_card: str | None
    sender_remark: str | None
    reply_to_source_message_id: str | None
    recalled: bool
    system: bool
    canonical_source_id: str
    canonical_source_record_index: int

    def canonical_projection(self) -> dict[str, Any]:
        """返回用于重复/冲突判断的稳定字段，不包含可变显示名和 raw 来源。

        同一条消息在不同导出器中的 display name 可能变化；这些字段属于
        Membership 事实，不应因为名称变化就把消息判成另一条逻辑消息。
        content_json/raw_payload_json 保存在 Canonical Store 和版本 provenance；
        实质转发正文另外复用正式树投影比较，只接受保留全部旧事实的单调补齐。
        """

        return {
            "source_message_id": self.source_message_id,
            "fallback_identity_key": self.fallback_identity_key,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "message_type": self.message_type,
            "content_text": self.content_text,
            "sender_platform_id": self.sender_platform_id,
            "sender_uin": self.sender_uin,
            "reply_to_source_message_id": self.reply_to_source_message_id,
            "recalled": self.recalled,
            "system": self.system,
        }


@dataclass(frozen=True)
class ImportBatchSummary:
    """一个来源文件的可观测导入结果。"""

    batch_id: str
    source_file: str
    session_id: str | None
    received_count: int
    inserted_count: int
    duplicate_count: int
    conflict_count: int
    error_count: int
    status: str
    error_message: str | None = None
    # 已有消息补齐转发正文单独计数，不混入普通重复或新增消息。
    enriched_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换成 CLI 和测试共同使用的普通字典。"""

        return asdict(self)


@dataclass(frozen=True)
class ImportRunSummary:
    """多文件导入的聚合摘要。"""

    batches: tuple[ImportBatchSummary, ...]

    def to_dict(self) -> dict[str, Any]:
        """输出 per-file 与 total 两层结果，避免只给一个不可解释的数字。"""

        totals = {
            "files": len(self.batches),
            "received_count": sum(batch.received_count for batch in self.batches),
            "inserted_count": sum(batch.inserted_count for batch in self.batches),
            "enriched_count": sum(batch.enriched_count for batch in self.batches),
            "duplicate_count": sum(batch.duplicate_count for batch in self.batches),
            "conflict_count": sum(batch.conflict_count for batch in self.batches),
            "error_count": sum(batch.error_count for batch in self.batches),
            "failed_batches": sum(batch.status == "failed" for batch in self.batches),
            "partial_batches": sum(batch.status == "partial" for batch in self.batches),
        }
        return {
            "totals": totals,
            "batches": [batch.to_dict() for batch in self.batches],
        }

    @property
    def has_errors(self) -> bool:
        """错误存在时让 CLI 使用非零退出码，而不是伪装成成功。"""

        return any(batch.error_count > 0 or batch.status == "failed" for batch in self.batches)
