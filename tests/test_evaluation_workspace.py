"""Managed evaluation workspace lifecycle and cleanup contracts."""
from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from tests.test_evaluation import _case, _FailedExecutor, _trace, _variant
from tests.test_evaluation_platform import _make_data
from trivae.config.settings import ModelSettings
from trivae.evaluation.contracts import CaseReference, DatasetSnapshot, EvaluationContractError, EvaluationSuite
from trivae.evaluation.frozen_data import freeze_data
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore
from trivae.evaluation.workspace import (
    WORKSPACE_ROOT_NAME,
    EvaluationWorkspace,
    cleanup_stale_workspaces,
)


def _master(tmp_path: Path) -> Path:
    canonical, semantic = _make_data(tmp_path)
    freeze_data(canonical, semantic, tmp_path / "master")
    return tmp_path / "master" / "freeze.json"


def test_workspace_success_persists_then_removes_only_its_clones(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    canonical_before = (manifest.parent / "trivae.sqlite3").read_bytes()
    with EvaluationWorkspace.create(manifest) as workspace:
        database = workspace.database_path
        assert database.is_file()
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE messages SET text='isolated'")
            connection.commit()
        workspace.mark_results_persisted()

    assert not workspace.directory.exists()
    assert (manifest.parent / "trivae.sqlite3").read_bytes() == canonical_before


def test_workspace_failure_after_persistence_cleans_by_default(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    workspace_path: Path | None = None
    with pytest.raises(RuntimeError, match="runner failed"):
        with EvaluationWorkspace.create(manifest) as workspace:
            workspace_path = workspace.directory
            workspace.mark_results_persisted()
            raise RuntimeError("runner failed")
    assert workspace_path is not None and not workspace_path.exists()


def test_interruption_without_persisted_results_keeps_expiring_recovery_copy(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        with EvaluationWorkspace.create(manifest) as workspace:
            recovery = workspace.directory
            raise KeyboardInterrupt

    marker = json.loads((recovery / "workspace.json").read_text(encoding="utf-8"))
    assert marker["status"] == "recovery_needed"
    assert marker["results_persisted"] is False
    report = cleanup_stale_workspaces(
        manifest,
        max_age=timedelta(days=7),
        now=datetime.now(timezone.utc) + timedelta(days=8),
    )
    assert recovery.name in report["removed"]
    assert not recovery.exists()


def test_explicit_debug_retention_expires_and_reaper_skips_active_lease(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    with EvaluationWorkspace.create(manifest, keep_debug_copy=True) as workspace:
        retained = workspace.directory
        workspace.mark_results_persisted()
        active_report = cleanup_stale_workspaces(
            manifest,
            max_age=timedelta(0),
            now=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert retained.name in active_report["active"]
        assert retained.exists()

    expired = cleanup_stale_workspaces(
        manifest,
        max_age=timedelta(days=7),
        now=datetime.now(timezone.utc) + timedelta(days=8),
    )
    assert retained.name in expired["removed"]
    assert not retained.exists()


def test_parallel_workspaces_have_independent_writable_databases(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    barrier = Barrier(2)

    def run(value: str) -> tuple[str, Path]:
        with EvaluationWorkspace.create(manifest) as workspace:
            database = workspace.database_path
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE experiment_marker(value TEXT)")
                connection.execute("INSERT INTO experiment_marker VALUES (?)", (value,))
                connection.commit()
            barrier.wait(timeout=10)
            with sqlite3.connect(database) as connection:
                assert connection.execute("SELECT value FROM experiment_marker").fetchone() == (value,)
            workspace.mark_results_persisted()
            return workspace.directory.name, workspace.directory

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run, "baseline")
        second = executor.submit(run, "candidate")
        first_id, first_path = first.result(timeout=30)
        second_id, second_path = second.result(timeout=30)

    assert first_id != second_id
    assert not first_path.exists() and not second_path.exists()
    with sqlite3.connect(manifest.parent / "trivae.sqlite3") as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='experiment_marker'"
        ).fetchone() is None


def test_master_manifest_version_mismatch_fails_before_creating_workspace(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationContractError, match="manifest version"):
        EvaluationWorkspace.create(manifest)
    assert not (manifest.parent / WORKSPACE_ROOT_NAME).exists()


def test_create_application_refuses_a_frozen_master_before_writable_initialization(tmp_path: Path) -> None:
    from trivae.bootstrap.application import create_application

    manifest = _master(tmp_path)
    database = manifest.parent / "trivae.sqlite3"
    before = database.read_bytes()
    with pytest.raises(EvaluationContractError, match="cannot use a frozen master"):
        create_application(database)
    assert database.read_bytes() == before

    semantic_database = manifest.parent / "trivae.semantic.sqlite3"
    semantic_before = semantic_database.read_bytes()
    with pytest.raises(EvaluationContractError, match="semantic-index stores"):
        create_application(tmp_path / "trivae.sqlite3", semantic_index_path=semantic_database)
    assert semantic_database.read_bytes() == semantic_before


def test_reaper_does_not_follow_workspace_symlink_outside_managed_root(tmp_path: Path) -> None:
    manifest = _master(tmp_path)
    root = manifest.parent / WORKSPACE_ROOT_NAME
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    valuable_file = outside / "keep.txt"
    valuable_file.write_text("preserve", encoding="utf-8")
    (root / "run-escaped").symlink_to(outside, target_is_directory=True)

    report = cleanup_stale_workspaces(manifest, max_age=timedelta(0))
    assert any("run-escaped" in item for item in report["errors"])
    assert valuable_file.read_text(encoding="utf-8") == "preserve"


def test_clone_failure_does_not_fall_back_to_a_regular_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _master(tmp_path)
    from trivae.evaluation import frozen_data

    def fail_clone(source: Path, destination: Path) -> None:
        raise OSError("clonefile unsupported")

    monkeypatch.setattr(frozen_data, "_clone_file", fail_clone)
    output = tmp_path / "failed-clone"
    with pytest.raises(EvaluationContractError, match="cannot clone frozen data"):
        frozen_data.clone_frozen(manifest, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    ((None, "completed"), (RuntimeError("provider failure"), "failed"),
     (KeyboardInterrupt(), "interrupted")),
)
def test_formal_cli_persists_run_and_trace_before_workspace_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException | None,
    expected_status: str,
) -> None:
    from types import SimpleNamespace

    from trivae.evaluation import experiment_manifest
    from trivae.interfaces import cli

    freeze_manifest = _master(tmp_path)
    snapshot = DatasetSnapshot.from_database(freeze_manifest.parent / "trivae.sqlite3")
    case = _case(snapshot)
    suite = EvaluationSuite(
        "workspace-suite", 1, "core", (CaseReference(case.case_id, case.version),),
        "workspace lifecycle fixture", "2026-10-29T00:00:00+00:00",
    )
    variant = _variant()
    model_settings = ModelSettings("key", "https://example.com", "test-provider", "test-model", 8)
    output = tmp_path / "formal-record"

    class FakeApplication:
        def __init__(self, database: Path, evaluation_database: Path) -> None:
            self.evaluation_store = SQLiteEvaluationStore(evaluation_database)
            self.runner = EvaluationRunner(
                query_executor=_FailedExecutor(),
                trace_reader=lambda trace_id: _trace(trace_id),
                store=self.evaluation_store,
                snapshot_resolver=lambda: DatasetSnapshot.from_database(database),
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            self.evaluation_store.close()

        async def evaluate_suite(self, *args, **kwargs):
            if failure is not None:
                raise type(failure)(*failure.args)
            return await self.runner.run_suite(*args, **kwargs)

        def read_trace(self, trace_id: str):
            return _trace(trace_id)

    monkeypatch.setattr(cli, "load_environment_file", lambda path: None)
    monkeypatch.setattr(cli, "load_settings", lambda **kwargs: model_settings)
    monkeypatch.setattr(cli, "_load_variant", lambda path: variant)
    monkeypatch.setattr(cli, "_load_cases", lambda path: {case.identity: case, case.case_id: case})
    monkeypatch.setattr(cli, "create_application", lambda database, **kwargs: FakeApplication(
        database, kwargs["evaluation_database_path"],
    ))
    monkeypatch.setattr(experiment_manifest, "_git_commit", lambda: "commit:test")
    monkeypatch.setattr(experiment_manifest, "load_router_jev_settings",
                        lambda: SimpleNamespace(to_safe_dict=lambda: {}))
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite.to_dict()), encoding="utf-8")
    args = SimpleNamespace(
        env_file=None,
        evaluation_command="run",
        agent_model=None,
        models_config=None,
        suite=suite_path,
        variant=tmp_path / "variant.json",
        cases_dir=tmp_path / "cases",
        case_list=None,
        record_dir=output,
        freeze_manifest=freeze_manifest,
        allow_prompt_variant=False,
        database=None,
        evaluation_database=None,
        keep_workspace=False,
        repeat=1,
        judge_version="none",
    )

    if failure is None:
        assert cli._run_evaluation_command(args) == 0
    else:
        with pytest.raises(type(failure)):
            cli._run_evaluation_command(args)

    record = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
    assert record["status"] == expected_status
    assert record["freeze_id"] == json.loads(freeze_manifest.read_text(encoding="utf-8"))["freeze_id"]
    assert record["freeze_manifest_version"] == 1
    assert record["workspace_storage"]["mode"] == "temporary_apfs_clonefile"
    assert (output / "evaluation.sqlite3").is_file()
    assert (output / "runs.json").is_file()
    if failure is None:
        assert len(json.loads((output / "runs.json").read_text(encoding="utf-8"))) == 1
        traces = list((output / "traces").glob("trace-*.json"))
        assert len(traces) == 1
        assert json.loads(traces[0].read_text(encoding="utf-8"))["trace_id"] == "trace:test"
    workspace_root = freeze_manifest.parent / WORKSPACE_ROOT_NAME
    if expected_status == "interrupted":
        retained = list(workspace_root.iterdir())
        assert len(retained) == 1
        marker = json.loads((retained[0] / "workspace.json").read_text(encoding="utf-8"))
        assert marker["status"] == "interrupted_persisted"
        cleanup_stale_workspaces(
            freeze_manifest,
            max_age=timedelta(days=7),
            now=datetime.now(timezone.utc) + timedelta(days=8),
        )
    assert not workspace_root.exists()
