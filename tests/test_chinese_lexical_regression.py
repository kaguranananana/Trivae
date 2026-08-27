"""中文 lexical recall regression：真实 unicode61/bigram 契约的最小复现与保护网。

Failure B 真实库证据：
- canonical `真心推荐 值得看一看` 在窗口内存在，FTS(unicode61 原文) MATCH "推荐" 0 hits；
- unicode61 把连续 Han run 存成单 token（实测 tokens: [真心推荐, 值得看一看]）。
本文件固化 bigram derived index 下的确定性召回契约，并保护 ASCII/URL/code 行为不退化。
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_lexical_text import (
    FTS_TOKENIZER_STRATEGY_ID,
    normalize_lexical_index_text,
    normalize_lexical_query_term,
)
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.lexical import LexicalRetrieval
from trivae.retrieval.structured import LexicalIndexError, LexicalQuery

SESSION = "qq:900"


class ChineseLexicalNormalizationTests(unittest.TestCase):
    """归一化纯函数的确定性契约（v2：bigram + Han/ASCII 边界包裹）。"""

    def test_cjk_run_becomes_space_wrapped_bigrams(self) -> None:
        self.assertEqual(normalize_lexical_index_text("真心推荐"), "真心 心推 推荐")
        self.assertEqual(
            normalize_lexical_index_text("真心推荐 值得看一看"),
            "真心 心推 推荐 值得 得看 看一 一看",
        )

    def test_single_han_character_is_preserved_with_boundary(self) -> None:
        self.assertEqual(normalize_lexical_index_text("推荐"), "推荐")
        self.assertEqual(normalize_lexical_index_text("看"), "看")
        # 单字夹在 ASCII 中必须形成 tokenizer 边界，而不是被并成一个 token。
        self.assertEqual(normalize_lexical_index_text("abc看xyz"), "abc 看 xyz")

    def test_ascii_url_code_and_error_message_are_unchanged(self) -> None:
        for text in (
            "https://github.com/owner/repo",
            "https://example.com/repo",
            "owner/repo",
            "ImportError",
            "foo_bar",
            "DeepSeek Harness",
            "HTTP 500",
            "matt skill",
            "abc123",
            "openai-sdk",
            "repo123",
        ):
            self.assertEqual(normalize_lexical_index_text(text), text)

    def test_mixed_script_boundary_is_explicit(self) -> None:
        # v1 的 mixed-script 缺陷用例；v2 必须在 Han/ASCII 两侧建立 tokenizer 边界。
        self.assertEqual(normalize_lexical_index_text("abc推荐"), "abc 推荐")
        self.assertEqual(normalize_lexical_index_text("推荐abc"), "推荐 abc")
        self.assertEqual(normalize_lexical_index_text("推荐这个repo"), "推荐 荐这 这个 repo")
        self.assertEqual(normalize_lexical_index_text("repo推荐这个"), "repo 推荐 荐这 这个")

    def test_query_terms_share_the_same_normalization_function(self) -> None:
        self.assertEqual(
            normalize_lexical_query_term("值得看一看"),
            normalize_lexical_index_text("值得看一看"),
        )
        self.assertEqual(normalize_lexical_query_term("foo_bar"), "foo_bar")


class ChineseLexicalRetrievalTests(unittest.TestCase):
    """§7.1 最小复现：窗口内确定存在 -> 必须命中；ASCII 契约不退化。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "chinese-lexical.sqlite3"
        messages = [
            make_message("c1", 1, 1_786_700_000_000, "真心推荐 值得看一看", sender_uid="u_a"),
            make_message("c2", 2, 1_786_700_100_000, "我推荐这个项目", sender_uid="u_b"),
            make_message("c3", 3, 1_786_700_200_000, "推荐", sender_uid="u_a"),
            make_message("c4", 4, 1_786_700_300_000, "不相关消息", sender_uid="u_b"),
            # mixed-script boundary 矩阵（FC-A：v1 曾 miss）。
            make_message("mx1", 5, 1_786_700_350_000, "abc推荐", sender_uid="u_b"),
            make_message("mx2", 6, 1_786_700_360_000, "推荐abc 这个部分", sender_uid="u_a"),
            make_message("a5", 7, 1_786_700_800_000, "直接说 DeepSeek 就行 推荐这个repo 给你", sender_uid="u_a"),
            make_message("mx3", 8, 1_786_700_810_000, "repo推荐这个 可以吗", sender_uid="u_b"),
            # ASCII / exact-lexical protection matrix（§十一）。
            make_message("a1", 5, 1_786_700_400_000, "https://github.com/owner/repo 可以看一下", sender_uid="u_a"),
            make_message("a2", 6, 1_786_700_500_000, "遇到 ImportError 该怎么处理", sender_uid="u_b"),
            make_message("a3", 7, 1_786_700_600_000, "配置里写 foo_bar 是对的", sender_uid="u_a"),
            make_message("a4", 8, 1_786_700_700_000, "用 DeepSeek Harness 的 HTTP 500 排查记录", sender_uid="u_b"),
            make_message("a5", 9, 1_786_700_800_000, "直接说 DeepSeek 就行 推荐这个repo 给你", sender_uid="u_a"),
            make_message("p1", 10, 1_786_700_900_000, "你好。今天天气不错！", sender_uid="u_b"),
        ]
        export = write_export(
            directory,
            "Chinese Lex(900).json",
            messages,
            chat_name="Chinese Lex",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.index = SQLiteLexicalIndex(self.database_path)
        self.stats = self.index.rebuild()
        self.lexical = LexicalRetrieval(self.repository)

    def tearDown(self) -> None:
        self.index.close()
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def _search(self, keyword: str) -> tuple[int, tuple[str, ...]]:
        result = self.lexical.search(LexicalQuery(keyword=keyword, session_ids=(SESSION,), limit=50))
        return result.total_hits, tuple(hit.message.internal_message_id for hit in result.hits)

    def test_rebuild_records_strategy_and_matches_canonical_count(self) -> None:
        self.assertTrue(self.stats.fts5_available)
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT value FROM trivae_derived_meta WHERE key='lexical_tokenizer_strategy'"
            ).fetchone()
        self.assertIsNotNone(row)
        if row is not None:
            self.assertEqual(row[0], FTS_TOKENIZER_STRATEGY_ID)

    def test_chinese_substring_query_hits_all_containing_messages(self) -> None:
        total, ids = self._search("推荐")
        self.assertEqual(total, 7)
        self.assertEqual(
            set(ids),
            {"qq:900:c1", "qq:900:c2", "qq:900:c3", "qq:900:a5", "qq:900:mx1", "qq:900:mx2", "qq:900:mx3"},
        )

    def test_chinese_full_phrase_substring(self) -> None:
        total, ids = self._search("值得看")
        self.assertEqual(total, 1)
        self.assertEqual(ids[0], "qq:900:c1")

    def test_ascii_to_cjk_boundary_recall(self) -> None:
        # FC-A 用例：v1 中 `abc推荐` 是单 token，`推荐` 无法命中。
        total, ids = self._search("推荐")
        self.assertIn("qq:900:mx1", set(ids))

    def test_cjk_to_ascii_boundary_recall(self) -> None:
        # `推荐abc`：q=推荐 与 q=abc 都必须按 lexical contract 命中。
        total_rec, ids_rec = self._search("推荐")
        self.assertIn("qq:900:mx2", set(ids_rec))
        total_abc, ids_abc = self._search("abc")
        # mx1 `abc推荐` 与 mx2 `推荐abc` 都含独立 abc token。
        self.assertEqual((total_abc, set(ids_abc)), (2, {"qq:900:mx1", "qq:900:mx2"}))

    def test_mixed_script_query_matrix(self) -> None:
        # `推荐这个repo` / `repo推荐这个` 三个方向查询均命中对应文档。
        total_zhe, ids_zhe = self._search("这个")
        self.assertEqual(set(ids_zhe), {"qq:900:c2", "qq:900:mx2", "qq:900:a5", "qq:900:mx3"})
        total_repo, ids_repo = self._search("repo")
        # a1 的 URL 尾段 `owner/repo` 同样含独立 repo token。
        self.assertEqual((total_repo, set(ids_repo)), (3, {"qq:900:a1", "qq:900:a5", "qq:900:mx3"}))

    def test_reverse_mixed_script_document(self) -> None:
        # `repo推荐这个`（ASCII 在前）：q=repo / q=推荐 / q=这个 全命中。
        _, ids_rec = self._search("推荐")
        _, ids_repo = self._search("repo")
        _, ids_zhe = self._search("这个")
        self.assertIn("qq:900:mx3", ids_rec)
        self.assertIn("qq:900:mx3", ids_repo)
        self.assertIn("qq:900:mx3", ids_zhe)

    def test_ascii_word_repo_url_code_error_matrix(self) -> None:
        # keyword 是单一 term；多词 AND 组合属于既有 lexical contract，不在本回归内重复。
        cases = {
            "ImportError": {"qq:900:a2"},
            "foo_bar": {"qq:900:a3"},
            "owner/repo": {"qq:900:a1"},
            "github.com": {"qq:900:a1"},
            "DeepSeek": {"qq:900:a4", "qq:900:a5"},
            "Harness": {"qq:900:a4"},
            "排查": {"qq:900:a4"},
        }
        for keyword, expected in cases.items():
            with self.subTest(keyword=keyword):
                total, ids = self._search(keyword)
                if expected:
                    self.assertEqual(total, len(expected))
                    self.assertEqual(set(ids), expected)
                else:
                    self.assertEqual(total, 0)

    def test_mixed_cjk_ascii_query_and_document(self) -> None:
        total, ids = self._search("推荐这个repo")
        self.assertEqual(total, 1)
        self.assertEqual(ids[0], "qq:900:a5")

    def test_punctuated_document_does_not_leak_matches(self) -> None:
        total, ids = self._search("天气不错")
        self.assertEqual((total, set(ids)), (1, {"qq:900:p1"}))

    def test_stale_strategy_is_rejected_explicitly(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE trivae_derived_meta SET value='unicode61-v0' WHERE key='lexical_tokenizer_strategy'"
            )
        with self.assertRaises(LexicalIndexError):
            self._search("推荐")

    def test_v1_index_is_rejected_by_v2_reader(self) -> None:
        # strategy 升级后，v1 索引绝不能被静默接受；必须显式 stale 要求 rebuild。
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE trivae_derived_meta SET value='unicode61+cjk-bigram-v1' "
                "WHERE key='lexical_tokenizer_strategy'"
            )
        with self.assertRaises(LexicalIndexError):
            self._search("推荐")

    def test_rebuild_after_stale_meta_restores_service(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "UPDATE trivae_derived_meta SET value='unicode61+cjk-bigram-v1' "
                "WHERE key='lexical_tokenizer_strategy'"
            )
        self.index.rebuild()
        total, ids = self._search("推荐")
        self.assertEqual(total, 7)

    def test_missing_meta_table_is_rejected_explicitly(self) -> None:
        self.index.drop()
        with self.assertRaises(LexicalIndexError):
            self._search("推荐")

    def test_strategy_id_version_is_stable_contract(self) -> None:
        self.assertEqual(FTS_TOKENIZER_STRATEGY_ID, "unicode61+cjk-bigram-v2")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
