"""Canonical mutation 位置、范围读取与导入义务的回归验证。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_auto_import import RecordingUpdater, export, run
from tests.test_forward_retrieval import forward_children, make_forward_message
from tests.test_ingestion import make_message, write_export
from trivae.data.ingestion.auto_import_contracts import FileVersion
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_auto_import import SQLiteAutoImportState
from trivae.data.storage.sqlite_forward import ensure_canonical_revision
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.structured import RetrievalError, ScopeFilters

BASE = 1_790_000_000_000


@pytest.fixture
def canonical(tmp_path: Path) -> Iterator[tuple[SQLiteCanonicalStore, SQLiteCanonicalReadRepository]]:
    """使用真实导入器建立可修改的临时 canonical，不改生产库。"""

    raw = tmp_path / "raw"
    raw.mkdir()
    source = write_export(
        raw, "chat.json",
        [make_message(f"m{index}", index, BASE + offset * 1000, f"正文 {index}")
         for index, offset in enumerate((0, 5, 10, 15, 100, 105))],
        chat_name="测试群", peer_uid="100", version="5",
    )
    with SQLiteCanonicalStore(tmp_path / "canonical.sqlite3") as store:
        SharedImporter(store).import_paths((source,))
        reader = SQLiteCanonicalReadRepository(store.database_path)
        try:
            yield store, reader
        finally:
            reader.close()


def test_body_and_timestamp_changes_keep_both_old_and_new_segments(canonical) -> None:
    store, reader = canonical
    before = reader.canonical_revision()
    with store.connection:
        store.connection.execute(
            "UPDATE messages SET timestamp = ?, content_text = '新正文' WHERE source_message_id = 'm1'",
            (BASE + 103000,),
        )
    assert reader.semantic_change_ranges(before, 5) == (
        ("qq:100", BASE, BASE + 15000), ("qq:100", BASE + 100000, BASE + 105000),
    )
    row = store.connection.execute("SELECT * FROM canonical_message_changes WHERE revision > ?", (before,)).fetchone()
    assert (row["old_timestamp"], row["new_timestamp"]) == (BASE + 5000, BASE + 103000)
    assert set(row.keys()) == {"revision", "old_session_id", "old_timestamp", "new_session_id", "new_timestamp"}


def test_deleted_bridges_remain_connected_and_deleted_tail_is_retained(canonical) -> None:
    store, reader = canonical
    before = reader.canonical_revision()
    with store.connection:
        store.connection.execute(
            "DELETE FROM message_sources WHERE internal_message_id IN "
            "(SELECT internal_message_id FROM messages WHERE source_message_id IN ('m1', 'm2', 'm3'))"
        )
        store.connection.execute("DELETE FROM messages WHERE source_message_id IN ('m1', 'm2', 'm3')")
    assert reader.semantic_change_ranges(before, 5) == (("qq:100", BASE, BASE + 15000),)
    assert [message.source_message_id for message in reader.iter_semantic_messages(
        1, scope=ScopeFilters(session_ids=("qq:100",), start_timestamp=BASE, end_timestamp=BASE + 16000)
    )] == ["m0"]


def test_session_move_records_old_and_new_session_locations(canonical) -> None:
    store, reader = canonical
    with store.connection:
        store.connection.execute(
            "INSERT INTO chat_sessions(session_id, platform, external_chat_id, name, chat_type) "
            "VALUES ('qq:200', 'qq', '200', '另一群', 'group')"
        )
    before = reader.canonical_revision()
    with store.connection:
        store.connection.execute("UPDATE messages SET session_id = 'qq:200' WHERE source_message_id = 'm0'")
    assert reader.semantic_change_ranges(before, 5) == (
        ("qq:100", BASE, BASE + 15000), ("qq:200", BASE, BASE),
    )


def test_name_changes_dirty_whole_session_but_noop_updates_do_not(canonical) -> None:
    store, reader = canonical
    before = reader.canonical_revision()
    with store.connection:
        store.connection.execute("UPDATE messages SET content_text = content_text")
        store.connection.execute("UPDATE chat_sessions SET name = name, last_message_timestamp = last_message_timestamp")
    assert reader.canonical_revision() == before
    assert reader.semantic_change_ranges(before, 5) == ()
    with store.connection:
        store.connection.execute("UPDATE chat_sessions SET name = '新群名'")
    assert reader.canonical_revision() == before + 1
    assert reader.semantic_change_ranges(before, 5) == (("qq:100", None, None),)


def test_failed_transaction_does_not_commit_revision_or_locations(canonical) -> None:
    store, reader = canonical
    before = reader.canonical_revision()
    with pytest.raises(RuntimeError, match="写入中断"):
        with store.connection:
            store.connection.execute("UPDATE messages SET content_text = '未提交'")
            raise RuntimeError("写入中断")
    assert reader.canonical_revision() == before
    assert reader.semantic_change_ranges(before, 5) == ()


def test_missing_history_and_pre_migration_revision_are_explicit(canonical) -> None:
    store, reader = canonical
    before = reader.canonical_revision()
    with store.connection:
        store.connection.execute("UPDATE messages SET content_text = '变更' WHERE source_message_id = 'm0'")
        store.connection.execute("DELETE FROM canonical_message_changes WHERE revision > ?", (before,))
    with pytest.raises(RetrievalError, match="does not cover"):
        reader.semantic_change_ranges(before, 5)
    # 模拟首次迁移旧库：当前水位以前没有位置历史，不能增量猜测。
    with store.connection:
        store.connection.execute("DELETE FROM trivae_derived_meta WHERE key = 'semantic_changes_baseline_revision'")
        ensure_canonical_revision(store.connection)
    with pytest.raises(RetrievalError, match="does not cover"):
        reader.semantic_change_ranges(before, 5)
    assert reader.semantic_change_ranges(reader.canonical_revision(), 5) == ()


def test_scoped_forward_stream_uses_outer_half_open_timestamps(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source = write_export(
        raw, "forward.json",
        [make_forward_message("outer-a", 10_000, forward_children()),
         make_forward_message("outer-b", 20_000, forward_children())],
        chat_name="测试群", peer_uid="100", version="5",
    )
    with SQLiteCanonicalStore(tmp_path / "canonical.sqlite3") as store:
        SharedImporter(store).import_paths((source,))
        reader = SQLiteCanonicalReadRepository(store.database_path)
        try:
            scope = ScopeFilters(session_ids=("qq:100",), start_timestamp=10_000, end_timestamp=20_000)
            roots = tuple(reader.iter_semantic_messages(1, scope=scope))
            children = tuple(reader.iter_forwarded_messages(1, scope=scope))
            assert [message.source_message_id for message in roots] == ["outer-a"]
            assert children
            assert {message.forward.root_message_id for message in children} == {"qq:100:outer-a"}
            before = reader.canonical_revision()
            with store.connection:
                store.connection.execute(
                    "UPDATE messages SET content_json = replace(content_json, '远程连接', '修改连接') "
                    "WHERE source_message_id = 'outer-a'"
                )
            assert reader.semantic_change_ranges(before, 5) == (("qq:100", 10_000, 10_000),)
        finally:
            reader.close()


def test_zero_insert_name_change_enqueues_both_indexes(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source = export(raw)
    database = tmp_path / "canonical.sqlite3"
    updater = RecordingUpdater()
    assert run(database, raw, updater).exit_code == 0
    updater.calls.clear()
    source.write_text(source.read_text().replace("测试群", "新群名"))
    report = run(database, raw, updater)
    assert report.batches[0].inserted_count == 0
    assert [kind for kind, _ in updater.calls] == ["lexical", "semantic"]
    updater.calls.clear()
    # 相同群名的幂等重放不再推进 revision，也不制造索引义务。
    export(raw, "duplicate.json").write_text(source.read_text())
    assert run(database, raw, updater).exit_code == 0
    assert updater.calls == []


def test_zero_insert_name_change_recovers_after_canonical_commit(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source = export(raw)
    database = tmp_path / "canonical.sqlite3"
    assert run(database, raw, RecordingUpdater()).exit_code == 0
    source.write_text(source.read_text().replace("测试群", "新群名"))
    with SQLiteCanonicalStore(database) as store:
        state = SQLiteAutoImportState(store.connection)
        version = FileVersion.read(source)
        state.prepare(source, version)
        batch = SharedImporter(store).import_paths((source,)).batches[0]
        assert batch.inserted_count == 0
        # 模拟 finish_file 前退出；重开连接后依靠 prepare 水位与 durable batch 恢复。
    with SQLiteCanonicalStore(database) as store:
        state = SQLiteAutoImportState(store.connection)
        with patch.object(SharedImporter, "import_paths", side_effect=AssertionError("不得重新解析")):
            assert state.recover()[0][2].batch_id == batch.batch_id
        assert {work.index_kind for work in state.pending_indexes()} == {"lexical", "semantic"}
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM chat_sessions").fetchone()[0] == "新群名"
