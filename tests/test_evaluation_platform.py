"""Local evaluation export, snapshot and experiment contract tests."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tests.test_evaluation import _case, _FailedExecutor, _snapshot, _trace, _variant
from trivae.evaluation.contracts import (
    CaseReference,
    DatasetSnapshot,
    EvaluationContractError,
    EvaluationReview,
    EvaluationSuite,
)
from trivae.evaluation.experiment_manifest import compare_experiments, finish_experiment, prepare_experiment
from trivae.evaluation.frozen_data import clone_frozen, freeze_data
from trivae.evaluation.langsmith_sync import export_experiment, sync_review
from trivae.evaluation.reporting import run_report
from trivae.evaluation.runner import EvaluationRunner
from trivae.evaluation.store import SQLiteEvaluationStore


def _suite(case):
    return EvaluationSuite("sample-suite", 1, "core", (CaseReference(case.case_id, case.version),),
                           "fixture suite", "2026-10-28T00:00:00+00:00")


def _local_run(tmp_path, case=None, variant=None):
    case = case or _case()
    variant = variant or _variant()
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    runner = EvaluationRunner(query_executor=_FailedExecutor(), trace_reader=lambda _: _trace(), store=store,
                              snapshot_resolver=lambda: case.dataset_snapshot)
    runs = asyncio.run(runner.run_suite(_suite(case), {case.identity: case}, variant))
    store.close()
    return runs[0]


def _make_data(tmp_path: Path):
    canonical = tmp_path / "trivae.sqlite3"
    con = sqlite3.connect(canonical)
    con.executescript("""
        CREATE TABLE sources(source_id TEXT, file_name TEXT, adapter TEXT, format_version TEXT, platform TEXT, external_chat_id TEXT);
        CREATE TABLE messages(timestamp INTEGER, text TEXT);
        CREATE TABLE import_batches(id INTEGER);
        CREATE TABLE messages_fts(text TEXT);
        CREATE TABLE trivae_derived_meta(key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO sources VALUES ('s', 'sample.json', 'test', '1', 'test', 'chat');
        INSERT INTO messages VALUES (10, 'original');
        INSERT INTO messages_fts VALUES ('original');
        INSERT INTO trivae_derived_meta VALUES ('canonical_revision', '1'), ('lexical_canonical_revision', '1');
    """)
    con.commit()
    con.close()
    semantic = tmp_path / "trivae.semantic.sqlite3"
    con = sqlite3.connect(semantic)
    con.execute("CREATE TABLE semantic_index_state(state_id INTEGER, status TEXT, canonical_revision INTEGER, identity_json TEXT)")
    con.execute("INSERT INTO semantic_index_state VALUES (1, 'completed', 1, ?)",
                (json.dumps({"database_identity": "trivae.sqlite3", "embedding": "fixture"}),))
    con.commit()
    con.close()
    return canonical, semantic


def test_frozen_sqlite_master_clone_and_revision_gate(tmp_path):
    canonical, semantic = _make_data(tmp_path)
    frozen = tmp_path / "master"
    info = freeze_data(canonical, semantic, frozen)
    assert info["index_state"]["canonical_revision"] == 1
    with sqlite3.connect(canonical) as con:
        con.execute("UPDATE messages SET text='new content'")
    clone = tmp_path / "clone"
    clone_frozen(frozen / "freeze.json", clone)
    with sqlite3.connect(clone / canonical.name) as con:
        assert con.execute("SELECT text FROM messages").fetchone()[0] == "original"
    with pytest.raises(EvaluationContractError, match="already exists"):
        freeze_data(canonical, semantic, frozen)
    with sqlite3.connect(semantic) as con:
        con.execute("UPDATE semantic_index_state SET canonical_revision=2")
    with pytest.raises(EvaluationContractError, match="semantic index"):
        freeze_data(canonical, semantic, tmp_path / "stale")


def test_snapshot_round_trip_preserves_large_source_inventory(tmp_path):
    canonical, _ = _make_data(tmp_path)
    with sqlite3.connect(canonical) as con:
        con.executemany("INSERT INTO sources VALUES (?, ?, 'test', '1', 'test', 'chat')",
                        [(f"s{i}", f"source{i}.json") for i in range(205)])
    snapshot = DatasetSnapshot.from_database(canonical)
    restored = DatasetSnapshot.from_dict(snapshot.to_dict())
    assert len(restored.manifest["sources"]) == 206
    assert restored.deterministic_fingerprint == snapshot.deterministic_fingerprint


def test_sync_independent_scores_trace_and_idempotence(tmp_path):
    case = _case()
    run = _local_run(tmp_path, case)
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    store.save_review(EvaluationReview("review-1", run.run_id, "human", "rubric-v1",
                                      {"citation_validity": {"score": 0.5}}, None, None, None, False,
                                      "2026-10-28T00:00:02+00:00"))
    store.save_review(EvaluationReview("review-2", run.run_id, "model_assisted", "judge-v1",
                                      {"citation_validity": {"score": 0.8}}, None, None, None, True,
                                      "2026-10-28T00:00:03+00:00"))
    store.close()
    trace_db = tmp_path / "trace.sqlite3"
    with sqlite3.connect(trace_db) as con:
        con.executescript("CREATE TABLE traces(trace_id TEXT, terminal_outcome TEXT); "
                          "CREATE TABLE trace_events(trace_id TEXT, sequence INTEGER, stage TEXT, operation TEXT, "
                          "phase TEXT, outcome TEXT, duration_ms REAL, payload_json TEXT, failure_json TEXT);")
        con.execute("INSERT INTO traces VALUES (?,?)", (run.trace_id, "error"))
        con.execute("INSERT INTO trace_events VALUES (?,?,?,?,?,?,?,?,?)", (run.trace_id, 1, "model", "model.request",
                    "failed", "error", 2.0, '{"secret":"private"}', '{"error_code":"MODEL_ERROR"}'))
    captures = []
    def handler(request):
        captures.append(json.loads(request.content))
        return httpx.Response(200, json={"dataset": {"id": captures[-1]["dataset_id"]},
                                         "experiment": {"id": "project-" + str(len(captures))}})
    kwargs = dict(evaluation_db=tmp_path / "runs.sqlite3", suite=_suite(case), cases={case.identity: case},
                  include_content=True, run_ids=[run.run_id], experiment="sample-exp", ledger_path=tmp_path / "ledger.sqlite3",
                  trace_db=trace_db, api_key="ls_test_key", transport=httpx.MockTransport(handler))
    result = export_experiment(**kwargs)
    assert result["status"] == "synced"
    row = captures[0]["results"][0]
    assert row["inputs"]["question"] == case.query
    assert row["actual_outputs"]["local_run_id"] == run.run_id
    assert row["actual_outputs"]["trace"]["events"][0]["operation"] == "model.request"
    assert row["actual_outputs"]["trace"]["events"][0]["failure"]["error_code"] == "MODEL_ERROR"
    assert row["error"] == "Trivae termination: failed"
    assert "private" not in json.dumps(captures)
    feedback = {x["key"]: x for x in row["evaluation_scores"]}
    assert feedback["human.citation_validity"]["score"] == 0.5
    assert feedback["llm_assisted.citation_validity"]["comment"] == "needs_adjudication"
    assert not any("accuracy" in key for key in feedback)
    assert export_experiment(**kwargs)["status"] == "already_synced"
    assert len(captures) == 1
    candidate = _local_run(tmp_path, case, _variant(variant_id="candidate"))
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    candidate = replace(candidate, started_at=run.started_at, completed_at=run.completed_at)
    store.save_run(candidate)
    with pytest.raises(EvaluationContractError, match="same experiment start time"):
        export_experiment(**{**kwargs, "experiment": "same-time", "run_ids": [candidate.run_id]})
    candidate = replace(candidate, started_at=(datetime.fromisoformat(run.started_at) + timedelta(seconds=1)).isoformat(),
                        completed_at=(datetime.fromisoformat(run.completed_at) + timedelta(seconds=1)).isoformat())
    store.save_run(candidate)
    store.close()
    result2 = export_experiment(**{**kwargs, "experiment": "candidate-exp", "run_ids": [candidate.run_id]})
    assert result2["dataset_id"] == result["dataset_id"]
    assert captures[0]["results"][0]["row_id"] == captures[1]["results"][0]["row_id"]

    with sqlite3.connect(tmp_path / "ledger.sqlite3") as con:
        con.execute("UPDATE external_runs SET remote_run_id='remote-run' WHERE local_run_id=?", (run.run_id,))
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    store.save_review(EvaluationReview("review-3", run.run_id, "human", "rubric-v1",
                                      {"evidence_coverage": {"label": "fail"}}, None, None, None, False,
                                      "2026-10-28T00:00:04+00:00"))
    store.close()
    feedback_calls = []
    def feedback_handler(request):
        feedback_calls.append(json.loads(request.content))
        return httpx.Response(200, json={})
    review_kwargs = dict(evaluation_db=tmp_path / "runs.sqlite3", ledger_path=tmp_path / "ledger.sqlite3",
                         experiment="sample-exp", review_id="review-3", api_key="ls_test_key",
                         transport=httpx.MockTransport(feedback_handler))
    assert sync_review(**review_kwargs)["axes_uploaded"] == 1
    assert sync_review(**review_kwargs)["status"] == "already_synced"
    assert len(feedback_calls) == 1
    assert run_report(tmp_path / "runs.sqlite3")["counts"]["human_quality_failed"] == 1


def test_export_failure_does_not_affect_local_runner_or_repeat_ambiguous_upload(tmp_path):
    case = _case()
    run = _local_run(tmp_path, case)
    def offline(request):
        raise httpx.ConnectError("offline", request=request)
    kwargs = dict(evaluation_db=tmp_path / "runs.sqlite3", suite=_suite(case), run_ids=[run.run_id],
                  experiment="offline", ledger_path=tmp_path / "ledger.sqlite3", api_key="ls_test_key",
                  transport=httpx.MockTransport(offline))
    with pytest.raises(EvaluationContractError, match="outcome unknown"):
        export_experiment(**kwargs)
    with pytest.raises(EvaluationContractError, match="already attempted"):
        export_experiment(**kwargs)
    second = _local_run(tmp_path, case)
    assert second.run_id != run.run_id
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    assert len(store.list_runs()) == 2
    store.close()


def test_export_refuses_configured_key_in_content(tmp_path, monkeypatch):
    case = _case()
    run = _local_run(tmp_path, case)
    monkeypatch.setenv("TRIVAE_MODEL_API_KEY", "sensitive-fixture-secret")
    path = tmp_path / "content.json"
    path.write_text(json.dumps({"cases": {case.identity: {"question": "sensitive-fixture-secret"}}}))
    with pytest.raises(EvaluationContractError, match="configured secret"):
        export_experiment(evaluation_db=tmp_path / "runs.sqlite3", suite=_suite(case), run_ids=[run.run_id],
                          experiment="safety", ledger_path=tmp_path / "ledger.sqlite3", api_key="ls_test_key",
                          content_path=path)


def test_historical_single_case_requires_benchmark_record_and_preserves_judge_failure(tmp_path):
    case = _case()
    run = _local_run(tmp_path, case)
    run = replace(run, suite_id="single_case")
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    store.save_run(run)
    store.close()
    records = tmp_path / "records.json"
    records.write_text(json.dumps([{"run_id": run.run_id, "case_id": run.case_id, "variant_id": run.variant_id,
                                    "metrics": [{"name": "evidence_recall", "value": 0.5, "scope": "evidence"}]}]))
    judgments = tmp_path / "judgments.json"
    judgments.write_text(json.dumps([{"run_id": run.run_id, "status": "judge_failed"}]))
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"dataset": {"id": "dataset"}, "experiment": {"id": "project"}})
    kwargs = dict(evaluation_db=tmp_path / "runs.sqlite3", suite=_suite(case), run_ids=[run.run_id],
                  experiment="historical", ledger_path=tmp_path / "ledger.sqlite3", api_key="ls_test_key",
                  transport=httpx.MockTransport(handler))
    with pytest.raises(EvaluationContractError, match="does not belong"):
        export_experiment(**kwargs)
    export_experiment(**kwargs, records_path=records, judgments_path=judgments)
    row = captured[0]["results"][0]
    assert row["actual_outputs"]["recorded_local_suite"] == "single_case@v1"
    scores = {item["key"]: item for item in row["evaluation_scores"]}
    assert scores["benchmark.evidence_recall"]["score"] == 0.5
    assert scores["judge.execution_status"]["value"] == "judge_failed"
    assert run_report(tmp_path / "runs.sqlite3", judgments=judgments)["counts"]["judge_failed"] == 1


def test_explicit_import_time_preserves_original_execution_times(tmp_path):
    case = _case()
    run = _local_run(tmp_path, case)
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"dataset": {"id": "dataset"}, "experiment": {"id": "project"}})
    export_experiment(evaluation_db=tmp_path / "runs.sqlite3", suite=_suite(case), run_ids=[run.run_id],
                      experiment="import-time", ledger_path=tmp_path / "ledger.sqlite3", api_key="ls_test_key",
                      import_time=True, transport=httpx.MockTransport(handler))
    body = captured[0]
    assert body["experiment_metadata"]["time_semantics"] == "import_time"
    assert body["results"][0]["actual_outputs"]["original_started_at"] == run.started_at
    assert body["results"][0]["actual_outputs"]["original_completed_at"] == run.completed_at
    assert datetime.fromisoformat(body["experiment_start_time"]) < datetime.fromisoformat(body["experiment_end_time"])


def test_formal_manifest_records_and_rejects_incomparable_data(tmp_path, monkeypatch):
    canonical, semantic = _make_data(tmp_path)
    freeze_data(canonical, semantic, tmp_path / "master")
    clone_frozen(tmp_path / "master/freeze.json", tmp_path / "work")
    snapshot = DatasetSnapshot.from_database(tmp_path / "work" / canonical.name)
    case = _case(snapshot)
    variant = replace(_variant(), code_version="commit1")
    from trivae.config.settings import ModelSettings
    from trivae.evaluation import experiment_manifest as module
    monkeypatch.setattr(module, "_git_commit", lambda: "commit1")
    monkeypatch.setattr(module, "load_settings", lambda: ModelSettings("key", "https://example.com", "test-provider", "test-model", 8))
    monkeypatch.setattr(module, "load_router_jev_settings", lambda: type("R", (), {"to_safe_dict": lambda self: {}})())
    args = dict(suite=_suite(case), cases={case.identity: case}, variant=variant,
                database=tmp_path / "work" / canonical.name, freeze_path=tmp_path / "work/freeze.json",
                repetitions=1, judge_version="none")
    a = prepare_experiment(**args, output_dir=tmp_path / "exp-a")
    b = prepare_experiment(**args, output_dir=tmp_path / "exp-b")
    run = _local_run(tmp_path, case, variant)
    candidate_run = _local_run(tmp_path, case, replace(variant, variant_id="candidate"))
    finish_experiment(tmp_path / "exp-a", a, (run,))
    finish_experiment(tmp_path / "exp-b", b, (candidate_run,))
    assert compare_experiments(tmp_path / "exp-a/experiment.json", tmp_path / "exp-b/experiment.json")["comparable"]
    b["freeze_id"] = "different"
    finish_experiment(tmp_path / "exp-b", b, (candidate_run,))
    result = compare_experiments(tmp_path / "exp-a/experiment.json", tmp_path / "exp-b/experiment.json")
    assert not result["comparable"] and "freeze_id differs" in result["reasons"]


def test_snapshot_same_id_with_different_manifest_is_rejected(tmp_path):
    case = _case()
    changed = replace(_snapshot(), deterministic_fingerprint="other manifest")
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    runner = EvaluationRunner(query_executor=_FailedExecutor(), trace_reader=lambda _: _trace(), store=store,
                              snapshot_resolver=lambda: changed)
    with pytest.raises(EvaluationContractError, match="manifest differs"):
        asyncio.run(runner.run_case(case, _variant()))
    store.close()


def test_case_version_review_and_suite_rerun_cli(tmp_path, monkeypatch, capsys):
    from trivae.interfaces import cli

    case = _case()
    source = tmp_path / "source.json"
    case.to_json(source)
    versioned = tmp_path / "cases" / "case.json"
    assert cli.main(["eval", "cases", "new-version", "--source", str(source), "--output", str(versioned)]) == 0
    from trivae.evaluation.contracts import EvaluationCaseBundle
    new_case = EvaluationCaseBundle.from_json(versioned)
    assert new_case.version == 2
    assert "pending review" in new_case.provenance.method
    suite = _suite(new_case)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite.to_dict()), encoding="utf-8")
    variant_path = tmp_path / "variant.json"
    variant_path.write_text(json.dumps(_variant().to_dict()), encoding="utf-8")
    db = tmp_path / "runs.sqlite3"

    class Application:
        def __init__(self):
            self.store = SQLiteEvaluationStore(db)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            self.store.close()
        async def evaluate_suite(self, s, cases, variant, *, repetitions):
            runner = EvaluationRunner(query_executor=_FailedExecutor(), trace_reader=lambda _: _trace(),
                                      store=self.store, snapshot_resolver=lambda: new_case.dataset_snapshot)
            return await runner.run_suite(s, cases, variant, repetitions=repetitions)

    monkeypatch.setattr(cli, "create_application", lambda *args, **kwargs: Application())
    command = ["eval", "run", "--suite", str(suite_path), "--variant", str(variant_path),
               "--cases-dir", str(versioned.parent), "--evaluation-database", str(db)]
    assert cli.main(command) == 0
    assert cli.main(command) == 0
    store = SQLiteEvaluationStore(db)
    runs = store.list_runs()
    store.close()
    assert len(runs) == 2 and all(r.case_version == 2 for r in runs)
    review_path = tmp_path / "review.json"
    review = EvaluationReview("review-fixture", runs[0].run_id, "human", "review-v1",
                              {"citation_validity": {"label": "fail"}}, None, None, None, False,
                              "2026-10-28T00:00:00+00:00")
    review_path.write_text(json.dumps(review.to_dict()), encoding="utf-8")
    assert cli.main(["eval", "review", "--evaluation-database", str(db), "--review", str(review_path)]) == 0
    assert cli.main(["eval", "review", "--evaluation-database", str(db), "--review", str(review_path)]) == 1
    assert run_report(db)["counts"]["human_quality_failed"] == 1
    capsys.readouterr()


def test_suite_candidates_drop_old_ground_truth(tmp_path):
    from trivae.evaluation.suite_maintenance import rebase_suite

    canonical, semantic = _make_data(tmp_path)
    freeze_data(canonical, semantic, tmp_path / "master")
    original = _case()
    result = rebase_suite(suite=_suite(original), cases={original.identity: original},
                          freeze_path=tmp_path / "master/freeze.json", output_dir=tmp_path / "candidates")
    assert result["review_status"] == "pending"
    data = json.loads((tmp_path / "candidates/cases/candidate-case-test.json").read_text())
    assert data["reference_findings"] == []
    assert data["provenance"]["source"] == original.identity
    assert "review:pending" in data["suite_tags"]
