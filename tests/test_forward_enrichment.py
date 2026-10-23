"""真实重复导入回归：后一次导出的转发正文必须补齐，并继续同步正式索引。"""

from __future__ import annotations

import copy
import json
from contextlib import closing

import pytest

from tests.test_forward_retrieval import make_forward_message
from tests.test_ingestion import make_message, write_export
from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.bootstrap.application import create_application
from trivae.bootstrap.import_indexes import LocalImportIndexUpdater
from trivae.bootstrap.ingestion import run_import_once
from trivae.capabilities import ExecutionScope, SemanticSearchInput
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.structured import LexicalQuery, ScopeFilters


def versions(nested: bool):
    """两个版本只有真实内部正文不同；根消息身份、时间和预览保持一致。"""
    empty = make_forward_message("outer", 10_000, [])
    full = make_forward_message("outer", 10_000, [
        make_message("inner", None, 100, "远程连接的真实补齐正文 " * 8),
    ])
    if nested:
        empty = make_forward_message("root", 20_000, [empty])
        full = make_forward_message("root", 20_000, [full])
    return empty, full


@pytest.mark.parametrize("nested", [False, True])
def test_later_forward_body_is_preserved_and_reimport_is_idempotent(tmp_path, nested):
    """根层和嵌套空节点均须补齐；再次导入相同正文不能再推进 Canonical revision。"""
    empty, full = versions(nested)
    sources = [write_export(tmp_path, f"input-{i}(100).json", [message],
                            chat_name="测试群", peer_uid="100", version="0.1.0")
               for i, message in enumerate((empty, full))]
    database = tmp_path / "messages.sqlite3"
    with SQLiteCanonicalStore(database) as store, closing(SQLiteCanonicalReadRepository(database)) as reader:
        importer = SharedImporter(store)
        importer.import_paths([sources[0]])
        before = reader.canonical_revision()
        summary = importer.import_paths([sources[1]]).batches[0]
        with closing(SQLiteLexicalIndex(database)) as index:
            index.rebuild()
        assert reader.count_lexical_hits(LexicalQuery(keyword="远程连接", limit=50)) == 1
        assert reader.forward_content_gaps(ScopeFilters()) == ()
        assert reader.canonical_revision() > before
        assert summary.enriched_count == 1
        published = reader.canonical_revision()
        assert importer.import_paths([sources[1]]).batches[0].enriched_count == 0
        assert reader.canonical_revision() == published
        # 老的空导出再出现也不能抹掉已知正文。
        importer.import_paths([sources[0]])
        assert reader.canonical_revision() == published
        assert reader.count_lexical_hits(LexicalQuery(keyword="远程连接", limit=50)) == 1


def test_changed_known_forward_body_is_a_recorded_conflict(tmp_path):
    """同一已知子消息改写正文属于冲突，保留原文和 incoming raw，不能算完全相同。"""
    _, original = versions(False)
    changed = copy.deepcopy(original)
    changed["content"]["elements"][0]["data"]["messages"][0]["content"]["text"] = "另一个冲突正文"
    database = tmp_path / "messages.sqlite3"
    with SQLiteCanonicalStore(database) as store:
        importer = SharedImporter(store)
        for i, message in enumerate((original, changed)):
            source = write_export(tmp_path, f"input-{i}(100).json", [message],
                                  chat_name="测试群", peer_uid="100", version="0.1.0")
            summary = importer.import_paths([source]).batches[0]
        assert summary.conflict_count == 1
        row = store.connection.execute("SELECT variant_kind, raw_payload_json FROM message_variants").fetchone()
        assert row["variant_kind"] == "conflict"
        assert json.loads(row["raw_payload_json"])["content"] == changed["content"]


def test_auto_import_publishes_forward_enrichment_to_both_indexes(tmp_path):
    """同文件二次导出补齐后，原索引队列必须按 revision 发布 FTS 与语义增量。"""
    database, raw = tmp_path / "messages.sqlite3", tmp_path / "raw"
    raw.mkdir()
    provider = _DeterministicProvider()
    updater = LocalImportIndexUpdater(database, semantic_provider=provider)
    for message in versions(True):
        write_export(raw, "input(100).json", [message], chat_name="测试群", peer_uid="100", version="0.1.0")
        report = run_import_once(database, raw, settle_seconds=0, min_age_seconds=0, index_updater=updater)
        assert report.exit_code == 0
    with closing(SQLiteCanonicalReadRepository(database)) as reader:
        assert reader.count_lexical_hits(LexicalQuery(keyword="远程连接", limit=50)) == 1
    assert report.pending_indexes == ()
    assert report.batches[0].enriched_count == 1
    with create_application(database, semantic_provider=provider) as application:
        assert application.semantic_index_status().status == "completed"
        result = application.invoke_tool("semantic_search", SemanticSearchInput(query="远程连接", limit=1),
                                         ExecutionScope(max_results=20))
        assert result.status != "error"
        assert any("远程连接" in message.normalized_content for message in result.data.expanded_messages)
