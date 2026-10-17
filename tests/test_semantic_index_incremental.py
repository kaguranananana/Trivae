"""真实 sqlite-vec 存储事务、精确输入凭据和旧格式迁移回归。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from trivae.retrieval.semantic.contracts import (
    EmbeddingModelIdentity,
    SemanticChunk,
    SemanticIndexIdentity,
    SemanticIndexStale,
    SemanticIndexStorageError,
)
from trivae.retrieval.semantic.index import SQLiteSemanticIndex

IDENTITY = SemanticIndexIdentity(
    database_identity="store-transaction-fixture",
    embedding=EmbeddingModelIdentity(
        provider="fixture", model="three-dimensional", dimension=3,
        pooling="mean", normalized=True, query_instruction="fixture query",
    ),
    chunker_version="fixture-v1",
    chunker_config={"embedding_max_chars": 6000},
)


def chunk(name: str, timestamp: int, text: str) -> SemanticChunk:
    """范围元数据与输入独立构造，验证相同 ID 不能证明输入相同。"""

    return SemanticChunk(
        chunk_id=name, parent_id=f"parent-{name}", session_id="session",
        parent_start_message_id=name, parent_end_message_id=name,
        start_message_id=name, end_message_id=name,
        start_timestamp=timestamp, end_timestamp=timestamp,
        message_count=1, effective_chars=len(text), embedding_input=text,
    )


def seed(index: SQLiteSemanticIndex) -> tuple[SemanticChunk, SemanticChunk]:
    """两个远隔块形成完整旧快照，后续只修改第一块。"""

    first, last = chunk("first", 1000, "旧正文"), chunk("last", 10000, "保留正文")
    index.start_rebuild(IDENTITY, 2, canonical_revision=7)
    index.insert_chunks(((first, (1.0, 0.0, 0.0)), (last, (0.0, 1.0, 0.0))))
    index.update_progress(2)
    index.finish("completed")
    return first, last


def stored_rows(index: SQLiteSemanticIndex) -> tuple[tuple[object, ...], ...]:
    """读取真实 metadata、内部 ID 和原始 float32，用于断言回滚及未受影响行。"""

    return tuple(tuple(row) for row in index._connection.execute(
        """
        SELECT c.*, v.embedding FROM semantic_chunks AS c
        JOIN semantic_vectors_3 AS v USING(vector_id) ORDER BY c.vector_id
        """
    ))


@pytest.mark.parametrize("interruption", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_incremental_failure_rolls_back_vectors_state_and_ids(tmp_path: Path, interruption: type[BaseException]) -> None:
    """写入多批后失败或强停，重开仍保留旧 revision、coverage 和所有原始字节。"""

    path = tmp_path / "index.sqlite3"
    index = SQLiteSemanticIndex(path)
    first, _ = seed(index)
    before = stored_rows(index)
    state = index.state()
    assert state is not None
    with pytest.raises(interruption, match="interrupt fixture"):
        with index.incremental_transaction(
            IDENTITY, 2, base_revision=7, canonical_revision=8, forwarded_message_count=0,
        ):
            assert index.prepare_incremental_ranges((("session", 1000, 1000),)) == 1
            index.insert_chunks(((replace(first, embedding_input="新正文"), (0.0, 0.0, 1.0)),))
            index.update_progress(2)
            index.finish("completed")
            # 即使调用方已经 finish，也必须等外层事务成功结束后才发布。
            raise interruption("interrupt fixture")
    index.close()
    reopened = SQLiteSemanticIndex(path)
    try:
        assert stored_rows(reopened) == before
        after = reopened.state()
        assert after is not None
        assert replace(after, updated_at=state.updated_at, last_error=state.last_error) == state
        assert after.last_error == f"{interruption.__name__}: interrupt fixture"
        assert reopened.supports_incremental()
        assert reopened.integrity_report(IDENTITY).status == "valid"
        # 失败重开后的下一次事务必须能重新建池并正常发布，不留下临时表污染。
        with reopened.incremental_transaction(
            IDENTITY, 2, base_revision=7, canonical_revision=8, forwarded_message_count=0,
        ):
            reopened.update_progress(2)
            reopened.finish("completed")
    finally:
        reopened.close()


def test_incremental_reuses_exact_input_and_preserves_unaffected_row(tmp_path: Path) -> None:
    """旧输入可跨 chunk 身份复用；同 ID 的新正文必须重新 embedding。"""

    index = SQLiteSemanticIndex(tmp_path / "index.sqlite3")
    try:
        first, _ = seed(index)
        unaffected = stored_rows(index)[1]
        renamed = replace(first, chunk_id="renamed", parent_id="new-parent")
        edited = replace(first, embedding_input="同边界但正文改变")
        with index.incremental_transaction(
            IDENTITY, 3, base_revision=7, canonical_revision=8, forwarded_message_count=0,
        ):
            # 重叠范围不会重复计数；两端均为 inclusive。
            assert index.prepare_incremental_ranges((("session", 1000, 1000), ("session", 0, 1000))) == 1
            assert index.reusable_vectors((renamed, edited)) == {"renamed": (1.0, 0.0, 0.0)}
            index.insert_chunks(((renamed, (1.0, 0.0, 0.0)),))
            index.insert_chunks(((edited, (0.0, 0.0, 1.0)),))
            index.update_progress(3)
            index.finish("completed")
        assert unaffected in stored_rows(index)
        assert index.state().canonical_revision == 8
        assert index.integrity_report(IDENTITY).status == "valid"
    finally:
        index.close()


def test_stale_builder_cannot_publish_a_plan_for_an_old_base(tmp_path: Path) -> None:
    """两个连接从相同基线规划，较晚获得锁的 builder 必须拒绝旧计划。"""

    path = tmp_path / "index.sqlite3"
    first = SQLiteSemanticIndex(path)
    seed(first)
    second = SQLiteSemanticIndex(path)
    try:
        with first.incremental_transaction(
            IDENTITY, 2, base_revision=7, canonical_revision=8, forwarded_message_count=0,
        ):
            first.update_progress(2)
            first.finish("completed")
        before = second.state()
        with pytest.raises(SemanticIndexStale, match="base identity or revision"):
            with second.incremental_transaction(
                IDENTITY, 2, base_revision=7, canonical_revision=8, forwarded_message_count=0,
            ):
                pytest.fail("a stale plan must never enter its write body")
        assert second.state() == before
    finally:
        first.close()
        second.close()


def test_incomplete_transaction_cannot_commit(tmp_path: Path) -> None:
    """缺少完成 coverage 的调用错误显式暴露，并回滚范围删除。"""

    index = SQLiteSemanticIndex(tmp_path / "index.sqlite3")
    try:
        seed(index)
        before = stored_rows(index)
        with pytest.raises(SemanticIndexStorageError, match="did not complete"):
            with index.incremental_transaction(
                IDENTITY, 2, base_revision=7, canonical_revision=8, forwarded_message_count=0,
            ):
                index.prepare_incremental_ranges((("session", None, None),))
        assert stored_rows(index) == before
        assert index.state().canonical_revision == 7
    finally:
        index.close()


@pytest.mark.parametrize("empty", [False, True])
def test_legacy_format_requires_one_explicit_rebuild(tmp_path: Path, empty: bool) -> None:
    """打开旧 schema 只补 nullable 列，新旧空索引也由格式标记明确区分。"""

    path = tmp_path / "index.sqlite3"
    index = SQLiteSemanticIndex(path)
    if empty:
        index.start_rebuild(IDENTITY, 0)
        index.finish("completed")
    else:
        seed(index)
    assert index.supports_incremental()
    with index._connection:
        # 直接还原旧物理 schema，确保 reopen 的真实迁移不会填充虚假输入。
        index._connection.execute("ALTER TABLE semantic_chunks DROP COLUMN embedding_input")
        index._connection.execute("ALTER TABLE semantic_index_state DROP COLUMN embedding_input_format")
    index.close()
    reopened = SQLiteSemanticIndex(path)
    try:
        assert not reopened.supports_incremental()
        if not empty:
            assert all(row[0] is None for row in reopened._connection.execute(
                "SELECT embedding_input FROM semantic_chunks"
            ))
        reopened.start_rebuild(IDENTITY, 0, canonical_revision=8)
        reopened.finish("completed")
        assert reopened.supports_incremental()
    finally:
        reopened.close()


@pytest.mark.parametrize("mutation", [
    "UPDATE semantic_index_state SET status = 'partial'",
    "UPDATE semantic_index_state SET status = 'failed'",
    "UPDATE semantic_index_state SET indexed_message_count = 1",
    "UPDATE semantic_index_state SET forwarded_message_count = 1",
    "UPDATE semantic_chunks SET embedding_input = NULL WHERE chunk_id = 'first'",
])
def test_incomplete_or_unverifiable_baseline_does_not_support_incremental(tmp_path: Path, mutation: str) -> None:
    """旧版覆盖不全、未完成状态或缺失凭据都只能显式续建/重建。"""

    index = SQLiteSemanticIndex(tmp_path / "index.sqlite3")
    try:
        seed(index)
        with index._connection:
            index._connection.execute(mutation)
        assert not index.supports_incremental()
    finally:
        index.close()
