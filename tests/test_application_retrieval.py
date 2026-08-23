from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, SearchMessagesInput
from trivae.retrieval.structured import MessageQuery


class ApplicationRetrievalTests(unittest.TestCase):
    """验证 Composition Root 的 read/index/Capability lifecycle。"""

    def test_application_materializes_secret_free_evaluation_snapshot(self) -> None:
        """Snapshot 通过 Application facade 读取当前 Canonical manifest，不携带聊天正文。"""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw_directory = directory / "raw"
            raw_directory.mkdir()
            write_export(
                raw_directory,
                "application-snapshot(100).json",
                [make_message("m1", 1, 1_768_435_200_000, "snapshot message")],
                chat_name="Application Snapshot",
                peer_uid=None,
                version="5.5.64",
            )
            database_path = directory / "application-snapshot.sqlite3"

            with create_application(database_path) as application:
                application.import_directory(raw_directory)
                snapshot = application.materialize_evaluation_snapshot()

            self.assertEqual(snapshot.status, "available")
            self.assertEqual(snapshot.message_count, 1)
            self.assertEqual(snapshot.manifest["message_count"], 1)
            self.assertNotIn("content", snapshot.manifest)
            self.assertNotIn("normalized_content", snapshot.manifest)

    def test_application_wires_structured_rebuild_and_search_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            raw_directory = directory / "raw"
            raw_directory.mkdir()
            write_export(
                raw_directory,
                "application(100).json",
                [make_message("m1", 1, 1_768_435_200_000, "alpha application")],
                chat_name="Application",
                peer_uid=None,
                version="5.5.64",
            )
            database_path = directory / "application.sqlite3"

            with create_application(database_path) as application:
                application.import_directory(raw_directory)
                structured = application.retrieve_messages(MessageQuery(session_ids=("qq:100",)))
                stats = application.rebuild_lexical_index()
                envelope = application.invoke_tool(
                    "search_messages",
                    SearchMessagesInput(keyword="alpha", session_ids=("qq:100",), limit=5),
                    ExecutionScope(allowed_session_ids=("qq:100",), max_results=5),
                )

                self.assertEqual(structured.returned_count, 1)
                self.assertEqual(stats.indexed_messages, 1)
                self.assertEqual(envelope.status, "ok")
                self.assertEqual(envelope.data.total_hits, 1)
