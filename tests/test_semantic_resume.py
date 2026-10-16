"""语义索引在已持久化 batch 后中断的确定性续建回归。"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Sequence
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from tests.test_ingestion import make_message, write_export
from trivae.bootstrap.application import TrivaeApplication, create_application
from trivae.capabilities import ExecutionScope, SemanticSearchInput
from trivae.interfaces import cli
from trivae.retrieval.semantic.chunking import SemanticChunkConfig, SemanticChunker
from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticEmbeddingError,
    SemanticIndexStale,
    SemanticIndexStorageError,
    SemanticIndexUnavailable,
    SemanticRetrievalResult,
)
from trivae.retrieval.semantic.index import SQLiteSemanticIndex
from trivae.retrieval.structured import MessageQuery


class _ResumeProvider:
    """按正文确定向量，并在指定 batch 显式失败以复现部分持久化。"""

    identity = EmbeddingModelIdentity(
        provider="test-provider",
        model="resume-regression",
        dimension=3,
        pooling="last_token",
        normalized=True,
        query_instruction="resume fixture retrieval",
    )
    document_batch_size = 2

    def __init__(self, *, fail_batch: int | None = None) -> None:
        self.fail_batch = fail_batch
        self.preload_count = 0
        self.batches: list[tuple[str, ...]] = []
        self.documents: list[str] = []

    def preload(self) -> None:
        """记录校验拒绝发生在模型加载前。"""

        self.preload_count += 1

    @staticmethod
    def _vector(text: str) -> tuple[float, ...]:
        """每段文本使用稳定向量，便于与不中断构建逐字节比较。"""

        if "远程连接" in text:
            return 1.0, 0.0, 0.0
        if "情感锚点" in text:
            return 0.0, 1.0, 0.0
        return 0.0, 0.0, 1.0

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.batches.append(tuple(texts))
        if len(self.batches) == self.fail_batch:
            raise SemanticEmbeddingError("fixture embedding interrupted after committed batch")
        self.documents.extend(texts)
        return tuple(self._vector(text) for text in texts)

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._vector(text)


def _import_fixture(application: TrivaeApplication, root: Path) -> None:
    """导入一个三 child 原生 Parent 和一个四 child 转发容器。"""

    raw = root / "raw"
    raw.mkdir()
    timestamp = 1_768_435_200_000
    forward = make_message("root", 4, timestamp + 4_000, "[聊天记录]", message_type="forward")
    forward["content"]["elements"] = [
        {
            "type": "forward",
            "data": {
                "messages": [
                    make_message("remote", 1, 1_000, "远程连接的真实内部讨论"),
                    make_message("emotion", 2, 2_000, "情感锚点的真实内部讨论"),
                    make_message("other", 3, 3_000, "第三条内部正文"),
                    make_message("last", 4, 4_000, "第四条内部正文"),
                ]
            },
        }
    ]
    write_export(
        raw,
        "resume(100).json",
        [
            *(make_message(f"native-{index}", index, timestamp + index * 1_000, f"原生消息 {index} 正文")
              for index in range(3)),
            forward,
        ],
        chat_name="Resume 群",
        peer_uid=None,
        version="5.5.64",
    )
    application.import_directory(raw)


def _configure_chunks(application: TrivaeApplication) -> None:
    """只给回归使用小分块，让一个 Parent 必须跨越多个持久 batch。"""

    assert application._semantic_builder is not None
    application._semantic_builder.chunker = SemanticChunker(
        SemanticChunkConfig(
            parent_max_messages=3,
            child_min_chars=1,
            child_max_messages=1,
            child_overlap_messages=0,
            semantic_void_skip_threshold=0,
        )
    )
    # Builder 与 Retrieval 必须共享同一 chunker identity，避免测试自身制造 stale。
    assert application.semantic_retrieval is not None
    application.semantic_retrieval.chunker = application._semantic_builder.chunker


def _rows(index: SQLiteSemanticIndex) -> tuple[tuple[object, ...], ...]:
    """在测试中比较全部 metadata 和原始向量，防止复用造成重复或错配。"""

    return tuple(
        tuple(row)
        for row in index._connection.execute(
            """
            SELECT c.*, v.embedding FROM semantic_chunks AS c
            JOIN semantic_vectors_3 AS v ON v.vector_id = c.vector_id
            ORDER BY c.vector_id
            """
        )
    )


class SemanticResumeTests(unittest.TestCase):
    """显式续建复用同源已存块，拒绝 stale、损坏和不可恢复的状态。"""

    def test_resume_only_embeds_missing_chunks_and_matches_clean_build(self) -> None:
        """分别中断原生 Parent 和跨 native/forward batch，重开后输出完全一致。"""

        for fail_batch in (2, 3):
            with self.subTest(fail_batch=fail_batch), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                database = root / "app.sqlite3"
                provider = _ResumeProvider(fail_batch=fail_batch)
                with create_application(database, semantic_provider=provider) as application:
                    _import_fixture(application, root)
                    _configure_chunks(application)
                    with self.assertRaisesRegex(SemanticEmbeddingError, "after committed batch"):
                        application.rebuild_semantic_index()
                    assert application._semantic_index is not None
                    state = application._semantic_index.state()
                    assert state is not None
                    saved_count = state.chunk_count
                    self.assertEqual(state.status, "failed")
                    self.assertEqual(saved_count, (fail_batch - 1) * 2)
                    # 第一种仅完成部分 Parent；第二种已跨流写入，但 flush 未返回时水位仍是零。
                    self.assertEqual(state.indexed_message_count, 0)

                resumed_provider = _ResumeProvider()
                with create_application(database, semantic_provider=resumed_provider) as resumed:
                    _configure_chunks(resumed)
                    stats = resumed.rebuild_semantic_index(resume=True)
                    assert resumed._semantic_index is not None
                    actual_rows = _rows(resumed._semantic_index)
                    self.assertEqual(stats.reused_chunk_count, saved_count)
                    self.assertEqual(stats.embedding_count, 7 - saved_count)
                    self.assertEqual(len(resumed_provider.documents), stats.embedding_count)
                    self.assertTrue(set(provider.documents).isdisjoint(resumed_provider.documents))
                    self.assertEqual(stats.chunk_count, 7)
                    self.assertEqual(stats.indexed_message_count, 4)
                    self.assertEqual(stats.indexed_forwarded_message_count, 4)
                    self.assertEqual(stats.to_dict()["reused_chunk_count"], saved_count)
                    self.assertEqual(resumed.validate_semantic_index().status, "valid")
                    envelope = resumed.invoke_tool(
                        "semantic_search",
                        SemanticSearchInput(
                            query="远程连接", session_ids=("qq:100",), limit=1,
                            context_before=1, context_after=1,
                        ),
                        ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                    )
                    self.assertEqual(envelope.status, "ok")
                    actual_result = envelope.data
                    assert isinstance(actual_result, SemanticRetrievalResult)
                    self.assertEqual(resumed.read_repository.count_messages(MessageQuery(limit=1)), 4)

                with create_application(
                    database, semantic_index_path=root / "clean.sqlite3", semantic_provider=_ResumeProvider()
                ) as clean:
                    _configure_chunks(clean)
                    clean_stats = clean.rebuild_semantic_index()
                    assert clean._semantic_index is not None
                    self.assertEqual(actual_rows, _rows(clean._semantic_index))
                    for field in (
                        "status", "canonical_message_count", "indexed_message_count", "eligible_message_count",
                        "semantic_void_message_count", "parent_count", "chunk_count", "skipped_void_chunks",
                        "forwarded_message_count", "indexed_forwarded_message_count", "eligible_forwarded_message_count",
                    ):
                        self.assertEqual(getattr(stats, field), getattr(clean_stats, field), field)
                    clean_result = clean.invoke_tool(
                        "semantic_search",
                        SemanticSearchInput(
                            query="远程连接", session_ids=("qq:100",), limit=1,
                            context_before=1, context_after=1,
                        ),
                        ExecutionScope(allowed_session_ids=("qq:100",), max_results=1),
                    ).data
                    assert isinstance(clean_result, SemanticRetrievalResult)
                    # 检索耗时自然不同；命中、恢复正文、来源和覆盖事实必须全部一致。
                    self.assertEqual(actual_result.hits, clean_result.hits)
                    self.assertEqual(actual_result.expanded_messages, clean_result.expanded_messages)
                    self.assertEqual(actual_result.primary_message_ids, clean_result.primary_message_ids)
                    self.assertEqual(actual_result.coverage, clean_result.coverage)
                    self.assertEqual(actual_result.partial, clean_result.partial)
                    self.assertEqual(actual_result.truncated, clean_result.truncated)

    def test_resume_accepts_committed_rows_ahead_of_building_progress(self) -> None:
        """模拟强停窗口：批次原子写入，但 progress 事务还未开始。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with create_application(root / "app.sqlite3", semantic_provider=_ResumeProvider()) as application:
                _import_fixture(application, root)
                _configure_chunks(application)
                assert application._semantic_index is not None
                index = application._semantic_index
                # 让 write 后的 progress 中断，再把状态还原成强停留下的 building。
                with patch.object(index, "update_progress", side_effect=KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        application.rebuild_semantic_index()
                with index._connection:
                    index._connection.execute(
                        "UPDATE semantic_index_state SET status = 'building', chunk_count = 0, last_error = NULL"
                    )
                provider = _ResumeProvider()
                application._semantic_builder.provider = provider
                stats = application.rebuild_semantic_index(resume=True)
                self.assertEqual(stats.status, "completed")
                # 一个 flush 先提交三批共六块，再统一写 progress；强停时六块均可复用。
                self.assertEqual(stats.reused_chunk_count, 6)
                self.assertEqual(stats.embedding_count, 1)
                self.assertEqual(application.validate_semantic_index().status, "valid")

    def test_resume_rejects_source_or_identity_changes_without_mutation(self) -> None:
        """identity、revision、原生/转发计数漂移都必须在模型加载与写入前拒绝。"""

        for changed in ("identity", "revision", "canonical_count", "forwarded_count"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                provider = _ResumeProvider(fail_batch=2)
                with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                    _import_fixture(application, root)
                    _configure_chunks(application)
                    with self.assertRaises(SemanticEmbeddingError):
                        application.rebuild_semantic_index()
                    assert application._semantic_builder is not None
                    assert application._semantic_index is not None
                    builder = application._semantic_builder
                    index = application._semantic_index
                    previous_state = index.state()
                    previous_rows = _rows(index)
                    if changed == "identity":
                        provider.identity = replace(provider.identity, model="changed-model")
                        change = patch.object(builder, "provider", provider)
                    elif changed == "revision":
                        revision = application.read_repository.canonical_revision()
                        change = patch.object(application.read_repository, "canonical_revision", return_value=revision + 1)
                    elif changed == "canonical_count":
                        change = patch.object(application.read_repository, "count_messages", return_value=5)
                    else:
                        change = patch.object(application.read_repository, "count_forwarded_messages", return_value=5)
                    with change, self.assertRaises(SemanticIndexStale):
                        application.rebuild_semantic_index(resume=True)
                    self.assertEqual(index.state(), previous_state)
                    self.assertEqual(_rows(index), previous_rows)
                    self.assertEqual(provider.preload_count, 1)

    def test_missing_and_completed_resume_are_rejected(self) -> None:
        """显式续建不隐式创建新索引，也不重新计算已完成索引。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = _ResumeProvider()
            with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                _import_fixture(application, root)
                _configure_chunks(application)
                with self.assertRaisesRegex(SemanticIndexUnavailable, "missing"):
                    application.rebuild_semantic_index(resume=True)
                self.assertEqual(provider.preload_count, 0)
                application.rebuild_semantic_index()
                assert application._semantic_index is not None
                previous_state = application._semantic_index.state()
                with self.assertRaisesRegex(SemanticIndexUnavailable, "completed"):
                    application.rebuild_semantic_index(resume=True)
                self.assertEqual(application._semantic_index.state(), previous_state)
                self.assertEqual(provider.preload_count, 1)

    def test_empty_failed_index_and_partial_index_can_resume(self) -> None:
        """首次模型失败没有 vec 表，partial 的全部旧块也允许显式复用。"""

        for status in ("failed", "partial"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                provider = _ResumeProvider(fail_batch=1 if status == "failed" else None)
                with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                    _import_fixture(application, root)
                    _configure_chunks(application)
                    assert application._semantic_index is not None
                    if status == "failed":
                        with self.assertRaises(SemanticEmbeddingError):
                            application.rebuild_semantic_index()
                    else:
                        application.rebuild_semantic_index()
                        application._semantic_index.finish("partial", "fixture incomplete coverage")
                    resumed_provider = _ResumeProvider()
                    assert application._semantic_builder is not None
                    application._semantic_builder.provider = resumed_provider
                    stats = application.rebuild_semantic_index(resume=True)
                    self.assertEqual(stats.status, "completed")
                    self.assertEqual(stats.embedding_count, 7 if status == "failed" else 0)
                    self.assertEqual(stats.reused_chunk_count, 0 if status == "failed" else 7)
                    self.assertEqual(len(resumed_provider.documents), stats.embedding_count)

    def test_resume_exposes_metadata_vector_corruption(self) -> None:
        """孤立 metadata/vector、错误 metadata 与夸大水位都不能静默继续。"""

        mutations = {
            "missing_vector": "DELETE FROM semantic_vectors_3 WHERE vector_id = 1",
            "orphan_vector": "DELETE FROM semantic_chunks WHERE vector_id = 1",
            "metadata": "UPDATE semantic_chunks SET effective_chars = effective_chars + 1 WHERE vector_id = 1",
            "progress": "UPDATE semantic_index_state SET chunk_count = chunk_count + 1",
        }
        for corruption, sql in mutations.items():
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                provider = _ResumeProvider(fail_batch=2)
                with create_application(root / "app.sqlite3", semantic_provider=provider) as application:
                    _import_fixture(application, root)
                    _configure_chunks(application)
                    with self.assertRaises(SemanticEmbeddingError):
                        application.rebuild_semantic_index()
                    assert application._semantic_index is not None
                    index = application._semantic_index
                    with index._connection:
                        index._connection.execute(sql)
                    previous_rows = _rows(index)
                    with self.assertRaises(SemanticIndexStorageError):
                        application.rebuild_semantic_index(resume=True)
                    self.assertEqual(_rows(index), previous_rows)
                    self.assertEqual(len(provider.documents), 2)


class SemanticResumeCLITests(unittest.TestCase):
    """CLI 仅透传显式 resume 选择，错误保留统一 SemanticError 投影。"""

    def test_cli_rebuild_passes_resume_to_application(self) -> None:
        """解析和真正执行 resume 都经过 Application facade。"""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "app.sqlite3"
            with create_application(database, semantic_provider=_ResumeProvider(fail_batch=2)) as application:
                _import_fixture(application, root)
                _configure_chunks(application)
                with self.assertRaises(SemanticEmbeddingError):
                    application.rebuild_semantic_index()
            with create_application(database, semantic_provider=_ResumeProvider()) as reopened:
                _configure_chunks(reopened)
                output = StringIO()
                with patch.object(cli, "create_application", return_value=reopened), redirect_stdout(output):
                    exit_code = cli.main(["semantic", "rebuild", "--database", str(database), "--resume"])
                self.assertEqual(exit_code, 0)
                self.assertIn('"reused_chunk_count": 2', output.getvalue())
                self.assertIn('"embedding_count": 5', output.getvalue())

    def test_cli_missing_resume_is_an_explicit_error(self) -> None:
        """缺失索引的 resume 返回 typed 非零错误，不触发默认重建。"""

        with tempfile.TemporaryDirectory() as temporary:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = cli.main(
                    ["semantic", "rebuild", "--database", str(Path(temporary) / "app.sqlite3"), "--resume"]
                )
            self.assertEqual(exit_code, 1)
            self.assertIn('"error_code": "SEMANTIC_INDEX_NOT_READY"', output.getvalue())
            self.assertIn("missing", output.getvalue())


if __name__ == "__main__":
    unittest.main()
