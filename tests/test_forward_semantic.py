"""合并转发经过真实 sqlite-vec、Canonical 恢复和 Tool 的语义回归。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Sequence

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, SemanticSearchInput
from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticIndexStale,
    SemanticQuery,
    SemanticRetrievalResult,
)
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.structured import MessageQuery


class _ForwardEmbeddingProvider:
    """用可区分正文的向量检查完整链路，模型质量由真实数据验证承担。"""

    identity = EmbeddingModelIdentity(
        provider="test-provider",
        model="forward-regression",
        dimension=3,
        pooling="last_token",
        normalized=True,
        query_instruction="forward regression retrieval",
    )
    document_batch_size = 8

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []

    def preload(self) -> None:
        """回归 provider 不加载外部模型。"""

    @staticmethod
    def _vector(text: str) -> tuple[float, ...]:
        """两个真实漏检词分别对应不同向量，便于核对返回的具体子消息。"""

        if "远程连接" in text:
            return (1.0, 0.0, 0.0)
        if "情感锚点" in text:
            return (0.0, 1.0, 0.0)
        return (0.0, 0.0, 1.0)

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.documents.extend(texts)
        return tuple(self._vector(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        self.queries.append(text)
        return self._vector(text)


def _forward(message_id: str, timestamp: int, children: list[dict[str, Any]]) -> dict[str, Any]:
    """构造真实 QCE 结构；preview 故意不能被当作已展开正文。"""

    message = make_message(message_id, 1, timestamp, "仅存在于预览的内容", message_type="forward")
    message["content"]["elements"] = [
        {"type": "forward", "data": {"messages": children, "preview": ["不应参与语义索引"]}}
    ]
    return message


def _write_group(raw: Path, group: int, messages: list[dict[str, Any]]) -> None:
    """通过真实 importer 建立 canonical 数据，避免手工伪造投影绕过解析链路。"""

    write_export(
        raw,
        f"semantic-forward({group}).json",
        messages,
        chat_name=f"Forward Group {group}",
        peer_uid=None,
        version="5.5.64",
    )


class ForwardSemanticTests(unittest.TestCase):
    """内部 occurrence 保留原始定位，当前群与转发时间始终决定查询边界。"""

    def test_nested_short_content_is_indexed_and_empty_nodes_remain_missing(self) -> None:
        """深层短正文也必须进向量索引，空节点预览不能伪装为真实内容。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            outer_time = 1_768_435_200_000
            _write_group(
                raw,
                100,
                [
                    _forward(
                        "root",
                        outer_time,
                        [
                            make_message("remote", 1, 1000, "远程连接"),
                            _forward("nested", 2000, [make_message("emotion", 1, 500, "情感锚点")]),
                            _forward("missing", 3000, []),
                        ],
                    )
                ],
            )
            provider = _ForwardEmbeddingProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()
                self.assertEqual(stats.canonical_message_count, 1)
                self.assertEqual(stats.indexed_message_count, 1)
                self.assertEqual(stats.forwarded_message_count, 4)
                self.assertEqual(stats.indexed_forwarded_message_count, 4)
                self.assertEqual(stats.eligible_forwarded_message_count, 2)
                self.assertEqual(stats.semantic_void_forwarded_message_count, 2)
                self.assertEqual(application.read_repository.count_messages(MessageQuery(limit=1)), 1)
                self.assertEqual(application.validate_semantic_index().status, "valid")
                self.assertEqual(len(provider.documents), 2)
                self.assertTrue(all("仅存在于预览" not in text for text in provider.documents))
                self.assertTrue(all("[转发时间范围]" in text for text in provider.documents))

                for keyword, source_id, locator in (
                    ("远程连接", "remote", "qq:100:root#forward:0.0"),
                    ("情感锚点", "emotion", "qq:100:root#forward:0.1.0.0"),
                ):
                    envelope = application.invoke_tool(
                        "semantic_search",
                        SemanticSearchInput(
                            query=keyword,
                            session_ids=("qq:100",),
                            limit=1,
                            context_before=0,
                            context_after=0,
                        ),
                        ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                    )
                    self.assertEqual(envelope.status, "partial")
                    self.assertIsInstance(envelope.data, SemanticRetrievalResult)
                    assert isinstance(envelope.data, SemanticRetrievalResult)
                    message = envelope.data.expanded_messages[0]
                    self.assertEqual(message.internal_message_id, locator)
                    self.assertEqual(message.source_message_id, source_id)
                    self.assertEqual(message.normalized_content, keyword)
                    self.assertEqual(message.timestamp, outer_time)
                    assert message.forward is not None
                    self.assertEqual(message.forward.root_message_id, "qq:100:root")
                    self.assertTrue(message.forward.path.endswith("data.messages[0]"))
                    self.assertIsNotNone(message.forward.source_file)
                    self.assertEqual(message.forward.source_record_index, 0)
                    self.assertIn("unexpanded_forward_content", envelope.data.coverage.known_gaps)
                    self.assertEqual(envelope.data.metadata.details["unexpanded_forward_node_count"], 1)

    def test_duplicate_and_cross_group_occurrences_are_not_collapsed(self) -> None:
        """同一原始 ID 在不同转发父消息与群中拥有不同可引用来源。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            child = make_message("same-original", 1, 1000, "远程连接")
            _write_group(raw, 100, [_forward("a", 2000, [child]), _forward("b", 3000, [child])])
            _write_group(raw, 200, [_forward("a", 4000, [child])])
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                assert application.semantic_retrieval is not None
                local = application.semantic_retrieval.search(
                    SemanticQuery(query="远程连接", session_ids=("qq:100",), limit=10)
                )
                global_result = application.semantic_retrieval.search(SemanticQuery(query="远程连接", limit=10))
                self.assertEqual(len(local.expanded_messages), 2)
                self.assertEqual({message.session_id for message in local.expanded_messages}, {"qq:100"})
                self.assertEqual(len({message.internal_message_id for message in global_result.expanded_messages}), 3)
                self.assertEqual({message.source_message_id for message in global_result.expanded_messages}, {"same-original"})

    def test_distinct_forward_elements_do_not_form_one_conversation(self) -> None:
        """同一外层消息里的两个合并记录也有各自的分块与邻居边界。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            parent = _forward("root", 2000, [make_message("remote", 1, 1000, "远程连接")])
            parent["content"]["elements"].append(
                {"type": "forward", "data": {"messages": [make_message("emotion", 1, 500, "情感锚点")]}}
            )
            _write_group(raw, 100, [parent])
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()
                self.assertEqual(stats.chunk_count, 2)
                self.assertEqual(application.validate_semantic_index().status, "valid")
                assert application.semantic_retrieval is not None
                result = application.semantic_retrieval.search(
                    SemanticQuery(query="情感锚点", session_ids=("qq:100",), limit=1, context_before=5, context_after=5)
                )
                self.assertEqual([message.source_message_id for message in result.expanded_messages], ["emotion"])
                assert result.expanded_messages[0].forward is not None
                self.assertEqual(result.expanded_messages[0].forward.container_path, "content.elements[1]")

    def test_forwarded_media_caption_keeps_its_actual_text(self) -> None:
        """QQ 的图片优先类型不能让合并记录里的实际文字也被当作纯媒体丢弃。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            child = make_message("caption", 1, 1000, "[图片:figure.png]\n远程连接")
            child["content"]["elements"].append({"type": "image", "data": {"file": "figure.png"}})
            # 同样的图片正文作为普通消息时，仍保留本次任务之前的原生过滤行为。
            _write_group(raw, 100, [_forward("root", 2000, [child]), child])
            provider = _ForwardEmbeddingProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()
                self.assertEqual(stats.eligible_forwarded_message_count, 1)
                self.assertEqual(stats.canonical_message_count, 2)
                self.assertEqual(stats.eligible_message_count, 0)
                self.assertEqual(stats.semantic_void_message_count, 2)
                self.assertEqual(stats.chunk_count, 1)
                self.assertIn("远程连接", provider.documents[0])
                self.assertNotIn("figure.png", provider.documents[0])
                assert application.semantic_retrieval is not None
                result = application.semantic_retrieval.search(SemanticQuery(query="远程连接", session_ids=("qq:100",)))
                self.assertEqual(result.expanded_messages[0].source_message_id, "caption")
                self.assertEqual(result.expanded_messages[0].message_type, "image")

    def test_scope_is_applied_before_vector_top_k(self) -> None:
        """大量其他群的完全同文候选不能挤掉目标群唯一 occurrence。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            child = make_message("original", 1, 1000, "远程连接")
            _write_group(raw, 100, [_forward(f"outside-{index}", 2000, [child]) for index in range(30)])
            _write_group(raw, 200, [_forward("target", 3000, [child])])
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                assert application.semantic_retrieval is not None
                result = application.semantic_retrieval.search(
                    SemanticQuery(query="远程连接", session_ids=("qq:200",), dense_top_k=1, limit=1)
                )
                self.assertEqual(len(result.hits), 1)
                self.assertEqual(result.expanded_messages[0].internal_message_id, "qq:200:target#forward:0.0")

    def test_original_time_does_not_change_current_group_time_scope(self) -> None:
        """内部时间可早于转发多年，范围过滤仍必须采用当前群转发时间。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            _write_group(raw, 100, [_forward("root", 100_000, [make_message("child", 1, 1000, "远程连接")])])
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                assert application.semantic_retrieval is not None
                historical = application.semantic_retrieval.search(
                    SemanticQuery(query="远程连接", session_ids=("qq:100",), start_timestamp=0, end_timestamp=5000)
                )
                current = application.semantic_retrieval.search(
                    SemanticQuery(query="远程连接", session_ids=("qq:100",), start_timestamp=100_000, end_timestamp=100_001)
                )
                self.assertEqual(historical.expanded_messages, ())
                self.assertEqual(len(current.expanded_messages), 1)
                assert current.expanded_messages[0].forward is not None
                self.assertEqual(current.expanded_messages[0].forward.original_timestamp, 1000)

    def test_sender_filter_marks_only_the_matching_child_as_primary(self) -> None:
        """共同 chunk 中的其他发送者可作上下文，但不能冒充本次条件下的直接命中。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            _write_group(
                raw,
                100,
                [
                    _forward(
                        "root",
                        2000,
                        [
                            make_message("alice", 1, 500, "远程连接", sender_uid="alice"),
                            make_message("bob", 2, 600, "情感锚点", sender_uid="bob"),
                        ],
                    )
                ],
            )
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                assert application.semantic_retrieval is not None
                result = application.semantic_retrieval.search(
                    SemanticQuery(query="情感锚点", session_ids=("qq:100",), sender_user_ids=("qq:uid:bob",), limit=1)
                )
                self.assertEqual(result.primary_message_ids, ("qq:100:root#forward:0.1",))
                self.assertEqual(result.hits[0].start_message_id, "qq:100:root#forward:0.1")

    def test_native_candidate_and_neighbors_are_trimmed_to_half_open_time_scope(self) -> None:
        """chunk 与范围相交不代表整段正文都可返回，普通消息行为同样保持准确。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            _write_group(
                raw,
                100,
                [make_message(f"m{index}", index, index * 1000, "远程连接的具体说明以及完整操作记录 " * 2) for index in (1, 2, 3)],
            )
            with create_application(root / "app.sqlite3", semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                assert application.semantic_retrieval is not None
                result = application.semantic_retrieval.search(
                    SemanticQuery(query="远程连接", session_ids=("qq:100",), start_timestamp=2000, end_timestamp=3000)
                )
                self.assertEqual([message.source_message_id for message in result.expanded_messages], ["m2"])
                self.assertEqual(result.primary_message_ids, ("qq:100:m2",))
                self.assertEqual(result.hits[0].start_message_id, "qq:100:m2")
                self.assertEqual(result.hits[0].end_message_id, "qq:100:m2")

    def test_same_count_nested_content_change_makes_index_stale(self) -> None:
        """只改 content_json 不改消息数时，旧向量仍必须在模型调用前被拒绝。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            parent = _forward("root", 2000, [make_message("child", 1, 1000, "远程连接")])
            _write_group(raw, 100, [parent])
            database_path = root / "app.sqlite3"
            provider = _ForwardEmbeddingProvider()
            with create_application(database_path, semantic_provider=provider) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                previous = application.semantic_index_status()
                parent["content"]["elements"][0]["data"]["messages"][0]["content"]["text"] = "情感锚点"
                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        "UPDATE messages SET content_json = ? WHERE internal_message_id = ?",
                        (json.dumps(parent["content"], ensure_ascii=False), "qq:100:root"),
                    )
                changed = application.semantic_index_status()
                self.assertEqual(changed.status, "stale")
                self.assertEqual(changed.canonical_message_count, previous.canonical_message_count)
                self.assertGreater(changed.canonical_revision, previous.canonical_revision)
                assert application.semantic_retrieval is not None
                with self.assertRaises(SemanticIndexStale):
                    application.semantic_retrieval.search(SemanticQuery(query="情感锚点"))
                with self.assertRaises(SemanticIndexStale):
                    application.validate_semantic_index()
                self.assertEqual(provider.queries, [])
                application.rebuild_semantic_index()
                self.assertEqual(application.semantic_index_status().status, "completed")

    def test_legacy_metadata_is_migrated_and_old_chunker_identity_is_rejected(self) -> None:
        """旧文件可以读出 stale 状态，不能因为 schema 新增列而崩溃或冒充可用。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            _write_group(raw, 100, [_forward("root", 2000, [make_message("child", 1, 1000, "远程连接")])])
            database_path = root / "app.sqlite3"
            semantic_path = root / "app.semantic.sqlite3"
            with create_application(database_path, semantic_provider=_ForwardEmbeddingProvider()) as application:
                application.import_directory(raw)
                assert application._semantic_builder is not None
                identity = application._semantic_builder.identity.to_dict()
                identity["chunker_version"] = "trivae-semantic-chunker-v1"
            # 此处只构造历史 metadata schema；派生文件里没有任何聊天正文。
            semantic_path.unlink()
            with sqlite3.connect(semantic_path) as connection:
                connection.execute(
                    "CREATE TABLE semantic_index_state (state_id INTEGER PRIMARY KEY, identity_json TEXT NOT NULL, "
                    "status TEXT NOT NULL, canonical_message_count INTEGER NOT NULL, indexed_message_count INTEGER NOT NULL, "
                    "chunk_count INTEGER NOT NULL, last_error TEXT, updated_at INTEGER NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO semantic_index_state VALUES (1, ?, 'completed', 1, 1, 0, NULL, 0)",
                    (json.dumps(identity),),
                )
            with create_application(database_path, semantic_provider=_ForwardEmbeddingProvider()) as application:
                self.assertEqual(application.semantic_index_status().status, "stale")
                assert application.semantic_retrieval is not None
                with self.assertRaises(SemanticIndexStale):
                    application.semantic_retrieval.search(SemanticQuery(query="远程连接"))
            # 新增列已持久保存，关闭再打开仍能读取完整的来源计数状态。
            index = SQLiteSemanticIndex(semantic_path)
            try:
                state = index.state()
                assert state is not None
                self.assertEqual(state.forwarded_message_count, 0)
                self.assertEqual(state.canonical_revision, 0)
            finally:
                index.close()

    def test_canonical_change_during_rebuild_keeps_explicit_failed_state(self) -> None:
        """构建期间变化的 canonical 不能产出 completed 的混合快照索引。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            parent = _forward("root", 2000, [make_message("child", 1, 1000, "远程连接")])
            _write_group(raw, 100, [parent])
            database_path = root / "app.sqlite3"

            class UpdatingProvider(_ForwardEmbeddingProvider):
                def preload(self) -> None:
                    # 只在临时 fixture 中复现“计数不变，构建快照却改变”的真实漂移类型。
                    parent["content"]["elements"][0]["data"]["messages"][0]["content"]["text"] = "情感锚点"
                    with sqlite3.connect(database_path) as connection:
                        connection.execute(
                            "UPDATE messages SET content_json = ? WHERE internal_message_id = ?",
                            (json.dumps(parent["content"], ensure_ascii=False), "qq:100:root"),
                        )

            with create_application(database_path, semantic_provider=UpdatingProvider()) as application:
                application.import_directory(raw)
                with self.assertRaisesRegex(SemanticIndexStale, "changed during semantic rebuild"):
                    application.rebuild_semantic_index()
                assert application._semantic_index is not None
                state = application._semantic_index.state()
                assert state is not None
                self.assertEqual(state.status, "failed")
                self.assertIn("canonical messages changed during semantic rebuild", state.last_error or "")


if __name__ == "__main__":
    unittest.main()
