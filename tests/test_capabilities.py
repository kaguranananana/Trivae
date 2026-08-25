from __future__ import annotations

from pathlib import Path

from tests.test_ingestion import make_message, write_export
from tests.test_lexical_retrieval import LexicalRetrievalTests
from trivae.capabilities import (
    CapabilityContractError,
    CapabilityRegistry,
    ExecutionScope,
    SearchMessagesCapability,
    SearchMessagesInput,
    SearchMessagesTool,
)
from trivae.data.ingestion.importer import SharedImporter
from trivae.retrieval.structured import LexicalQuery


class CapabilityContractTests(LexicalRetrievalTests):
    """验证 Tool wrapper 不复制 Retrieval 逻辑，并继承 trusted scope。"""

    def setUp(self) -> None:
        super().setUp()
        self.capability = SearchMessagesCapability(self.lexical)
        self.tool = SearchMessagesTool(self.capability)
        self.registry = CapabilityRegistry()
        self.registry.register(self.tool)

    def test_registry_valid_search_and_core_semantics_match(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        request = SearchMessagesInput(
            keyword="missing",
            limit=5,
            context_before=0,
            context_after=0,
        )
        direct = self.lexical.search(
            LexicalQuery(keyword="missing", session_ids=("qq:100",), limit=5, context_before=0, context_after=0)
        )
        envelope = self.registry.invoke("search_messages", request, scope)

        self.assertEqual(self.registry.names(), ("search_messages",))
        self.assertEqual(envelope.status, "ok")
        self.assertIsNotNone(envelope.data)
        assert envelope.data is not None
        self.assertEqual(envelope.data.total_hits, direct.total_hits)
        self.assertEqual(envelope.data.returned_messages, direct.returned_messages)
        self.assertEqual(envelope.data.expanded_messages, direct.expanded_messages)
        self.assertEqual(envelope.meta["truncated"], direct.truncated)
        self.assertFalse(hasattr(self.tool, "connection"))
        self.assertNotIn("raw_payload_json", str(envelope.to_dict()))

    def test_default_lexical_search_returns_all_31_hits(self) -> None:
        """默认查询不能把 31 条命中硬截成 20 条。"""

        export = write_export(
            Path(self.temporary.name),
            "limit-regression(100).json",
            [
                make_message(
                    f"limit-{index}",
                    10_000 + index,
                    1_768_435_200_000 + index,
                    "limit-regression marker",
                )
                for index in range(31)
            ],
            chat_name="Session A",
            peer_uid=None,
            version="5.5.64",
        )
        # 重新导入 canonical facts，并显式重建 derived lexical index。
        SharedImporter(self.store).import_paths([export])
        self.index.rebuild()

        envelope = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="limit-regression"),
            ExecutionScope(),
        )

        self.assertEqual(envelope.status, "ok")
        self.assertEqual(envelope.data.total_hits, 31)
        self.assertEqual(len(envelope.data.hits), 31)
        self.assertEqual(envelope.data.metadata.details["returned_hits"], 31)
        self.assertFalse(envelope.data.partial)

    def test_session_and_time_scope_cannot_be_bypassed(self) -> None:
        scope = ExecutionScope(
            allowed_session_ids=("qq:100",),
            start_timestamp=1_768_435_200_000,
            end_timestamp=1_768_867_200_000,
            max_results=5,
        )
        inherited = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="alpha", limit=5, context_before=0, context_after=0),
            scope,
        )
        outside_session = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="alpha", session_ids=("qq:200",), limit=5),
            scope,
        )
        outside_time = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="alpha", start_timestamp=1_768_400_000_000, limit=5),
            scope,
        )

        self.assertEqual(inherited.status, "ok")
        self.assertEqual({message.session_id for message in inherited.data.expanded_messages}, {"qq:100"})
        self.assertEqual(outside_session.status, "error")
        self.assertEqual(outside_session.error.code, "SCOPE_VIOLATION")
        self.assertEqual(outside_time.status, "error")
        self.assertEqual(outside_time.error.code, "SCOPE_VIOLATION")

    def test_invalid_params_and_bound_are_typed_errors(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=3)
        empty = self.registry.invoke(
            "search_messages", SearchMessagesInput(keyword="", limit=3), scope
        )
        over_bound = self.registry.invoke(
            "search_messages", SearchMessagesInput(keyword="alpha", limit=4), scope
        )

        self.assertEqual(empty.status, "error")
        self.assertEqual(empty.error.code, "INVALID_ARGUMENT")
        self.assertEqual(over_bound.status, "error")
        self.assertEqual(over_bound.error.code, "INVALID_ARGUMENT")

    def test_provider_shape_violations_are_not_normalized(self) -> None:
        """DeepSeek 风格的非法字段继续显式失败，不自动修正或扩大 scope。"""

        invalid_cases = (
            ("keyword_type", {"keyword": ["alpha"]}),
            ("empty_session_ids", {"keyword": "alpha", "session_ids": ()}),
            ("timestamp_type", {"keyword": "alpha", "start_timestamp": True}),
            ("reversed_time_range", {"keyword": "alpha", "start_timestamp": 2, "end_timestamp": 1}),
            ("invalid_limit", {"keyword": "alpha", "limit": 0}),
            ("negative_context", {"keyword": "alpha", "context_before": -1}),
            ("wrong_list_item_type", {"keyword": "alpha", "sender_user_ids": (1,)}),
        )
        for name, arguments in invalid_cases:
            with self.subTest(name=name):
                with self.assertRaises(CapabilityContractError):
                    SearchMessagesInput(**arguments)  # type: ignore[arg-type]

        with self.assertRaises(TypeError):
            SearchMessagesInput(keyword="alpha", unknown_field=True)  # type: ignore[call-arg]

    def test_truncation_is_separate_from_partial_status(self) -> None:
        scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=5)
        envelope = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="alpha", limit=5, context_before=2, context_after=2),
            scope,
        )

        self.assertEqual(envelope.status, "ok")
        self.assertTrue(envelope.meta["truncated"])
        self.assertEqual(envelope.data.partial, False)
        self.assertEqual(envelope.data.truncated, True)

    def test_missing_lexical_index_projects_capability_unavailable(self) -> None:
        self.index.drop()
        envelope = self.registry.invoke(
            "search_messages",
            SearchMessagesInput(keyword="alpha", limit=5),
            ExecutionScope(max_results=5),
        )

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.error.code, "CAPABILITY_UNAVAILABLE")
