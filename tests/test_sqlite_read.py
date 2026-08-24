from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application


class SQLiteReadRangeTests(unittest.TestCase):
    """验证 canonical range 在完整排序 tuple 上保持闭区间语义。"""

    def test_range_does_not_include_previous_message_with_same_timestamp_and_seq(self) -> None:
        """同 timestamp/seq 的真实 QQ 消息仍必须按 internal ID 精确截取。"""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw_directory = directory / "raw"
            raw_directory.mkdir()
            write_export(
                raw_directory,
                "same-order-key(100).json",
                [
                    make_message("m1", 7, 1_768_435_200_000, "first"),
                    make_message("m2", 7, 1_768_435_200_000, "second"),
                    make_message("m3", 8, 1_768_435_200_000, "third"),
                ],
                chat_name="Same Order Key",
                peer_uid=None,
                version="5.5.64",
            )
            database_path = directory / "same-order-key.sqlite3"

            with create_application(database_path) as application:
                application.import_directory(raw_directory)
                messages = application.read_repository.read_message_range(
                    "qq:100",
                    "qq:100:m2",
                    "qq:100:m3",
                    10,
                )

            self.assertEqual(
                [message.internal_message_id for message in messages],
                ["qq:100:m2", "qq:100:m3"],
            )
