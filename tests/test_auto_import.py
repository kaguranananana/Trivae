"""自动导入的隔离 SQLite、真实进程中断及 CLI 回归。"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_ingestion import make_message, write_export
from tests.test_semantic_retrieval import _DeterministicProvider
from trivae.bootstrap.application import create_application
from trivae.bootstrap.ingestion import import_lock, read_import_status, run_import_once
from trivae.capabilities.contracts import (
    ExecutionScope,
    GetRecentMessagesInput,
    SearchMessagesInput,
    SemanticSearchInput,
)
from trivae.data.ingestion.auto_import import IncrementalImporter
from trivae.data.ingestion.auto_import_contracts import IndexKind, IndexWork
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.ingestion.qq_export import QQExportParser
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.interfaces.cli import main


@dataclass
class RecordingUpdater:
    """只验证索引交接与重放，不把测试替身当成真实检索验收。"""

    fail_kind: str | None = None
    calls: list[tuple[IndexKind, tuple[IndexWork, ...]]] = field(default_factory=list)

    def update(self, index_kind: IndexKind, work: tuple[IndexWork, ...]) -> None:
        self.calls.append((index_kind, work))
        if index_kind == self.fail_kind:
            raise RuntimeError("index fixture failure")


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    directory = tmp_path / "raw"
    directory.mkdir()
    return directory


def export(raw: Path, name: str = "chat.json", *, ids: tuple[str, ...] = ("m1",)) -> Path:
    """沿用既有 QQ fixture，全部写入 pytest 临时目录。"""

    return write_export(
        raw,
        name,
        [
            make_message(identity, index + 1, 1_790_000_000_000 + index, f"消息 {identity}")
            for index, identity in enumerate(ids)
        ],
        chat_name="测试群",
        peer_uid="12345",
        version="5",
    )


def run(database: Path, raw: Path, updater: RecordingUpdater | None = None):
    return run_import_once(database, raw, settle_seconds=0, min_age_seconds=0, index_updater=updater)


def scalar(database: Path, sql: str) -> int:
    with sqlite3.connect(database) as connection:
        return int(connection.execute(sql).fetchone()[0])


def test_empty_directory_records_success_without_index_work(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    updater = RecordingUpdater()
    report = run(database, raw, updater)
    assert report.exit_code == 0
    assert report.files == ()
    assert updater.calls == []
    assert read_import_status(database)["last_run"]["status"] == "completed"
    # 轻量入口不初始化 Query/Evaluation 等其他数据库。
    assert sorted(path.name for path in tmp_path.glob("*.sqlite3")) == ["store.sqlite3"]


def test_new_file_and_restart_skip_parsing_unchanged_file(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw)
    report = run(database, raw)
    assert report.exit_code == 2
    assert report.batches[0].inserted_count == 1
    assert {item.index_kind for item in report.pending_indexes} == {"lexical", "semantic"}
    with patch.object(QQExportParser, "parse", side_effect=AssertionError("must not parse unchanged file")):
        repeated = run(database, raw)
    assert repeated.files[0].status == "unchanged"
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 1
    assert repeated.to_dict()["indexes"]["retrieval_readiness"] == "pending"


def test_duplicate_export_preserves_provenance_without_new_index_work(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw, "a.json")
    updater = RecordingUpdater()
    run(database, raw, updater)
    updater.calls.clear()
    export(raw, "b.json")
    report = run(database, raw, updater)
    assert report.exit_code == 0
    assert report.batches[0].inserted_count == 0
    assert report.batches[0].duplicate_count == 1
    assert updater.calls == []
    assert scalar(database, "SELECT COUNT(*) FROM message_sources") == 2


def test_changed_export_imports_new_records_once(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    updater = RecordingUpdater()
    export(raw)
    run(database, raw, updater)
    export(raw, ids=("m1", "m2"))
    report = run(database, raw, updater)
    assert report.batches[0].inserted_count == 1
    assert report.batches[0].duplicate_count == 1
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 2
    assert scalar(database, "SELECT COUNT(*) FROM message_sources") == 2
    assert len(updater.calls) == 4


def test_same_size_rewrite_with_preserved_mtime_records_conflict(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    updater = RecordingUpdater()
    run(database, raw, updater)
    before = source.stat()
    # 模拟保留 mtime 的同长覆盖；ctime 变化仍必须使文件重新进入导入器。
    source.write_text(source.read_text().replace("消息", "变化"))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert source.stat().st_size == before.st_size
    report = run(database, raw, updater)
    assert report.batches[0].inserted_count == 0
    assert report.batches[0].conflict_count == 1
    # 既有 Store 将同一 canonical occurrence 的冲突记在 batch，避免改变原 provenance 契约。
    assert scalar(database, "SELECT SUM(conflict_count) FROM import_batches") == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT content_text FROM messages").fetchone()[0] == "消息 m1"
    assert len(updater.calls) == 2


def test_conflict_from_new_export_preserves_variant_and_canonical(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw, "a.json")
    run(database, raw)
    source = export(raw, "b.json")
    source.write_text(source.read_text().replace("消息", "变化"))
    report = run(database, raw)
    assert report.batches[0].conflict_count == 1
    assert report.batches[0].inserted_count == 0
    assert scalar(database, "SELECT COUNT(*) FROM message_variants WHERE variant_kind = 'conflict'") == 1
    assert scalar(database, "SELECT COUNT(*) FROM message_sources") == 2
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT content_text FROM messages").fetchone()[0] == "消息 m1"


def test_recent_file_is_deferred_then_compensated(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw)
    with SQLiteCanonicalStore(database) as store:
        runner = IncrementalImporter(SharedImporter(store), now_ns=lambda: time.time_ns())
        with patch.object(QQExportParser, "parse", side_effect=AssertionError("writing input must not open")):
            report = runner.run(raw, settle_seconds=0, min_age_seconds=60)
        assert report.exit_code == 75
        assert report.files[0].status == "deferred"
        runner.now_ns = lambda: time.time_ns() + 61_000_000_000
        recovered = runner.run(raw, settle_seconds=0, min_age_seconds=60)
    assert recovered.batches[0].inserted_count == 1


def test_change_between_samples_is_skipped_and_later_imported(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    with SQLiteCanonicalStore(database) as store:

        def change(_: float) -> None:
            source.write_text('{"metadata":')

        runner = IncrementalImporter(SharedImporter(store), sleep=change)
        report = runner.run(raw, settle_seconds=1, min_age_seconds=0)
    assert report.exit_code == 75
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 0
    export(raw)
    assert run(database, raw).batches[0].inserted_count == 1


def test_change_while_copying_snapshot_is_deferred(tmp_path: Path, raw: Path) -> None:
    import shutil

    database = tmp_path / "store.sqlite3"
    source = export(raw)
    original_copy = shutil.copyfileobj

    def copy_and_change(input_stream, output_stream) -> None:
        original_copy(input_stream, output_stream)
        source.write_text('{"metadata":')

    with patch("trivae.data.ingestion.auto_import.shutil.copyfileobj", side_effect=copy_and_change):
        report = run(database, raw)
    assert report.exit_code == 75
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 0


def test_source_can_change_after_snapshot_without_losing_next_version(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    original_parse = QQExportParser.parse

    def parse_and_replace(self, path):
        parsed = original_parse(self, path)
        # Parser 读的是不可变快照；QCE 后续版本留到下一轮。
        assert path != source
        export(raw, ids=("m1", "m2"))
        return parsed

    with patch.object(QQExportParser, "parse", parse_and_replace):
        first = run(database, raw)
    assert first.batches[0].received_count == 1
    second = run(database, raw)
    assert second.batches[0].inserted_count == 1
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 2


def test_invalid_json_retries_and_other_files_continue(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    invalid = raw / "a.json"
    invalid.write_text('{"metadata":')
    export(raw, "b.json")
    first = run(database, raw)
    assert first.exit_code == 1
    assert [batch.status for batch in first.batches] == ["failed", "completed"]
    second = run(database, raw)
    assert second.batches[0].status == "failed"
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 1
    export(raw, "a.json", ids=("m2",))
    assert run(database, raw).batches[0].inserted_count == 1
    assert read_import_status(database)["unfinished_files"] == []


def test_partial_import_keeps_retryable_status_and_record_errors(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw, ids=("m1", "m2"))
    payload = json.loads(source.read_text())
    payload["messages"][1]["timestamp"] = "invalid"
    source.write_text(json.dumps(payload))
    first = run(database, raw)
    assert first.exit_code == 1
    assert first.batches[0].status == "partial"
    second = run(database, raw)
    assert second.batches[0].duplicate_count == 1
    assert len(second.pending_indexes) == 2
    assert scalar(database, "SELECT COUNT(*) FROM import_errors") == 2
    export(raw, ids=("m1", "m2"))
    final = run(database, raw)
    assert final.batches[0].status == "completed"
    assert final.batches[0].inserted_count == 1
    assert scalar(database, "SELECT COUNT(*) FROM message_sources") == 2


def test_unknown_import_error_rolls_back_file_and_continues(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw, "a.json", ids=("m1", "broken"))
    export(raw, "b.json", ids=("m3",))
    original_write = SQLiteCanonicalStore.write_message

    def fail_second(self, message):
        if message.source_message_id == "broken":
            raise RuntimeError("fixture write failure")
        return original_write(self, message)

    with patch.object(SQLiteCanonicalStore, "write_message", fail_second):
        first = run(database, raw)
    assert first.exit_code == 1
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 1
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 1
    assert first.files[0].status == "failed"
    assert "fixture write failure" in first.files[0].reason
    assert run(database, raw).batches[0].inserted_count == 2


def _crash_process(database: Path, raw: Path, *, after_commit: bool) -> subprocess.CompletedProcess:
    """真实子进程退出，验证 SQLite durable state 而不只模拟内存异常。"""

    injection = (
        "runner.state.finish_file = lambda *a, **k: os._exit(92)"
        if after_commit
        else "store.commit = lambda: os._exit(91)"
    )
    script = (
        """
import os
import sys
from pathlib import Path
from trivae.data.storage.sqlite import SQLiteCanonicalStore
from trivae.data.ingestion.importer import SharedImporter
from trivae.data.ingestion.auto_import import IncrementalImporter
store = SQLiteCanonicalStore(Path(sys.argv[1]))
runner = IncrementalImporter(SharedImporter(store))
"""
        + injection
        + """
runner.run(Path(sys.argv[2]), settle_seconds=0, min_age_seconds=0)
"""
    )
    return subprocess.run([sys.executable, "-c", script, str(database), str(raw)], capture_output=True, timeout=30)


@pytest.mark.parametrize("after_commit", [False, True])
def test_process_exit_before_or_after_commit_recovers_without_loss(
    tmp_path: Path, raw: Path, after_commit: bool
) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw)
    process = _crash_process(database, raw, after_commit=after_commit)
    assert process.returncode == (92 if after_commit else 91), process.stderr.decode()
    assert scalar(database, "SELECT COUNT(*) FROM messages") == int(after_commit)
    if after_commit:
        with patch.object(
            QQExportParser, "parse", side_effect=AssertionError("committed batch must recover without parsing")
        ):
            report = run(database, raw)
        assert report.files[0].status == "recovered"
    else:
        report = run(database, raw)
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 1
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 1
    assert scalar(database, "SELECT COUNT(*) FROM auto_import_runs WHERE status = 'interrupted'") == 1
    assert len(report.pending_indexes) == 2


def test_index_failure_persists_and_retries_without_reimport(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw)
    updater = RecordingUpdater(fail_kind="semantic")
    first = run(database, raw, updater)
    assert first.exit_code == 1
    assert len(first.pending_indexes) == 1
    assert first.pending_indexes[0].status == "failed"
    assert "fixture failure" in first.pending_indexes[0].last_error
    updater.fail_kind = None
    updater.calls.clear()
    with patch.object(QQExportParser, "parse", side_effect=AssertionError("only retry index")):
        recovered = run(database, raw, updater)
    assert recovered.exit_code == 0
    assert [kind for kind, _ in updater.calls] == ["semantic"]
    assert updater.calls[0][1][0].attempts == 1
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 1


def test_index_commit_confirmation_interruption_replays_work(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw)
    updater = RecordingUpdater()
    with SQLiteCanonicalStore(database) as store:
        runner = IncrementalImporter(SharedImporter(store), index_updater=updater)
        original_mark = runner.state.mark_indexes

        def interrupted_mark(work, status, error=None):
            if status == "completed":
                raise KeyboardInterrupt("after index commit")
            return original_mark(work, status, error)

        with patch.object(runner.state, "mark_indexes", interrupted_mark):
            with pytest.raises(KeyboardInterrupt):
                runner.run(raw, settle_seconds=0, min_age_seconds=0)
    assert len(updater.calls) == 1
    first_batch = updater.calls[0][1][0].batch_id
    assert run(database, raw, updater).exit_code == 0
    assert updater.calls[1][1][0].batch_id == first_batch
    assert scalar(database, "SELECT COUNT(*) FROM import_batches") == 1


def test_first_run_adopts_proven_history_and_imports_unknown_history(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    known = export(raw, "known.json")
    with SQLiteCanonicalStore(database) as store:
        SharedImporter(store).import_paths((known,))
        # 历史 fixture 的导入时间明确晚于文件，避免毫秒精度舍入的不确定性。
        store.connection.execute("UPDATE import_batches SET started_at = '2099-01-01T00:00:00+00:00'")
        store.connection.commit()
    export(raw, "unknown.json", ids=("m2",))
    original_parse = QQExportParser.parse
    original_normalize = QQExportParser.iter_normalized_messages
    parsed_names: list[str] = []
    normalized_names: list[str] = []

    def record_parse(self, path):
        parsed_names.append(path.name)
        return original_parse(self, path)

    def record_normalize(self, parsed, record_index_offset=0):
        normalized_names.append(parsed.source.file_name)
        return original_normalize(self, parsed, record_index_offset)

    with (
        patch.object(QQExportParser, "parse", record_parse),
        patch.object(QQExportParser, "iter_normalized_messages", record_normalize),
    ):
        report = run(database, raw)
    # 首次历史接管必须核验 JSON/provenance；已证明历史不再逐条规范化或重写。
    assert parsed_names == ["known.json", "unknown.json"]
    assert normalized_names == ["unknown.json"]
    assert [item.status for item in report.files] == ["adopted", "completed"]
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 2
    assert len(report.pending_indexes) == 2


@pytest.mark.parametrize("current_ids", [("m1", "m2"), ("m2",)])
def test_history_changed_after_parse_before_batch_start_is_not_skipped(
    tmp_path: Path, raw: Path, current_ids: tuple[str, ...]
) -> None:
    """回归复核复现：文件时间早于 batch.started_at 仍可能包含未导入记录。"""

    database = tmp_path / "store.sqlite3"
    source = export(raw)
    original_parse = QQExportParser.parse

    def parse_then_qce_overwrites(self, path):
        parsed = original_parse(self, path)
        export(raw, ids=current_ids)
        # 确保覆盖发生在批次时间之前，复现旧时间判定能够接管的竞争窗口。
        time.sleep(0.01)
        return parsed

    with SQLiteCanonicalStore(database) as store:
        with patch.object(QQExportParser, "parse", parse_then_qce_overwrites):
            SharedImporter(store).import_paths((source,))
    with patch.object(QQExportParser, "parse", autospec=True, side_effect=original_parse) as parse:
        report = run(database, raw)
    assert parse.call_count == 1
    assert report.files[0].status == "completed"
    assert report.batches[0].inserted_count == 1
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 2
    assert len(report.pending_indexes) == 2


def test_history_candidate_invalid_json_uses_original_failed_batch_once(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    with SQLiteCanonicalStore(database) as store:
        SharedImporter(store).import_paths((source,))
        store.connection.execute("UPDATE import_batches SET started_at = '2099-01-01T00:00:00+00:00'")
        store.connection.commit()
    source.write_text('{"metadata":')
    original_parse = QQExportParser.parse
    with patch.object(QQExportParser, "parse", autospec=True, side_effect=original_parse) as parse:
        report = run(database, raw)
    assert parse.call_count == 1
    assert report.exit_code == 1
    assert report.batches[0].status == "failed"
    assert scalar(database, "SELECT COUNT(*) FROM import_errors") == 1


def test_history_candidate_source_identity_change_cannot_be_hidden(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    with SQLiteCanonicalStore(database) as store:
        SharedImporter(store).import_paths((source,))
        store.connection.execute("UPDATE import_batches SET started_at = '2099-01-01T00:00:00+00:00'")
        store.connection.commit()
    payload = json.loads(source.read_text())
    payload["chatInfo"]["peerUid"] = "99999"
    source.write_text(json.dumps(payload))
    report = run(database, raw)
    assert report.exit_code == 1
    assert "Source file identity changed" in report.files[0].reason
    assert scalar(database, "SELECT COUNT(*) FROM chat_sessions") == 1


def test_history_modified_after_import_cannot_be_adopted(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    source = export(raw)
    with SQLiteCanonicalStore(database) as store:
        SharedImporter(store).import_paths((source,))
    before = source.stat()
    export(raw, ids=("m1", "m2"))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    report = run(database, raw)
    assert report.files[0].status == "completed"
    assert report.batches[0].inserted_count == 1


def test_calendar_backlog_scans_all_files_regardless_of_message_date(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    export(raw, "old-export-20200101.json")
    run(database, raw)
    export(raw, "missed-yesterday.json", ids=("m2",))
    export(raw, "late-export.json", ids=("m3",))
    report = run(database, raw)
    assert sum(batch.inserted_count for batch in report.batches) == 2
    assert scalar(database, "SELECT COUNT(*) FROM messages") == 3


def test_status_is_read_only_and_cli_returns_pending_index_status(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert main(["import-once", "--database", str(database), "--status"]) == 0
    assert json.loads(output.getvalue())["status"] == "not_initialized"
    assert not database.exists()
    export(raw)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main(
            [
                "import-once",
                "--database",
                str(database),
                "--raw-dir",
                str(raw),
                "--settle-seconds",
                "0",
                "--min-age-seconds",
                "0",
            ]
        )
    assert code == 2
    assert json.loads(output.getvalue())["indexes"]["updater"] == "integration_required"
    assert read_import_status(database)["last_run"]["status"] == "index_pending"


def test_lock_blocks_other_process_and_releases_after_process_death(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    with import_lock(database):
        process = subprocess.run(
            [sys.executable, "-m", "trivae", "import-once", "--database", str(database), "--raw-dir", str(raw)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process.returncode == 75
        assert json.loads(process.stdout)["error_code"] == "IMPORT_ALREADY_RUNNING"
        assert not database.exists()
    script = """
import sys
import time
from pathlib import Path
from trivae.bootstrap.ingestion import import_lock
with import_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    time.sleep(30)
"""
    holder = subprocess.Popen([sys.executable, "-c", script, str(database)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
    finally:
        holder.kill()
        holder.wait(timeout=10)
        holder.stdout.close()
    assert run(database, raw).exit_code == 0


def test_invalid_timing_arguments_fail_before_database_creation(tmp_path: Path, raw: Path) -> None:
    database = tmp_path / "store.sqlite3"
    with pytest.raises(ValueError, match="finite and non-negative"):
        run_import_once(database, raw, settle_seconds=-1)
    assert not database.exists()


def test_cli_to_canonical_and_agent_tools_exposes_pending_indexes(tmp_path: Path, raw: Path) -> None:
    """真实 CLI 到 Agent 工具；旧索引必须显式 stale，不能伪装新消息可搜索。"""

    database = tmp_path / "store.sqlite3"
    # 语义 chunker 会过滤过短文本；先建立确实有向量的基线，才能验证 count 漂移。
    write_export(
        raw,
        "baseline.json",
        [make_message("m1", 1, 1_790_000_000_000, "budget baseline " + "detail " * 30)],
        chat_name="测试群",
        peer_uid="12345",
        version="5",
    )
    with create_application(database, semantic_provider=_DeterministicProvider()) as application:
        application.import_directory(raw)
        application.rebuild_lexical_index()
        application.rebuild_semantic_index()
        assert application.semantic_index_status().chunk_count > 0
    export(raw, "delayed-export.json", ids=("m2",))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "trivae",
            "import-once",
            "--database",
            str(database),
            "--raw-dir",
            str(raw),
            "--settle-seconds",
            "0",
            "--min-age-seconds",
            "0",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 2, process.stderr
    report = json.loads(process.stdout)
    assert report["import"]["totals"]["inserted_count"] == 1
    assert len(report["indexes"]["pending"]) == 2
    with create_application(database, semantic_provider=_DeterministicProvider()) as application:
        scope = ExecutionScope(allowed_session_ids=("qq:12345",), max_results=10)
        recent = application.invoke_tool("get_recent_messages", GetRecentMessagesInput(limit=10), scope)
        assert recent.status == "ok"
        assert {message.source_message_id for message in recent.data.messages} == {"m1", "m2"}
        lexical = application.invoke_tool("lexical_search", SearchMessagesInput(keyword="m2", limit=5), scope)
        assert lexical.status == "error"
        # Tool 层把 LexicalIndexError 明确投影为既有 CAPABILITY_UNAVAILABLE。
        assert lexical.error.code == "CAPABILITY_UNAVAILABLE"
        assert "stale" in lexical.error.message
        semantic = application.invoke_tool("semantic_search", SemanticSearchInput(query="m2", limit=5), scope)
        assert semantic.status == "error"
        assert semantic.error.code == "SEMANTIC_INDEX_STALE"
        assert application.semantic_index_status().status == "stale"
    # 验证无人值守命令没有暗中重建旧索引。
    assert scalar(database, "SELECT COUNT(*) FROM messages_fts") == 1
