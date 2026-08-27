"""get_recent_messages capability/contract/ordering regression（Failure A）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_ingestion import make_message, write_export
from trivae.capabilities.contracts import (
    CapabilityContractError,
    CapabilityScopeError,
    ExecutionScope,
    GetRecentMessagesInput,
)
from trivae.capabilities.recent_messages import RecentMessagesCapability
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.structured import MessageQuery, StructuredRetrieval


class RecentMessagesOrderingTests(unittest.TestCase):
    """§4.4 ordering contract：先选窗口内最新 limit 条，再按阅读顺序返回。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "recent.sqlite3"
        messages = [
            make_message(f"m{index}", index, base + index * 60_000, f"message {index}", sender_uid="u_a")
            for index, base in enumerate((1_786_780_800_000,) * 4, start=1)
        ]
        export = write_export(
            directory,
            "Recent(910).json",
            messages,
            chat_name="Recent",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        from trivae.data.ingestion.importer import SharedImporter

        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.retrieval = StructuredRetrieval(self.repository)

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def _retrieve(self, limit: int):
        return self.retrieval.retrieve_recent_messages(MessageQuery(limit=limit))

    def test_latest_limit_selection_returns_chronologically(self) -> None:
        result = self._retrieve(2)
        contents = [m.normalized_content for m in result.messages]
        self.assertEqual(contents, ["message 3", "message 4"])
        self.assertEqual(result.total_hits, 4)
        self.assertEqual(result.returned_count, 2)
        self.assertTrue(result.truncated)

    def test_limit_covering_window_returns_all_in_order(self) -> None:
        result = self._retrieve(10)
        self.assertEqual([m.normalized_content for m in result.messages], [f"message {i}" for i in range(1, 5)])
        self.assertFalse(result.truncated)
        self.assertEqual({m.internal_message_id for m in result.messages}, {
            "qq:910:m1", "qq:910:m2", "qq:910:m3", "qq:910:m4",
        })

    def test_time_window_filtering_is_respected(self) -> None:
        base = 1_786_780_800_000
        result = self.retrieval.retrieve_recent_messages(
            MessageQuery(
                start_timestamp=base + 150_000,
                end_timestamp=base + 400_000,
                limit=1,
            )
        )
        self.assertEqual(result.total_hits, 2)
        self.assertEqual([m.normalized_content for m in result.messages], ["message 4"])


class RecentMessagesCapabilityTests(unittest.TestCase):
    """输入契约、trusted scope、archive_latest resolve 与 zero-result ok。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database_path = directory / "recent-cap.sqlite3"
        base = 1_786_700_000_000
        messages = [
            make_message("r1", 1, base, "第一条", sender_uid="u_a"),
            make_message("r2", 2, base + 86_400_000, "第二条", sender_uid="u_b"),
        ]
        export = write_export(
            directory,
            "Recent Cap(920).json",
            messages,
            chat_name="Recent Cap",
            peer_uid=None,
            version="5.5.64",
        )
        self.store = SQLiteCanonicalStore(self.database_path)
        from trivae.data.ingestion.importer import SharedImporter

        SharedImporter(self.store).import_paths([export])
        self.repository = SQLiteCanonicalReadRepository(self.database_path)
        self.capability = RecentMessagesCapability(StructuredRetrieval(self.repository))
        self.latest = base + 86_400_000

    def tearDown(self) -> None:
        self.repository.close()
        self.store.close()
        self.temporary.cleanup()

    def test_no_args_defaults_to_recent_two_days_archive_latest(self) -> None:
        # B1 contract：SDK `{}` 合法调用 ≡ relative 2 days；不再出现 SDK 合法/Capability 拒绝。
        scope = ExecutionScope(allowed_session_ids=("qq:920",))
        request = GetRecentMessagesInput()
        result = self.capability.execute(request, scope)
        self.assertEqual(result.total_hits, 2)
        query_end = result.query.to_dict()["end_timestamp"]
        self.assertEqual(query_end, self.latest + 1)

    def test_relative_time_range_resolves_archive_latest(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:920",), start_timestamp=None, end_timestamp=None)
        request = GetRecentMessagesInput(
            time_range={"kind": "relative", "amount": 2, "unit": "day", "anchor": "archive_latest"},
            limit=50,
        )
        result = self.capability.execute(request, scope)
        result.query.to_dict()["start_timestamp"]
        query_end = result.query.to_dict()["end_timestamp"]
        # anchor 是 archive latest；end exclusive 已包含最新一条。
        self.assertEqual(query_end, self.latest + 1)
        self.assertEqual(result.total_hits, 2)
        self.assertEqual([m.internal_message_id for m in result.messages], ["qq:920:r1", "qq:920:r2"])

    def test_explicit_time_window_is_honored(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:920",))
        request = GetRecentMessagesInput(
            start_timestamp=1_786_700_000_000,
            end_timestamp=1_786_700_000_001,
            limit=10,
        )
        result = self.capability.execute(request, scope)
        self.assertEqual(result.total_hits, 1)

    def test_reversed_range_and_invalid_inputs_are_contract_errors(self) -> None:
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(start_timestamp=200, end_timestamp=100)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(start_timestamp=100, limit=0)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(time_range={"kind": "relative", "amount": 1, "unit": "hour"}, limit=10)
        with self.assertRaises(CapabilityContractError):
            GetRecentMessagesInput(limit=-1)

    def test_session_scope_cannot_be_bypassed(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:other",))
        request = GetRecentMessagesInput(
            time_range={"kind": "relative", "amount": 1, "unit": "day", "anchor": "archive_latest"},
            session_ids=("qq:920",),
            limit=10,
        )
        with self.assertRaises(CapabilityScopeError):
            self.capability.execute(request, scope)

    def test_relative_anchor_missing_in_empty_scope_is_legal_zero_result(self) -> None:
        # trusted session 无消息时 archive_latest 不存在；zero-result 契约下这是合法空结果
        # 而不是参数错误（旧实现曾抛 CapabilityContractError 导致模型进入无效重试）。
        scope = ExecutionScope(allowed_session_ids=("qq:999",))
        request = GetRecentMessagesInput(
            time_range={"kind": "relative", "amount": 1, "unit": "week", "anchor": "archive_latest"},
            limit=10,
        )
        result = self.capability.execute(request, scope)
        self.assertEqual(result.total_hits, 0)
        self.assertEqual(len(result.messages), 0)
        self.assertFalse(result.truncated)
        self.assertEqual(result.coverage.status, "complete")

    def test_zero_result_is_ok_not_error(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:920",))
        request = GetRecentMessagesInput(
            start_timestamp=1,
            end_timestamp=2,
            limit=10,
        )
        result = self.capability.execute(request, scope)
        self.assertEqual(result.total_hits, 0)
        self.assertEqual(len(result.messages), 0)
        self.assertFalse(result.truncated)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
