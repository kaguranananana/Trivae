"""自动导入到正式索引构建器、Agent 工具与失败续建的隔离回归。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_forward_retrieval import make_forward_message
from tests.test_ingestion import make_message, write_export
from tests.test_semantic_resume import _ResumeProvider
from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.bootstrap.application import create_application
from trivae.bootstrap.import_indexes import LocalImportIndexUpdater
from trivae.bootstrap.ingestion import run_import_once
from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, SemanticSearchInput
from trivae.data.storage.sqlite_lexical import SQLiteLexicalIndex
from trivae.interfaces.cli import main
from trivae.retrieval.semantic.builder import SemanticIndexBuilder
from trivae.retrieval.semantic.index import SQLiteSemanticIndex


def write_fixture(raw: Path, name: str, *, forwarded: bool = False, count: int = 1) -> Path:
    """每条长正文相隔一小时，使默认 chunker 生成独立且真实可续建的块。"""

    raw.mkdir(exist_ok=True)
    messages = [
        make_message(f"m{index}", index + 1, 1_790_000_000_000 + index * 3_600_000, "budget " + "detail " * 30)
        for index in range(count)
    ]
    if forwarded:
        messages.append(
            make_forward_message(
                "outer",
                1_790_000_001_000,
                [make_message("inner", None, 100, "budget 合并转发内部的正式正文 " + "detail " * 30)],
            )
        )
    return write_export(raw, name, messages, chat_name="测试群", peer_uid="12345", version="5")


def run(database: Path, raw: Path, updater: LocalImportIndexUpdater):
    return run_import_once(database, raw, settle_seconds=0, min_age_seconds=0, index_updater=updater)


def test_real_updater_makes_new_native_and_forwarded_messages_available_to_agent(tmp_path: Path) -> None:
    """既有转发投影及工具生产入口必须随自动导入一起更新。"""

    database, raw = tmp_path / "store.sqlite3", tmp_path / "raw"
    write_fixture(raw, "chat.json", forwarded=True)
    provider = _DeterministicProvider()
    report = run(database, raw, LocalImportIndexUpdater(database, semantic_provider=provider))
    assert report.exit_code == 0
    assert report.pending_indexes == ()
    assert provider.document_batches
    # 自动入口没有创建 Application 的 Evaluation / Conversation 资源。
    assert {path.name for path in tmp_path.glob("*.sqlite3")} == {"store.sqlite3", "store.semantic.sqlite3"}
    with create_application(database, semantic_provider=provider) as application:
        scope = ExecutionScope(allowed_session_ids=("qq:12345",), max_results=10)
        lexical = application.invoke_tool("lexical_search", SearchMessagesInput(keyword="合并转发内部", limit=5), scope)
        assert lexical.status == "ok"
        assert lexical.data.hits[0].message.forward.root_message_id == "qq:12345:outer"
        semantic = application.invoke_tool("semantic_search", SemanticSearchInput(query="budget", limit=5), scope)
        assert semantic.status == "ok"
        assert semantic.data.hits
        assert application.semantic_index_status().status == "completed"


def test_no_change_or_duplicate_only_export_never_rebuilds_indexes(tmp_path: Path) -> None:
    database, raw = tmp_path / "store.sqlite3", tmp_path / "raw"
    write_fixture(raw, "a.json")
    updater = LocalImportIndexUpdater(database, semantic_provider=_DeterministicProvider())
    assert run(database, raw, updater).exit_code == 0
    with (
        patch.object(SQLiteLexicalIndex, "rebuild", side_effect=AssertionError("no new data")),
        patch.object(SemanticIndexBuilder, "rebuild", side_effect=AssertionError("no new data")),
    ):
        assert run(database, raw, updater).exit_code == 0
        write_fixture(raw, "duplicate.json")
        duplicated = run(database, raw, updater)
    assert duplicated.exit_code == 0
    assert duplicated.batches[0].inserted_count == 0
    assert duplicated.batches[0].duplicate_count == 1


@pytest.mark.parametrize("source_changes", [False, True])
def test_embedding_failure_is_persisted_and_recovered_using_snapshot_contract(
    tmp_path: Path, source_changes: bool
) -> None:
    """同快照续建复用已存向量；新快照重新构建，不能误确认旧索引。"""

    database, raw = tmp_path / "store.sqlite3", tmp_path / "raw"
    write_fixture(raw, "chat.json", count=4)
    failed_provider = _ResumeProvider(fail_batch=2)
    failed = run(database, raw, LocalImportIndexUpdater(database, semantic_provider=failed_provider))
    assert failed.exit_code == 1
    assert len(failed.pending_indexes) == 1
    assert failed.pending_indexes[0].index_kind == "semantic"
    assert "after committed batch" in failed.pending_indexes[0].last_error
    with closing(SQLiteSemanticIndex(database.with_name("store.semantic.sqlite3"))) as semantic:
        assert semantic.state().status == "failed"
        assert semantic.state().chunk_count == 2
    if source_changes:
        write_fixture(raw, "chat.json", count=5)
    provider = _ResumeProvider()
    updater = LocalImportIndexUpdater(database, semantic_provider=provider)
    original_rebuild = SemanticIndexBuilder.rebuild
    with patch.object(SemanticIndexBuilder, "rebuild", autospec=True, side_effect=original_rebuild) as rebuild:
        # 保留真实构建，记录它是否选择了既有的显式续建参数。
        recovered = run(database, raw, updater)
    assert recovered.exit_code == 0
    assert rebuild.call_args.kwargs["resume"] is (not source_changes)
    assert len(provider.documents) == (5 if source_changes else 2)
    # 模拟语义提交成功而队列确认前进程中断；恢复只确认已有同快照成果。
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE auto_import_index_work SET status = 'running' WHERE index_kind = 'semantic'")
    with patch.object(SemanticIndexBuilder, "rebuild", side_effect=AssertionError("already committed")):
        assert run(database, raw, updater).exit_code == 0


def test_cli_update_indexes_is_explicit_and_status_does_not_construct_updater(tmp_path: Path, capsys) -> None:
    database, raw = tmp_path / "store.sqlite3", tmp_path / "raw"
    write_fixture(raw, "chat.json")
    updater = LocalImportIndexUpdater(database, semantic_provider=_DeterministicProvider())
    with patch("trivae.interfaces.import_once_cli.create_import_index_updater", return_value=updater) as factory:
        assert main(["import-once", "--database", str(database), "--status", "--update-indexes"]) == 0
        factory.assert_not_called()
        assert not database.exists()
        capsys.readouterr()
        assert main([
            "import-once", "--database", str(database), "--raw-dir", str(raw),
            "--settle-seconds", "0", "--min-age-seconds", "0", "--update-indexes",
        ]) == 0
        factory.assert_called_once_with(database)
    report = json.loads(capsys.readouterr().out)
    assert report["indexes"]["updater"] == "connected"
    assert report["indexes"]["pending"] == []
