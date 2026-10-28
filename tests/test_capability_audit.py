"""Capability reference and reporting boundaries with small local fixtures."""
from __future__ import annotations

import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from tests.test_evaluation import _case
from tests.test_evaluation_platform import _local_run, _suite
from trivae.evaluation.capability_audit import audit_evidence, capability_report, reference_confirmed
from trivae.evaluation.contracts import EvaluationContractError, EvaluationReview
from trivae.evaluation.store import SQLiteEvaluationStore


def _message_case():
    case = _case()
    finding = case.reference_findings[0]
    evidence = replace(finding.reference_evidence[0], locator={"internal_message_id": "message:test"})
    return replace(case, reference_findings=(replace(finding, reference_evidence=(evidence,)),))


def _confirmed(case):
    finding = case.reference_findings[0]
    evidence = finding.reference_evidence[0]
    finding = replace(finding, provenance=replace(finding.provenance, adjudicated=True),
                      reference_evidence=(replace(evidence, provenance=replace(evidence.provenance, adjudicated=True)),))
    return replace(case, suite_tags=(*case.suite_tags, "review:confirmed"), reference_findings=(finding,))


def test_evidence_rechecks_source_and_does_not_promote_semantic_review(tmp_path):
    case = _message_case()
    database = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(database) as con:
        con.executescript("CREATE TABLE messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT); "
                          "CREATE TABLE forwarded_messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT);")
        con.execute("INSERT INTO messages VALUES ('message:test','session:test',200,'person','original source')")
    freeze = {"freeze_id": "freeze:test", "snapshot": case.dataset_snapshot.to_dict(), "index_state": {"revision": 1}}
    packet = {"freeze_id": "freeze:test", "snapshot_id": case.dataset_snapshot.snapshot_id,
              "cases": [{"case_id": case.case_id, "case_version": case.version,
              "evidence": [{"internal_message_id": "message:test", "session_id": "session:test", "timestamp": 200,
                            "sender_user_id": "person", "content_text": "original source", "quotes": ["original"]}]}]}
    with (patch("trivae.evaluation.capability_audit.DatasetSnapshot.from_database", return_value=case.dataset_snapshot),
          patch("trivae.evaluation.capability_audit._metadata", return_value={"revision": 1})):
        report = audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet, freeze=freeze, database=database)
        assert report["sources_checked"] == 1
        assert report["human_pending"] == 1
        packet["cases"][0]["evidence"][0]["quotes"] = ["different"]
        with pytest.raises(EvaluationContractError, match="quote does not match"):
            audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet, freeze=freeze, database=database)
        packet["cases"][0]["evidence"][0]["quotes"] = []
        packet["cases"][0]["evidence"][0]["timestamp"] = 201
        with pytest.raises(EvaluationContractError, match="metadata or text differs"):
            audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet, freeze=freeze, database=database)
        packet["cases"][0]["evidence"][0]["timestamp"] = 200
        packet["cases"][0]["case_version"] = 2
        with pytest.raises(EvaluationContractError, match="evidence packet is missing"):
            audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet, freeze=freeze, database=database)


def test_forwarded_message_keeps_parent_and_original_time(tmp_path):
    case = _message_case()
    database = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(database) as con:
        con.executescript("CREATE TABLE messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT); "
                          "CREATE TABLE forwarded_messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT, root_message_id TEXT, parent_message_id TEXT, "
                          "path TEXT, original_timestamp INTEGER);")
        con.execute("INSERT INTO forwarded_messages VALUES "
                    "('message:test','session:test',200,'person','forwarded text','root','parent','0.1',120)")
    freeze = {"freeze_id": "freeze:test", "snapshot": case.dataset_snapshot.to_dict(), "index_state": {"revision": 1}}
    entry = {"internal_message_id": "message:test", "session_id": "session:test", "timestamp": 200,
             "sender_user_id": "person", "content_text": "forwarded text", "root_message_id": "root",
             "parent_message_id": "parent", "path": "0.1", "original_timestamp": 120}
    packet = {"freeze_id": "freeze:test", "snapshot_id": case.dataset_snapshot.snapshot_id,
              "cases": [{"case_id": case.case_id, "case_version": 1, "evidence": [entry]}]}
    with (patch("trivae.evaluation.capability_audit.DatasetSnapshot.from_database", return_value=case.dataset_snapshot),
          patch("trivae.evaluation.capability_audit._metadata", return_value={"revision": 1})):
        assert audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet,
                              freeze=freeze, database=database)["sources_checked"] == 1
        entry["original_timestamp"] = 121
        with pytest.raises(EvaluationContractError, match="forwarded source metadata differs"):
            audit_evidence(suite=_suite(case), cases={case.identity: case}, packet=packet,
                           freeze=freeze, database=database)


def test_pending_references_do_not_enter_formal_quality_and_partial_usage_is_kept(tmp_path):
    case = _message_case()
    run = _local_run(tmp_path, case)
    store = SQLiteEvaluationStore(tmp_path / "runs.sqlite3")
    run = replace(run, terminal_status="completed", operational_measurements={
        "usage": {"input_tokens": 100, "known_output_tokens": 12, "responses_without_usage": 1},
        "latency_ms": 20.0, "tool_calls": 2})
    store.save_run(run)
    for review in (
        EvaluationReview("h1", run.run_id, "human", "cap-v2", {"task_completion": {"label": "pass"}},
                         None, None, None, False, "2026-10-28T01:00:01+00:00"),
        EvaluationReview("m1", run.run_id, "model_assisted", "cap-v2", {"task_completion": {"label": "fail"}},
                         None, None, None, True, "2026-10-28T01:00:02+00:00"),
    ):
        store.save_review(review)
    store.close()
    report = capability_report(tmp_path / "runs.sqlite3", _suite(case), {case.identity: case})
    axis = report["quality"]["task_completion"]
    assert axis["human_confirmed"]["denominator"] == 0
    assert axis["model_assisted_provisional"]["denominator"] == 1
    assert axis["model_assisted_provisional"]["numerator"] == 0
    assert report["usage"]["known_input_tokens"] == 100
    assert report["usage"]["known_output_tokens"] == 12
    assert report["usage"]["responses_without_usage"] == 1
    assert not reference_confirmed(case)
    confirmed = _confirmed(case)
    assert reference_confirmed(confirmed)
    eligible = capability_report(tmp_path / "runs.sqlite3", _suite(confirmed), {confirmed.identity: confirmed})
    assert eligible["quality"]["task_completion"]["human_confirmed"]["denominator"] == 1
    assert eligible["quality"]["task_completion"]["human_confirmed"]["numerator"] == 1
