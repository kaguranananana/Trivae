"""QQChatExporter V5/0.1.0 Adapter。

这个模块是唯一理解 QQ 导出字段差异的地方。下游只接收
`ParsedExport` 和 `CanonicalMessage`，因此同群合并不会依赖文件名中的
“全量/增量”文字或某个导出版本的 source-specific type。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from trivae.data.model import (
    CanonicalMessage,
    ChatSession,
    ParsedExport,
    RecordValidationError,
    SourceDescriptor,
    SourceFormatError,
    SourceIdentityError,
)


_GROUP_ID_IN_PARENTHESIS = re.compile(r"\((?P<group_id>\d+)\)\.json$")
_GROUP_ID_IN_STAMPED_NAME = re.compile(r"_(?P<group_id>\d+)_\d{8}_\d+\.json$")
_CONTENT_MARKER = re.compile(r"\[(图片|文件|视频|语音):\s*([^\]]+)\]")
_UNKNOWN_ID_VALUES = {"", "未知", "unknown", "system", "系统消息"}


class QQExportParser:
    """把一个 QQ JSON 文件解析成文件级来源和可规范化消息。"""

    adapter_name = "qq_chat_exporter"

    def parse(self, path: Path) -> ParsedExport:
        """读取并验证文件级结构；单条消息的验证留给迭代器。

        文件级错误不能被当成空文件继续导入，否则会让用户误以为该群
        已经完成 ingestion。
        """

        try:
            with path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
        except FileNotFoundError as exc:
            raise SourceFormatError(f"QQ source file does not exist: {path}") from exc
        except json.JSONDecodeError as exc:
            raise SourceFormatError(f"Invalid JSON in QQ source file {path.name}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise SourceFormatError(f"QQ source file is not UTF-8: {path.name}") from exc

        if not isinstance(payload, dict):
            raise SourceFormatError(f"QQ source root must be an object: {path.name}")

        metadata = payload.get("metadata")
        chat_info = payload.get("chatInfo")
        messages = payload.get("messages")

        if not isinstance(metadata, dict):
            raise SourceFormatError(f"QQ source metadata must be an object: {path.name}")
        if not isinstance(chat_info, dict):
            raise SourceFormatError(f"QQ source chatInfo must be an object: {path.name}")
        if not isinstance(messages, list):
            raise SourceFormatError(f"QQ source messages must be an array: {path.name}")

        external_chat_id = self._extract_external_chat_id(path, chat_info)
        platform = "qq"
        chat_name = self._optional_text(chat_info.get("name")) or external_chat_id
        format_version = self._optional_text(metadata.get("version")) or "unknown"
        source_id = f"{self.adapter_name}:{path.name}"

        source = SourceDescriptor(
            source_id=source_id,
            file_name=path.name,
            adapter=self.adapter_name,
            format_version=format_version,
            platform=platform,
            external_chat_id=external_chat_id,
            chat_name=chat_name,
            chat_type=self._optional_text(chat_info.get("type")) or "unknown",
            self_uid=self._optional_text(chat_info.get("selfUid")),
            self_uin=self._optional_text(chat_info.get("selfUin")),
        )
        session = ChatSession(
            platform=platform,
            external_chat_id=external_chat_id,
            name=chat_name,
            chat_type=source.chat_type,
            self_uid=source.self_uid,
            self_uin=source.self_uin,
        )
        return ParsedExport(source=source, session=session, messages=messages)

    def iter_normalized_messages(
        self,
        parsed: ParsedExport,
        record_index_offset: int = 0,
    ) -> Iterable[tuple[int, CanonicalMessage]]:
        """逐条把 source message 转成 Canonical Message。

        逐条 yield 让 Importer 能在发现单条坏记录时记录 error 并继续处理
        同一文件中其他可验证记录，同时不吞掉未知异常。
        """

        for local_index, raw_message in enumerate(parsed.messages):
            # Importer 在逐条处理时传入原文件 offset，保证 provenance 不被重置为 0。
            record_index = record_index_offset + local_index
            # 先确认当前记录是 object，后续字段读取才有明确边界。
            if not isinstance(raw_message, dict):
                raise RecordValidationError(
                    f"message[{record_index}] must be an object in {parsed.source.file_name}"
                )

            # 提取并验证所有下游需要的时间/顺序字段；timestamp 是 canonical 时间事实。
            timestamp = self._required_integer(raw_message, "timestamp", record_index, parsed)
            seq = self._optional_integer(raw_message.get("seq"), "seq", record_index, parsed)

            # content 必须保留完整 JSON，不能只抽取一段文本后丢失 image/file/reply 结构。
            content = raw_message.get("content")
            if not isinstance(content, dict):
                raise RecordValidationError(
                    f"message[{record_index}].content must be an object in {parsed.source.file_name}"
                )
            elements = content.get("elements", [])
            if not isinstance(elements, list):
                raise RecordValidationError(
                    f"message[{record_index}].content.elements must be an array in {parsed.source.file_name}"
                )

            # sender 显示信息进入 Membership/Message snapshot；未知系统发送者不伪造用户身份。
            sender = raw_message.get("sender") or {}
            if not isinstance(sender, dict):
                raise RecordValidationError(
                    f"message[{record_index}].sender must be an object in {parsed.source.file_name}"
                )
            sender_identity = self._sender_identity(sender)
            sender_platform_id = sender_identity[0]
            sender_uin = sender_identity[1]
            sender_user_id = (
                f"{parsed.source.platform}:{sender_identity[2]}" if sender_identity[2] else None
            )

            # message type 从 system 标志和 element kind 推导，屏蔽 type_1/text 等版本差异。
            message_type = self._canonical_message_type(raw_message, elements)
            raw_content_text = self._optional_text(content.get("text")) or ""
            content_text = self._normalize_content_text(raw_content_text)
            reply_to_source_message_id = self._reply_target(elements)
            source_message_id = self._optional_text(raw_message.get("id"))

            # 没有稳定 ID 时使用可解释的结构化 identity key；这里不调用 hash/hashlib。
            fallback_identity_key = None
            if source_message_id is None:
                fallback_identity_key = self._fallback_identity_key(
                    parsed.session.session_id,
                    sender_identity[2],
                    seq,
                    timestamp,
                    message_type,
                    content_text,
                    reply_to_source_message_id,
                )

            # 稳定 ID 优先；fallback key 只在 source message ID 缺失时承担 identity 作用。
            identity_suffix = source_message_id or f"fallback:{fallback_identity_key}"
            internal_message_id = f"{parsed.session.session_id}:{identity_suffix}"

            # 完整 raw payload 与 content JSON 都用 UTF-8 保存，确保后续重新处理不依赖展示文本。
            content_json = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            raw_payload_json = json.dumps(
                raw_message,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

            yield record_index, CanonicalMessage(
                internal_message_id=internal_message_id,
                session_id=parsed.session.session_id,
                platform=parsed.source.platform,
                source_message_id=source_message_id,
                fallback_identity_key=fallback_identity_key,
                seq=seq,
                timestamp=timestamp,
                message_type=message_type,
                content_text=content_text,
                content_json=content_json,
                raw_payload_json=raw_payload_json,
                sender_user_id=sender_user_id,
                sender_platform_id=sender_platform_id,
                sender_uin=sender_uin,
                sender_name=self._optional_text(sender.get("name")),
                sender_nickname=self._optional_text(sender.get("nickname")),
                sender_group_card=self._optional_text(sender.get("groupCard")),
                sender_remark=self._optional_text(sender.get("remark")),
                reply_to_source_message_id=reply_to_source_message_id,
                recalled=bool(raw_message.get("recalled", False)),
                system=bool(raw_message.get("system", False)),
                canonical_source_id=parsed.source.source_id,
                canonical_source_record_index=record_index,
            )

    @staticmethod
    def _extract_external_chat_id(path: Path, chat_info: dict[str, Any]) -> str:
        """从 authoritative peerUid 或文件显式群号取得 session identity。"""

        # 新版导出直接提供 peerUid，这是最可靠的来源字段。
        peer_uid = QQExportParser._optional_text(chat_info.get("peerUid"))
        if peer_uid:
            return peer_uid

        # V5 当前没有 peerUid，但真实文件名保留了括号群号或带导出时间戳的群号。
        for pattern in (_GROUP_ID_IN_PARENTHESIS, _GROUP_ID_IN_STAMPED_NAME):
            match = pattern.search(path.name)
            if match:
                return match.group("group_id")

        # 群名可变，无法替代稳定 external_chat_id；这里必须显式失败。
        raise SourceIdentityError(
            f"Cannot determine stable QQ external_chat_id from chatInfo or filename: {path.name}"
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        """把 JSON scalar 转为非空字符串；不对内容做 trim，保留原始语义。"""

        if value is None:
            return None
        text = str(value)
        return text if text else None

    @classmethod
    def _required_integer(
        cls,
        message: dict[str, Any],
        field_name: str,
        record_index: int,
        parsed: ParsedExport,
    ) -> int:
        """读取必需整数并把输入错误定位到文件和记录位置。"""

        value = message.get(field_name)
        parsed_value = cls._optional_integer(value, field_name, record_index, parsed)
        if parsed_value is None:
            raise RecordValidationError(
                f"message[{record_index}].{field_name} is required in {parsed.source.file_name}"
            )
        return parsed_value

    @staticmethod
    def _optional_integer(
        value: Any,
        field_name: str,
        record_index: int,
        parsed: ParsedExport,
    ) -> int | None:
        """只接受整数或整数文本，避免把浮点/布尔值静默转成时间。"""

        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise RecordValidationError(
                f"message[{record_index}].{field_name} must be an integer in {parsed.source.file_name}"
            )
        if isinstance(value, int):
            return value
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
            return int(value)
        raise RecordValidationError(
            f"message[{record_index}].{field_name} must be an integer in {parsed.source.file_name}"
        )

    @staticmethod
    def _sender_identity(sender: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        """返回 uid、uin 和用于跨群身份的稳定 key。"""

        uid = QQExportParser._optional_text(sender.get("uid"))
        if uid in _UNKNOWN_ID_VALUES:
            uid = None

        uin = QQExportParser._optional_text(sender.get("uin"))
        if uin in _UNKNOWN_ID_VALUES:
            uin = None

        # uid 优先于 uin；只有两者都没有时才返回 None，避免伪造系统用户。
        identity_key = f"uid:{uid}" if uid else (f"uin:{uin}" if uin else None)
        return uid, uin, identity_key

    @staticmethod
    def _canonical_message_type(raw_message: dict[str, Any], elements: list[Any]) -> str:
        """从 element kinds 推导跨 QQ 导出版本一致的 message type。"""

        if bool(raw_message.get("system", False)):
            return "system"

        element_kinds = {
            str(element.get("type"))
            for element in elements
            if isinstance(element, dict) and element.get("type")
        }
        if "reply" in element_kinds or str(raw_message.get("type")) == "reply":
            return "reply"
        if "image" in element_kinds:
            return "image"
        if "file" in element_kinds:
            return "file"
        if "video" in element_kinds:
            return "video"
        if "audio" in element_kinds:
            return "audio"
        if "json" in element_kinds:
            return "json"
        if element_kinds - {"text", "at", "face"}:
            return "rich"
        return "text"

    @staticmethod
    def _normalize_content_text(text: str) -> str:
        """只统一导出器对资源占位符的空格差异，其他文本保持原样。"""

        return _CONTENT_MARKER.sub(lambda match: f"[{match.group(1)}:{match.group(2)}]", text)

    @staticmethod
    def _reply_target(elements: list[Any]) -> str | None:
        """读取 reply element 的稳定目标消息 ID，忽略 exporter 的预览字段。"""

        for element in elements:
            if not isinstance(element, dict) or element.get("type") != "reply":
                continue
            data = element.get("data")
            if not isinstance(data, dict):
                continue
            target = data.get("referencedMessageId") or data.get("messageId")
            target_text = QQExportParser._optional_text(target)
            if target_text and target_text != "0":
                return target_text
        return None

    @staticmethod
    def _fallback_identity_key(
        session_id: str,
        sender_identity_key: str | None,
        seq: int | None,
        timestamp: int,
        message_type: str,
        content_text: str,
        reply_to_source_message_id: str | None,
    ) -> str:
        """用 JSON 数组表达 fallback identity，避免 content-only 去重和哈希算法。"""

        return json.dumps(
            [
                session_id,
                sender_identity_key,
                seq,
                timestamp,
                message_type,
                content_text,
                reply_to_source_message_id,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
