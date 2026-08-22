from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trivae.data.ingestion.importer import SharedImporter
from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.model import SourceIdentityError
from trivae.data.storage.sqlite import SQLiteCanonicalStore


def make_message(
    message_id: str | None,
    seq: int,
    timestamp: int,
    text: str,
    *,
    sender_uid: str = "u_sender",
    message_type: str = "text",
    reply_to: str | None = None,
) -> dict:
    """生成最小 QQ fixture；实际 raw 文件仍由 QQExportParser 负责验证。"""

    elements: list[dict] = [{"type": "text", "data": {"text": text}}]
    if reply_to is not None:
        elements.insert(
            0,
            {
                "type": "reply",
                "data": {
                    "messageId": reply_to,
                    "referencedMessageId": reply_to,
                    "senderName": "other",
                },
            },
        )
    return {
        **({"id": message_id} if message_id is not None else {}),
        "seq": str(seq),
        "timestamp": timestamp,
        "time": "2026-08-01T00:00:00.000Z",
        "sender": {
            "uid": sender_uid,
            "uin": "10001",
            "name": "Sender",
            "nickname": "Sender",
            "groupCard": "Card",
        },
        "type": message_type,
        "content": {"text": text, "html": "", "elements": elements, "resources": [], "mentions": []},
        "recalled": False,
        "system": False,
    }


def write_export(
    directory: Path,
    filename: str,
    messages: list[dict],
    *,
    chat_name: str,
    peer_uid: str | None,
    version: str,
) -> Path:
    """写入测试输入，不触碰项目真实 data/raw。"""

    chat_info = {
        "name": chat_name,
        "type": "group",
        "selfUid": "u_self",
        "selfUin": "20000",
    }
    if peer_uid is not None:
        chat_info["peerUid"] = peer_uid
    payload = {
        "metadata": {"name": "QQChatExporter", "version": version},
        "chatInfo": chat_info,
        "statistics": {},
        "messages": messages,
        "exportOptions": {},
    }
    path = directory / filename
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class QQExportParserTests(unittest.TestCase):
    def test_supports_v5_filename_identity_and_normalizes_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_export(
                directory,
                "群聊名称(12345).json",
                [make_message("m1", 1, 1000, "[图片: x.png]", message_type="type_1")],
                chat_name="群聊名称",
                peer_uid=None,
                version="5.5.64",
            )
            parsed = QQExportParser().parse(path)
            record_index, message = next(QQExportParser().iter_normalized_messages(parsed))

            self.assertEqual(record_index, 0)
            self.assertEqual(parsed.session.external_chat_id, "12345")
            self.assertEqual(message.message_type, "text")
            self.assertEqual(message.content_text, "[图片:x.png]")
            self.assertEqual(message.source_message_id, "m1")

    def test_supports_peer_uid_and_reply_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_export(
                directory,
                "group_display_99999_20260816_123456789.json",
                [make_message("m2", 2, 2000, "reply body", reply_to="m1")],
                chat_name="增量显示名",
                peer_uid="99999",
                version="0.1.0",
            )
            parsed = QQExportParser().parse(path)
            _, message = next(QQExportParser().iter_normalized_messages(parsed))

            self.assertEqual(parsed.session.external_chat_id, "99999")
            self.assertEqual(message.message_type, "reply")
            self.assertEqual(message.reply_to_source_message_id, "m1")

    def test_missing_stable_group_id_is_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_export(
                directory,
                "group-without-id.json",
                [],
                chat_name="会变化的名字",
                peer_uid=None,
                version="5.5.64",
            )
            with self.assertRaises(SourceIdentityError):
                QQExportParser().parse(path)

    def test_missing_message_id_uses_structured_fallback_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_export(
                directory,
                "fallback(12345).json",
                [make_message(None, 10, 3000, "no stable id")],
                chat_name="fallback",
                peer_uid=None,
                version="5.5.64",
            )
            parsed = QQExportParser().parse(path)
            _, message = next(QQExportParser().iter_normalized_messages(parsed))

            self.assertIsNone(message.source_message_id)
            self.assertIsNotNone(message.fallback_identity_key)
            self.assertIn("fallback:", message.internal_message_id)


class SharedImporterTests(unittest.TestCase):
    def test_merges_same_group_and_keeps_same_id_in_other_group(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            first = write_export(
                directory,
                "full(100).json",
                [
                    make_message("same", 1, 1000, "first"),
                    make_message("conflict", 2, 2000, "original"),
                ],
                chat_name="full",
                peer_uid=None,
                version="5.5.64",
            )
            second = write_export(
                directory,
                "group_increment_100_20260816_123456789.json",
                [
                    make_message("conflict", 2, 2000, "changed"),
                    make_message("new", 3, 3000, "increment"),
                ],
                chat_name="increment",
                peer_uid="100",
                version="0.1.0",
            )
            third = write_export(
                directory,
                "other(200).json",
                [make_message("same", 1, 1000, "same id other group")],
                chat_name="other",
                peer_uid=None,
                version="5.5.64",
            )

            with SQLiteCanonicalStore(database_path) as store:
                summary = SharedImporter(store).import_paths([first, second, third])

                self.assertEqual(summary.to_dict()["totals"]["received_count"], 5)
                self.assertEqual(summary.to_dict()["totals"]["inserted_count"], 4)
                self.assertEqual(summary.to_dict()["totals"]["duplicate_count"], 1)
                self.assertEqual(summary.to_dict()["totals"]["conflict_count"], 1)
                self.assertEqual(store.count("chat_sessions"), 2)
                self.assertEqual(store.count("messages"), 4)
                self.assertEqual(store.count("message_variants"), 1)
                self.assertEqual(store.count("message_sources"), 5)

                # 第二次导入不新增 canonical message，也不膨胀同一来源 occurrence。
                rerun = SharedImporter(store).import_paths([first, second, third])
                self.assertEqual(rerun.to_dict()["totals"]["inserted_count"], 0)
                self.assertEqual(store.count("messages"), 4)
                self.assertEqual(store.count("message_sources"), 5)
                self.assertEqual(store.count("message_variants"), 1)

    def test_record_error_is_visible_and_other_records_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            path = write_export(
                directory,
                "partial(300).json",
                [
                    make_message("valid", 1, 1000, "valid"),
                    {"id": "invalid", "seq": "bad", "timestamp": 2000, "sender": {}, "content": {}},
                ],
                chat_name="partial",
                peer_uid=None,
                version="5.5.64",
            )

            with SQLiteCanonicalStore(database_path) as store:
                summary = SharedImporter(store).import_paths([path])

                self.assertTrue(summary.has_errors)
                self.assertEqual(summary.to_dict()["totals"]["inserted_count"], 1)
                self.assertEqual(summary.to_dict()["totals"]["error_count"], 1)
                self.assertEqual(store.count("messages"), 1)
                self.assertEqual(store.count("import_errors"), 1)


if __name__ == "__main__":
    unittest.main()
