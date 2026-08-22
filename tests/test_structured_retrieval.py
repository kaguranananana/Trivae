from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.structured import (
    AggregateQuery,
    InvalidRetrievalQuery,
    MessageQuery,
    StructuredAggregateResult,
    StructuredMessageResult,
    StructuredRetrieval,
)


class StructuredRetrievalTests(unittest.TestCase):
    """用两个 session 固定 M2.0/M2.1 的 scope、ordering 与 aggregate 契约。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "structured.sqlite3"

        session_a_messages = [
            make_message("a-seq-2", 2, 1_768_435_200_000, "alpha seq two", sender_uid="u_a"),
            make_message("a-seq-1", 1, 1_768_435_200_000, "alpha seq one", sender_uid="u_b"),
            make_message("a-missing-1", None, 1_768_435_200_000, "alpha missing one", sender_uid="u_a"),
            make_message(
                "a-missing-2",
                None,
                1_768_435_200_000,
                "alpha missing two",
                sender_uid="u_a",
                reply_to="reply-target",
            ),
            make_message("shared-source", 5, 1_768_867_200_000, "beta shared source", sender_uid="u_b"),
            make_message("a-february", 6, 1_769_904_000_000, "alpha february", sender_uid="u_a"),
        ]
        session_b_messages = [
            make_message(
                "shared-source",
                1,
                1_768_435_200_000,
                "alpha other session",
                sender_uid="u_b",
                reply_to="reply-target",
            ),
            make_message("b-second", 2, 1_769_904_000_000, "gamma other session", sender_uid="u_b"),
        ]
        first = write_export(
            directory,
            "session-a(100).json",
            session_a_messages,
            chat_name="Session A",
            peer_uid=None,
            version="5.5.64",
        )
        second = write_export(
            directory,
            "session-b(200).json",
            session_b_messages,
            chat_name="Session B",
            peer_uid=None,
            version="5.5.64",
        )

        self.store = SQLiteCanonicalStore(self.database_path)
        SharedImporter(self.store).import_paths([first, second])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.retrieval = StructuredRetrieval(self.repository)

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def test_session_source_and_reply_filters_are_isolated(self) -> None:
        source_a = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:100",), source_message_id="shared-source")
        )
        source_b = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:200",), source_message_id="shared-source")
        )
        reply_b = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:200",), reply_to_source_message_id="reply-target")
        )

        self.assertEqual([message.session_id for message in source_a.messages], ["qq:100"])
        self.assertEqual([message.session_id for message in source_b.messages], ["qq:200"])
        self.assertEqual([message.internal_message_id for message in reply_b.messages], ["qq:200:shared-source"])

        with self.assertRaises(InvalidRetrievalQuery):
            MessageQuery(source_message_id="shared-source")
        with self.assertRaises(InvalidRetrievalQuery):
            MessageQuery(reply_to_source_message_id="reply-target")

    def test_half_open_time_sender_type_and_multi_condition_filters(self) -> None:
        start = 1_768_435_200_000
        end = 1_768_867_200_000
        result = self.retrieval.retrieve_messages(
            MessageQuery(
                session_ids=("qq:100",),
                start_timestamp=start,
                end_timestamp=end,
                sender_user_ids=("qq:uid:u_a",),
                message_types=("text",),
            )
        )

        self.assertEqual(result.total_hits, 2)
        self.assertTrue(all(message.timestamp == start for message in result.messages))
        self.assertEqual(result.messages[0].sender_user_id, "qq:uid:u_a")
        self.assertEqual(result.messages[0].message_type, "text")
        self.assertEqual(
            self.retrieval.retrieve_messages(
                MessageQuery(session_ids=("qq:100",), start_timestamp=end, end_timestamp=end)
            ).returned_count,
            0,
        )

    def test_empty_result_projection_and_result_semantics(self) -> None:
        result = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:100",), message_types=("not-present",))
        )

        self.assertIsInstance(result, StructuredMessageResult)
        self.assertEqual(result.strategy, "structured")
        self.assertEqual(result.total_hits, 0)
        self.assertEqual(result.returned_count, 0)
        self.assertEqual(result.messages, ())
        self.assertEqual(result.coverage.status, "complete")
        self.assertFalse(result.partial)
        self.assertFalse(result.truncated)

        projection = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:100",), source_message_id="a-seq-2")
        ).messages[0]
        self.assertEqual(projection.internal_message_id, "qq:100:a-seq-2")
        self.assertEqual(projection.source_message_id, "a-seq-2")
        self.assertEqual(projection.normalized_content, "alpha seq two")
        self.assertFalse(hasattr(projection, "raw_payload_json"))
        self.assertFalse(hasattr(projection, "content_json"))
        self.assertFalse(hasattr(projection, "canonical_projection_json"))

    def test_total_returned_limit_and_deterministic_ordering(self) -> None:
        start = 1_768_435_200_000
        end = start + 1
        limited = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:100",), start_timestamp=start, end_timestamp=end, limit=3)
        )
        repeated = self.retrieval.retrieve_messages(
            MessageQuery(session_ids=("qq:100",), start_timestamp=start, end_timestamp=end, limit=10)
        )

        self.assertEqual(limited.total_hits, 4)
        self.assertEqual(limited.returned_count, 3)
        self.assertTrue(limited.truncated)
        self.assertEqual(
            [message.internal_message_id for message in limited.messages],
            ["qq:100:a-seq-1", "qq:100:a-seq-2", "qq:100:a-missing-1"],
        )
        self.assertEqual(
            [message.internal_message_id for message in repeated.messages],
            [
                "qq:100:a-seq-1",
                "qq:100:a-seq-2",
                "qq:100:a-missing-1",
                "qq:100:a-missing-2",
            ],
        )
        self.assertEqual(
            [message.internal_message_id for message in repeated.messages],
            [message.internal_message_id for message in self.retrieval.retrieve_messages(
                MessageQuery(session_ids=("qq:100",), start_timestamp=start, end_timestamp=end, limit=10)
            ).messages],
        )

    def test_aggregate_count_and_group_by_session_sender_month(self) -> None:
        total = self.retrieval.aggregate_messages(AggregateQuery())
        by_session = self.retrieval.aggregate_messages(AggregateQuery(group_by="session"))
        by_sender = self.retrieval.aggregate_messages(AggregateQuery(group_by="sender"))
        by_month = self.retrieval.aggregate_messages(AggregateQuery(group_by="month"))

        self.assertIsInstance(total, StructuredAggregateResult)
        self.assertEqual(total.total_count, 8)
        self.assertEqual(total.buckets, ())
        self.assertEqual(
            [(bucket.group_key, bucket.count) for bucket in by_session.buckets],
            [("qq:100", 6), ("qq:200", 2)],
        )
        self.assertEqual(
            [(bucket.group_key, bucket.count) for bucket in by_sender.buckets],
            [("qq:uid:u_a", 4), ("qq:uid:u_b", 4)],
        )
        self.assertEqual(
            [(bucket.group_key, bucket.count) for bucket in by_month.buckets],
            [("2026-01", 6), ("2026-02", 2)],
        )

    def test_invalid_time_limit_and_empty_scope_are_explicit(self) -> None:
        invalid_queries = (
            lambda: MessageQuery(start_timestamp=2, end_timestamp=1),
            lambda: MessageQuery(limit=0),
            lambda: MessageQuery(limit=None),
            lambda: MessageQuery(session_ids=()),
            lambda: MessageQuery(sender_user_ids=()),
            lambda: MessageQuery(message_types=()),
            lambda: MessageQuery(session_ids=("qq:100",), source_message_id=""),
        )
        for make_query in invalid_queries:
            with self.subTest(query=make_query):
                with self.assertRaises(InvalidRetrievalQuery):
                    make_query()
