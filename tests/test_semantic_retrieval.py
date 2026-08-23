from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import create_application
from trivae.capabilities import ExecutionScope, SemanticSearchInput
from trivae.observability.collector import TraceCollector
from trivae.observability.projection import project_trace
from trivae.query.evidence import build_tool_result_record
from trivae.query.runtime.openai_tools import SemanticSearchSDKToolAdapter
from trivae.retrieval.semantic.chunking import SemanticChunker
from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticIndexIdentity,
    SemanticMessage,
    SemanticQueryError,
    SemanticRetrievalResult,
)
from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider


class _DeterministicProvider:
    """用固定三维向量验证索引链路，不把 fixture 误称为模型质量评测。"""

    identity = EmbeddingModelIdentity(
        provider="test-provider",
        model="semantic-fixture",
        dimension=3,
        pooling="last_token",
        normalized=True,
        query_instruction="fixture retrieval instruction",
    )
    document_batch_size = 8

    def __init__(self) -> None:
        self.document_batches: list[tuple[str, ...]] = []
        self.query_texts: list[str] = []

    def preload(self) -> None:
        """确定性 fixture 没有模型资源，但遵守显式加载计时 contract。"""

    def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        """让包含 budget 的 child 与 query 对齐，其余 child 使用正交向量。"""

        self.document_batches.append(tuple(texts))
        return tuple((1.0, 0.0, 0.0) if "budget" in text else (0.0, 1.0, 0.0) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        """固定 query 向量，只用于验证 score/range/citation 主链路。"""

        self.query_texts.append(text)
        return (1.0, 0.0, 0.0)


def _semantic_message(message_id: str, timestamp: int, content: str, *, sender: str = "Alice") -> SemanticMessage:
    """构造不依赖 SQLite 的 chunker projection。"""

    return SemanticMessage(
        internal_message_id=message_id,
        session_id="session-1",
        session_display="Semantic Fixture",
        sender_name=sender,
        sender_user_id="u-1",
        timestamp=timestamp,
        message_type="text",
        normalized_content=content,
        system=False,
        recalled=False,
    )


def _write_semantic_fixture(root: Path) -> Path:
    """写入两个有时间间隔的 parent，确保测试覆盖 range metadata。"""

    raw = root / "raw"
    raw.mkdir()
    base = 1_768_435_200_000
    write_export(
        raw,
        "semantic(100).json",
        [
            make_message("m1", 1, base, "budget plan " + "detail " * 30),
            make_message(
                "m2",
                2,
                base + 2 * 60 * 60 * 1000,
                "meeting notes " + "detail " * 30,
                sender_uid="u_other",
            ),
        ],
        chat_name="Semantic Fixture",
        peer_uid=None,
        version="5.5.64",
    )
    return raw


class SemanticRetrievalTests(unittest.TestCase):
    """验证 semantic vertical slice 的 deterministic contract 和失败边界。"""

    def test_chunker_preserves_void_range_but_excludes_void_text(self) -> None:
        """semantic void 仍参与 canonical range，embedding input 只保留有效正文。"""

        chunker = SemanticChunker()
        result = chunker.chunk(
            (
                _semantic_message("m1", 1_000, "好"),
                _semantic_message("m2", 1_500, "[图片:x.png]", sender="Alice"),
                _semantic_message("m3", 2_000, "预算计划 " + "细节 " * 30),
            )
        )
        self.assertEqual(len(result.chunks), 1)
        chunk = result.chunks[0]
        self.assertEqual(chunk.message_count, 3)
        self.assertIn("预算计划", chunk.embedding_input)
        self.assertNotIn("好", chunk.embedding_input)
        self.assertNotIn("图片:x.png", chunk.embedding_input)
        self.assertIn("[来源]", chunk.embedding_input)
        self.assertIn("[时间范围]", chunk.embedding_input)
        self.assertIn("[参与者]", chunk.embedding_input)

    def test_sentence_transformer_provider_applies_query_instruction_and_validates_shape(self) -> None:
        """provider 只给 query 加 instruction，并对 dimension/normalization 做显式校验。"""

        calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

        class Model:
            def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
                calls.append((tuple(texts), kwargs))
                # 模拟 Qwen bfloat16 Normalize 的微小范数误差，provider 应修正而不是放宽校验。
                return [[1.0024, 0.0, 0.0] for _ in texts]

        provider = SentenceTransformerEmbeddingProvider(
            model="fixture/model",
            dimension=3,
            model_loader=lambda _: Model(),
        )
        provider.embed_documents(("document",))
        provider.embed_query("question")
        self.assertEqual(calls[0][0], ("document",))
        self.assertTrue(calls[1][0][0].startswith("Instruct: "))
        self.assertIn("Query: question", calls[1][0][0])
        self.assertTrue(calls[1][1]["normalize_embeddings"])
        normalized = provider.embed_query("question")
        self.assertAlmostEqual(sum(value * value for value in normalized) ** 0.5, 1.0, places=6)

    def test_sentence_transformer_provider_bounds_real_mps_cache_growth(self) -> None:
        """连续 document batches 按固定间隔释放空闲 MPS cache，CPU provider 不走该路径。"""

        releases: list[str] = []

        class Model:
            device = SimpleNamespace(type="mps")

            def encode(self, texts: list[str], **kwargs: object) -> list[list[float]]:
                return [[1.0, 0.0, 0.0] for _ in texts]

        provider = SentenceTransformerEmbeddingProvider(
            model="fixture/model",
            dimension=3,
            mps_cache_release_interval=2,
            model_loader=lambda _: Model(),
        )
        fake_torch = SimpleNamespace(
            mps=SimpleNamespace(empty_cache=lambda: releases.append("released"))
        )
        with patch(
            "trivae.retrieval.semantic.embedding.importlib.import_module",
            return_value=fake_torch,
        ):
            provider.embed_documents(("first batch",))
            self.assertEqual(releases, [])
            provider.embed_documents(("second batch",))
            self.assertEqual(releases, ["released"])
            provider.embed_query("query")
            self.assertEqual(releases, ["released", "released"])

    def test_index_identity_rejects_secret_fields_without_hashing(self) -> None:
        """identity 使用可读 JSON，secret 字段在构造时直接失败。"""

        with self.assertRaises(SemanticQueryError):
            SemanticIndexIdentity(
                database_identity="fixture.sqlite3",
                embedding=EmbeddingModelIdentity("provider", "model", 3, "last_token", True, "instruction"),
                chunker_version="v1",
                chunker_config={"api_key": "must-not-enter-identity"},
            )
        with self.assertRaises(SemanticQueryError):
            SemanticIndexIdentity(
                database_identity="fixture.sqlite3",
                embedding=EmbeddingModelIdentity("provider", "model", 3, "last_token", True, "instruction"),
                chunker_version="v1",
                chunker_config={"secret": "must-not-enter-identity"},
            )

    def test_application_builds_independent_semantic_index_and_recovers_canonical_messages(self) -> None:
        """builder、vec0、semantic tool 和 current-run evidence 共享同一 canonical range。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            database_path = root / "app.sqlite3"
            provider = _DeterministicProvider()
            with create_application(database_path, semantic_provider=provider) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()
                repeated_stats = application.rebuild_semantic_index()
                integrity = application.validate_semantic_index()
                envelope = application.invoke_tool(
                    "semantic_search",
                    SemanticSearchInput(
                        query="how was the budget planned",
                        session_ids=("qq:100",),
                        limit=1,
                        context_before=0,
                        context_after=0,
                    ),
                    ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                )

                self.assertEqual(stats.status, "completed")
                self.assertEqual(repeated_stats.status, "completed")
                self.assertEqual(stats.eligible_message_count, 2)
                self.assertEqual(stats.semantic_void_message_count, 0)
                self.assertEqual(stats.parent_count, 2)
                self.assertEqual(stats.chunk_count, 2)
                self.assertEqual(stats.embedding_count, 2)
                self.assertEqual(stats.embedding_batch_size, 8)
                # 两个时间分隔的 Parent 共享一个 batch，避免真实模型逐 Parent 低利用率调用。
                self.assertEqual(stats.embedding_batch_count, 1)
                self.assertEqual([len(batch) for batch in provider.document_batches[:1]], [2])
                self.assertGreater(stats.index_size_bytes, 0)
                self.assertEqual(integrity.status, "valid")
                self.assertEqual(integrity.metadata_chunk_count, 2)
                self.assertEqual(integrity.vector_count, 2)
                self.assertEqual(integrity.missing_vector_count, 0)
                self.assertEqual(integrity.orphan_vector_count, 0)
                self.assertEqual(integrity.sampled_range_count, 2)
                self.assertEqual(integrity.recovered_range_count, 2)
                self.assertEqual(envelope.status, "ok")
                self.assertIsInstance(envelope.data, SemanticRetrievalResult)
                assert isinstance(envelope.data, SemanticRetrievalResult)
                self.assertEqual(envelope.data.hits[0].start_message_id, "qq:100:m1")
                self.assertEqual([message.internal_message_id for message in envelope.data.expanded_messages], ["qq:100:m1"])
                self.assertIn("index_identity", envelope.data.metadata.details)

                record = build_tool_result_record(
                    run_id="run-fixture",
                    tool_call_id="run-fixture/tool-call/1",
                    tool_result_id="run-fixture/tool-call/1/result",
                    tool_name="semantic_search",
                    envelope=envelope,
                    scope=ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                )
                self.assertEqual([item.message.internal_message_id for item in record.message_items], ["qq:100:m1"])
                self.assertNotIn("chunk_id", record.to_model_provenance())

            # 重开进程边界后继续验证同一 derived index，而不是依赖内存状态。
            with create_application(database_path, semantic_provider=_DeterministicProvider()) as reopened:
                self.assertEqual(reopened.semantic_index_status().status, "completed")
                self.assertEqual(reopened.validate_semantic_index().status, "valid")

    def test_builder_coalesces_chunks_across_parent_boundaries(self) -> None:
        """大量小 Parent 必须填满 provider batch，同时保持最终 canonical watermark。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            base = 1_768_435_200_000
            # 两小时 gap 强制形成十个 Parent；每个 Parent 只产生一个 child。
            write_export(
                raw,
                "semantic-batches(100).json",
                [
                    make_message(
                        f"batch-{index}",
                        index,
                        base + index * 2 * 60 * 60 * 1000,
                        f"batch marker {index} " + "detail " * 30,
                    )
                    for index in range(10)
                ],
                chat_name="Semantic Batch Fixture",
                peer_uid=None,
                version="5.5.64",
            )
            provider = _DeterministicProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()

            self.assertEqual(stats.status, "completed")
            self.assertEqual(stats.indexed_message_count, 10)
            self.assertEqual(stats.parent_count, 10)
            self.assertEqual(stats.chunk_count, 10)
            self.assertEqual(stats.embedding_batch_count, 2)
            self.assertEqual([len(batch) for batch in provider.document_batches], [8, 2])

    def test_interrupted_rebuild_records_failed_terminal_state(self) -> None:
        """可捕获的 Ctrl+C 不能让已退出进程永久遗留 building 状态。"""

        class InterruptedProvider(_DeterministicProvider):
            def embed_documents(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            with create_application(root / "app.sqlite3", semantic_provider=InterruptedProvider()) as application:
                application.import_directory(raw)
                with self.assertRaises(KeyboardInterrupt):
                    application.rebuild_semantic_index()
                status = application.semantic_index_status()

            self.assertEqual(status.status, "failed")
            self.assertEqual(status.last_error, "KeyboardInterrupt")

    def test_void_only_parents_advance_progress_without_embedding(self) -> None:
        """零 child Parent 不调用模型，但仍计入完整 canonical watermark。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            base = 1_768_435_200_000
            contents = ("好", *(f"valid marker {index} " + "detail " * 30 for index in range(8)), "[图片:x.png]")
            write_export(
                raw,
                "semantic-void-progress(100).json",
                [
                    make_message(
                        f"void-progress-{index}",
                        index,
                        base + index * 2 * 60 * 60 * 1000,
                        content,
                    )
                    for index, content in enumerate(contents)
                ],
                chat_name="Semantic Void Progress Fixture",
                peer_uid=None,
                version="5.5.64",
            )
            provider = _DeterministicProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                application.import_directory(raw)
                stats = application.rebuild_semantic_index()

            self.assertEqual(stats.status, "completed")
            self.assertEqual(stats.indexed_message_count, 10)
            self.assertEqual(stats.semantic_void_message_count, 2)
            self.assertEqual(stats.chunk_count, 8)
            self.assertEqual(stats.embedding_batch_count, 1)
            self.assertEqual([len(batch) for batch in provider.document_batches], [8])

    def test_application_status_distinguishes_missing_completed_and_stale_index(self) -> None:
        """运维 facade 必须把未建、可用和 canonical 漂移分别投影出来。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            with create_application(root / "app.sqlite3", semantic_provider=_DeterministicProvider()) as application:
                application.import_directory(raw)
                missing = application.semantic_index_status()
                self.assertEqual(missing.status, "missing")
                self.assertEqual(missing.canonical_message_count, 2)

                application.rebuild_semantic_index()
                completed = application.semantic_index_status()
                self.assertEqual(completed.status, "completed")
                self.assertEqual(completed.indexed_message_count, 2)
                self.assertEqual(completed.chunk_count, 2)

                write_export(
                    raw,
                    "semantic-status-followup(100).json",
                    [make_message("m3", 3, 1_768_435_200_000 + 4 * 60 * 60 * 1000, "follow-up")],
                    chat_name="Semantic Fixture",
                    peer_uid=None,
                    version="5.5.64",
                )
                application.import_directory(raw)
                stale = application.semantic_index_status()
                self.assertEqual(stale.status, "stale")
                self.assertEqual(stale.canonical_message_count, 3)
                self.assertEqual(stale.indexed_message_count, 2)
                self.assertEqual(stale.to_dict()["persisted_identity"], completed.to_dict()["persisted_identity"])

    def test_semantic_index_not_ready_and_stale_are_explicit_tool_errors(self) -> None:
        """未构建和 canonical 漂移都不能静默回到 lexical。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            provider = _DeterministicProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                application.import_directory(raw)
                request = SemanticSearchInput(query="budget", session_ids=("qq:100",), limit=1)
                scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=1)
                not_ready = application.invoke_tool("semantic_search", request, scope)
                self.assertEqual(not_ready.error.code, "SEMANTIC_INDEX_NOT_READY")

                assert application._semantic_index is not None
                assert application._semantic_builder is not None
                application._semantic_index.start_rebuild(
                    application._semantic_builder.identity,
                    canonical_message_count=2,
                )
                building = application.invoke_tool("semantic_search", request, scope)
                self.assertEqual(building.error.code, "SEMANTIC_INDEX_NOT_READY")
                self.assertEqual(provider.query_texts, [])

                application.rebuild_semantic_index()
                write_export(
                    raw,
                    "semantic-followup(100).json",
                    [make_message("m3", 3, 1_768_435_200_000 + 3 * 60 * 60 * 1000, "new data " + "detail " * 30)],
                    chat_name="Semantic Fixture",
                    peer_uid=None,
                    version="5.5.64",
                )
                application.import_directory(raw)
                stale = application.invoke_tool("semantic_search", request, scope)
                self.assertEqual(stale.error.code, "SEMANTIC_INDEX_STALE")

    def test_semantic_filters_top_k_and_partial_coverage_are_explicit(self) -> None:
        """验证 session/time/sender/type filter、bounded pool 和 partial 状态都可观察。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            base = 1_768_435_200_000
            with create_application(root / "app.sqlite3", semantic_provider=_DeterministicProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                request = SemanticSearchInput(
                    query="meeting",
                    session_ids=("qq:100",),
                    start_timestamp=base + 60 * 60 * 1000,
                    end_timestamp=base + 3 * 60 * 60 * 1000,
                    sender_user_ids=("qq:uid:u_other",),
                    message_types=("text",),
                    limit=1,
                    dense_top_k=1,
                    context_before=0,
                    context_after=0,
                )
                scope = ExecutionScope(allowed_session_ids=("qq:100",), max_results=1)
                complete = application.invoke_tool("semantic_search", request, scope)
                self.assertEqual(complete.status, "ok")
                assert isinstance(complete.data, SemanticRetrievalResult)
                self.assertEqual(complete.data.hits[0].start_message_id, "qq:100:m2")
                self.assertEqual(complete.data.coverage.status, "complete")
                self.assertEqual(complete.data.metadata.details["dense_candidate_pool"], 4)

                assert application._semantic_index is not None
                application._semantic_index.finish("partial", "fixture partial coverage")
                partial = application.invoke_tool("semantic_search", request, scope)
                self.assertEqual(partial.status, "partial")
                assert isinstance(partial.data, SemanticRetrievalResult)
                self.assertTrue(partial.data.partial)
                self.assertEqual(partial.data.coverage.status, "partial")

    def test_semantic_trace_exposes_strategy_and_retrieval_operation(self) -> None:
        """Trace 保留 semantic strategy/index details，错误 owner 仍在 retrieval stage。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = _write_semantic_fixture(root)
            with create_application(root / "app.sqlite3", semantic_provider=_DeterministicProvider()) as application:
                application.import_directory(raw)
                application.rebuild_semantic_index()
                collector = TraceCollector(application._trace_store, trace_id="trace-semantic", request_id="request-semantic")
                envelope = application.capability_registry.invoke(
                    "semantic_search",
                    SemanticSearchInput(query="budget", session_ids=("qq:100",), limit=1),
                    ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                    trace_context=collector.operation_context("query").child("tool:semantic-1"),
                )
                self.assertEqual(envelope.status, "ok")
                projection = project_trace(application._trace_store.read_trace("trace-semantic"))
                retrieval = [item for item in projection.timeline if item.stage == "retrieval"]
                self.assertEqual(retrieval[1].payload["strategy"], "semantic")
                self.assertIn("index_identity", retrieval[1].payload["context_expansion"]["details"])

    def test_semantic_runtime_adapter_exposes_distinct_tool_name(self) -> None:
        """SDK adapter 的公开名称是 semantic_search，而非策略参数化旧工具。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with create_application(root / "app.sqlite3", semantic_provider=_DeterministicProvider()) as application:
                tool = SemanticSearchSDKToolAdapter(application.capability_registry).as_sdk_tool(trusted_max_results=3)
                self.assertEqual(tool.name, "semantic_search")
                properties = tool.params_json_schema["properties"]
                self.assertIn("query", properties)
                self.assertNotIn("keyword", properties)


if __name__ == "__main__":
    unittest.main()
