from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trivae.data.ingestion.importer import SharedImporter
from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.model import RecordValidationError, SourceFormatError, SourceIdentityError
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.interfaces.cli import main as cli_main


def make_message(
    message_id: str | None,
    seq: int | str | None,
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
    message = {
        **({"id": message_id} if message_id is not None else {}),
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
    # 允许 fixture 显式省略 seq，覆盖上游合法空序号的契约。
    if seq is not None:
        message["seq"] = str(seq)
    return message


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

    def test_missing_seq_is_accepted_as_optional_ordering_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for suffix, raw_seq in (("missing", None), ("empty", "")):
                with self.subTest(seq_case=suffix):
                    path = write_export(
                        directory,
                        f"{suffix}-seq(12345).json",
                        [make_message("m1", raw_seq, 3000, "without seq")],
                        chat_name="missing-seq",
                        peer_uid=None,
                        version="5.5.64",
                    )

                    parsed = QQExportParser().parse(path)
                    _, message = next(QQExportParser().iter_normalized_messages(parsed))

                    self.assertIsNone(message.seq)

    def test_invalid_non_empty_seq_is_record_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = write_export(
                directory,
                "invalid-seq(12345).json",
                [make_message("m1", "not-an-integer", 3000, "bad seq")],
                chat_name="invalid-seq",
                peer_uid=None,
                version="5.5.64",
            )

            parsed = QQExportParser().parse(path)
            with self.assertRaises(RecordValidationError):
                next(QQExportParser().iter_normalized_messages(parsed))

    def test_invalid_timestamp_is_record_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            message = make_message("m1", 1, 3000, "bad timestamp")
            message["timestamp"] = "not-an-integer"
            path = write_export(
                directory,
                "invalid-timestamp(12345).json",
                [message],
                chat_name="invalid-timestamp",
                peer_uid=None,
                version="5.5.64",
            )

            parsed = QQExportParser().parse(path)
            with self.assertRaises(RecordValidationError):
                next(QQExportParser().iter_normalized_messages(parsed))


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

    def test_structured_representation_difference_is_equal_when_semantics_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            first_message = make_message("structured", 1, 1000, "[图片: x.png]")
            first_message["content"]["elements"] = [
                {"type": "text", "data": {"text": "[图片: x.png]"}},
                {"type": "image", "data": {"file": "x.png", "subType": 0}},
            ]
            first_message["content"]["resources"] = [
                {"type": "image", "filename": "x.png", "size": 10, "url": "/image/x.png"}
            ]
            second_message = make_message("structured", 1, 1000, "[图片: x.png]")
            second_message["content"]["elements"] = [
                {"type": "image", "data": {"file": "x.png", "subType": 1, "width": 100, "height": 80}}
            ]
            second_message["content"]["resources"] = [
                {
                    "type": "image",
                    "filename": "x.png",
                    "size": 10,
                    "url": "/image/x.png",
                    "width": 100,
                    "height": 80,
                }
            ]
            first = write_export(
                directory,
                "structured-v5(777).json",
                [first_message],
                chat_name="structured",
                peer_uid=None,
                version="5.5.64",
            )
            second = write_export(
                directory,
                "structured-v1.json",
                [second_message],
                chat_name="structured",
                peer_uid="777",
                version="0.1.0",
            )

            with SQLiteCanonicalStore(database_path) as store:
                summary = SharedImporter(store).import_paths([first, second])
                totals = summary.to_dict()["totals"]
                variant = store.connection.execute(
                    "SELECT variant_kind, raw_payload_json FROM message_variants"
                ).fetchone()

                self.assertEqual(totals["inserted_count"], 1)
                self.assertEqual(totals["duplicate_count"], 1)
                self.assertEqual(totals["conflict_count"], 0)
                self.assertEqual(store.count("message_variants"), 1)
                self.assertEqual(variant["variant_kind"], "duplicate_equal")
                self.assertIsNone(variant["raw_payload_json"])

    def test_file_level_errors_use_typed_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            invalid_json = directory / "invalid-json(301).json"
            invalid_json.write_text("{", encoding="utf-8")

            invalid_metadata = write_export(
                directory,
                "invalid-metadata(302).json",
                [],
                chat_name="invalid-metadata",
                peer_uid=None,
                version="5.5.64",
            )
            metadata_payload = json.loads(invalid_metadata.read_text(encoding="utf-8"))
            metadata_payload["metadata"] = []
            invalid_metadata.write_text(json.dumps(metadata_payload), encoding="utf-8")

            invalid_chat_info = write_export(
                directory,
                "invalid-chat-info(303).json",
                [],
                chat_name="invalid-chat-info",
                peer_uid=None,
                version="5.5.64",
            )
            chat_info_payload = json.loads(invalid_chat_info.read_text(encoding="utf-8"))
            chat_info_payload["chatInfo"] = []
            invalid_chat_info.write_text(json.dumps(chat_info_payload), encoding="utf-8")

            invalid_messages = write_export(
                directory,
                "invalid-messages(304).json",
                [],
                chat_name="invalid-messages",
                peer_uid=None,
                version="5.5.64",
            )
            messages_payload = json.loads(invalid_messages.read_text(encoding="utf-8"))
            messages_payload["messages"] = {}
            invalid_messages.write_text(json.dumps(messages_payload), encoding="utf-8")

            missing_identity = write_export(
                directory,
                "group-without-id.json",
                [],
                chat_name="display name only",
                peer_uid=None,
                version="5.5.64",
            )

            with SQLiteCanonicalStore(database_path) as store:
                summary = SharedImporter(store).import_paths(
                    [invalid_json, invalid_metadata, invalid_chat_info, invalid_messages, missing_identity]
                )
                codes = [
                    row["error_code"]
                    for row in store.connection.execute("SELECT error_code FROM import_errors")
                ]

                self.assertEqual(summary.to_dict()["totals"]["failed_batches"], 5)
                self.assertEqual(codes.count("SOURCE_FORMAT_INVALID"), 4)
                self.assertEqual(codes.count("SOURCE_ID_INVALID"), 1)

    def test_error_code_mapping_does_not_inspect_error_message(self) -> None:
        self.assertEqual(
            SharedImporter._error_code(SourceFormatError("format wording can change")),
            "SOURCE_FORMAT_INVALID",
        )

    def test_record_error_has_record_invalid_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            path = write_export(
                directory,
                "partial(305).json",
                [
                    make_message("valid", 1, 1000, "valid"),
                    make_message("invalid", "bad", 2000, "invalid seq"),
                ],
                chat_name="partial",
                peer_uid=None,
                version="5.5.64",
            )

            with SQLiteCanonicalStore(database_path) as store:
                SharedImporter(store).import_paths([path])
                error = store.connection.execute(
                    "SELECT error_code FROM import_errors WHERE source_record_index = 1"
                ).fetchone()

                self.assertIsNotNone(error)
                self.assertEqual(error["error_code"], "RECORD_INVALID")

    def test_unknown_write_error_rolls_back_file_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            database_path = directory / "trivae.sqlite3"
            path = write_export(
                directory,
                "rollback(306).json",
                [make_message("m1", 1, 1000, "rollback")],
                chat_name="rollback",
                peer_uid=None,
                version="5.5.64",
            )

            with SQLiteCanonicalStore(database_path) as store:
                with patch.object(store, "write_message", side_effect=RuntimeError("write failed")):
                    with self.assertRaisesRegex(RuntimeError, "write failed"):
                        SharedImporter(store).import_paths([path])

                self.assertEqual(store.count("sources"), 0)
                self.assertEqual(store.count("chat_sessions"), 0)
                self.assertEqual(store.count("import_batches"), 0)
                self.assertEqual(store.count("messages"), 0)
                self.assertEqual(store.count("import_errors"), 0)

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


class CliTests(unittest.TestCase):
    def test_success_and_partial_imports_return_machine_readable_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            valid_directory = directory / "valid"
            valid_directory.mkdir()
            write_export(
                valid_directory,
                "valid(401).json",
                [make_message("m1", 1, 1000, "valid")],
                chat_name="valid",
                peer_uid=None,
                version="5.5.64",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                success_code = cli_main(
                    [
                        "import",
                        "--raw-dir",
                        str(valid_directory),
                        "--database",
                        str(directory / "valid.sqlite3"),
                    ]
                )
            success_payload = json.loads(output.getvalue())
            self.assertEqual(success_code, 0)
            self.assertEqual(success_payload["totals"]["error_count"], 0)

            partial_directory = directory / "partial"
            partial_directory.mkdir()
            write_export(
                partial_directory,
                "partial(402).json",
                [make_message("bad", "not-an-integer", 1000, "bad")],
                chat_name="partial",
                peer_uid=None,
                version="5.5.64",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                partial_code = cli_main(
                    [
                        "import",
                        "--raw-dir",
                        str(partial_directory),
                        "--database",
                        str(directory / "partial.sqlite3"),
                    ]
                )
            partial_payload = json.loads(output.getvalue())
            self.assertEqual(partial_code, 1)
            self.assertEqual(partial_payload["totals"]["error_count"], 1)

    def test_file_level_cli_error_returns_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw_directory = directory / "raw"
            raw_directory.mkdir()
            (raw_directory / "broken(403).json").write_text("{", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli_main(
                    [
                        "import",
                        "--raw-dir",
                        str(raw_directory),
                        "--database",
                        str(directory / "broken.sqlite3"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 1)
            self.assertEqual(payload["totals"]["failed_batches"], 1)

if __name__ == "__main__":
    unittest.main()
