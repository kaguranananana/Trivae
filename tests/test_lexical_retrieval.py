from __future__ import annotations

from pathlib import Path

from tests.test_ingestion import make_message, write_export
from tests.test_structured_retrieval import StructuredRetrievalTests
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import InvalidRetrievalQuery, LexicalIndexError, LexicalQuery


class LexicalRetrievalTests(StructuredRetrievalTests):
    """在 Structured fixture 上验证 FTS derived index 与自动 context。"""

    def setUp(self) -> None:
        super().setUp()
        self.index = SQLiteLexicalIndex(self.database_path)
        self.stats = self.index.rebuild()
        self.lexical = LexicalRetrieval(self.repository)

    def tearDown(self) -> None:
        self.index.close()
        super().tearDown()

    def test_fts5_rebuild_and_session_scoped_bounded_hits(self) -> None:
        self.assertTrue(self.stats.fts5_available)
        self.assertEqual(self.stats.indexed_messages, 8)

        result = self.lexical.search(
            LexicalQuery(keyword="alpha", session_ids=("qq:100",), limit=3, context_before=0, context_after=0)
        )

        self.assertEqual(result.total_hits, 5)
        self.assertEqual(len(result.hits), 3)
        self.assertEqual(result.returned_messages, 3)
        self.assertTrue(result.partial)
        self.assertTrue(result.truncated)
        self.assertTrue(all(hit.message.session_id == "qq:100" for hit in result.hits))
        self.assertTrue(all(message.session_id == "qq:100" for message in result.expanded_messages))

    def test_context_merge_dedup_and_hit_preservation(self) -> None:
        result = self.lexical.search(
            LexicalQuery(keyword="alpha", session_ids=("qq:100",), limit=5, context_before=2, context_after=2)
        )
        hit_ids = {hit.message.internal_message_id for hit in result.hits}
        expanded_ids = [message.internal_message_id for message in result.expanded_messages]

        self.assertEqual(len(expanded_ids), len(set(expanded_ids)))
        self.assertTrue(hit_ids.issubset(set(expanded_ids)))
        self.assertTrue(result.truncated)
        self.assertFalse(result.partial)
        self.assertEqual(result.returned_messages, 5)

    def test_adjacent_hits_share_context_without_duplicate_messages(self) -> None:
        result = self.lexical.search(
            LexicalQuery(keyword="missing", session_ids=("qq:100",), limit=10, context_before=2, context_after=2)
        )
        expanded_ids = [message.internal_message_id for message in result.expanded_messages]

        self.assertEqual(result.total_hits, 2)
        self.assertEqual(len(expanded_ids), len(set(expanded_ids)))
        self.assertEqual(
            {hit.message.internal_message_id for hit in result.hits},
            {"qq:100:a-missing-1", "qq:100:a-missing-2"},
        )

    def test_deleting_derived_index_preserves_canonical_and_exposes_unavailable(self) -> None:
        self.index.drop()
        self.assertEqual(self.store.count("messages"), 8)

        with self.assertRaises(LexicalIndexError):
            self.lexical.search(LexicalQuery(keyword="alpha"))

        rebuilt = self.index.rebuild()
        self.assertEqual(rebuilt.indexed_messages, 8)

    def test_new_canonical_message_requires_explicit_rebuild(self) -> None:
        """导入新增 canonical fact 后，旧 FTS 必须显式暴露 stale 并 rebuild。"""

        new_export = write_export(
            Path(self.temporary.name),
            "session-a-followup(100).json",
            [make_message("a-rebuild", 7, 1_769_904_000_001, "rebuild marker")],
            chat_name="Session A",
            peer_uid=None,
            version="5.5.64",
        )
        SharedImporter(self.store).import_paths([new_export])

        self.assertEqual(self.store.count("messages"), 9)
        with self.assertRaises(LexicalIndexError):
            self.lexical.search(LexicalQuery(keyword="rebuild", context_before=0, context_after=0))

        rebuilt = self.index.rebuild()
        self.assertEqual(rebuilt.indexed_messages, 9)
        result = self.lexical.search(
            LexicalQuery(keyword="rebuild", session_ids=("qq:100",), context_before=0, context_after=0)
        )
        self.assertEqual(result.total_hits, 1)

    def test_empty_keyword_and_unbounded_lexical_query_are_invalid(self) -> None:
        with self.assertRaises(InvalidRetrievalQuery):
            LexicalQuery(keyword="")
        with self.assertRaises(InvalidRetrievalQuery):
            LexicalQuery(keyword="alpha", limit=None)
