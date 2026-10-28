"""Private bundle checks retain context and do not claim semantic verification."""
import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from scripts.verify_capability_bundle import verify
from tests.test_capability_audit import _message_case
from tests.test_evaluation_platform import _suite
from trivae.evaluation.contracts import EvaluationContractError


def test_bundle_detects_changed_context_and_requires_distinct_review_search(tmp_path):
    base = _message_case()
    finding = replace(base.reference_findings[0], criterion="capability.reference-example", expected_semantics="example")
    case = replace(base, time_context={"as_of": "2026-10-28T12:00:00+08:00"}, reference_findings=(finding,),
                   suite_tags=(*base.suite_tags, "gt:gt1"), critical_requirements=("core",),
                   uncertainty_constraints=("limited",))
    suite = _suite(case)
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    (case_dir / "case.json").write_text(json.dumps(case.to_dict()))
    database = tmp_path / "database.sqlite3"
    with sqlite3.connect(database) as con:
        con.executescript("CREATE TABLE messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT, reply_to_source_message_id TEXT); "
                          "CREATE TABLE chat_sessions(session_id TEXT, name TEXT);")
        con.execute("INSERT INTO messages VALUES ('message:test','session:test',200,'person','original',NULL)")
        con.execute("INSERT INTO chat_sessions VALUES ('session:test','group')")
    source = {"internal_message_id": "message:test", "session_id": "session:test", "timestamp": 200,
              "sender_user_id": "person", "content_text": "original", "reply_to_source_message_id": None}
    entry = {**source, "kind": "message", "session_name": "group", "context": [source.copy()]}
    files = {
        "suite.json": suite.to_dict(),
        "freeze.json": {},
        "questions-frozen.json": {"as_of": case.time_context["as_of"], "frozen_at": "2026-10-28T12:00:00+08:00",
                                  "cases": [{"case_id": case.case_id, "version": 1, "query": case.query}]},
        "ground-truth-v1.json": {"suite_id": suite.suite_id, "suite_version": suite.version, "gt_version": "gt1",
            "as_of": case.time_context["as_of"], "created_at": "2026-10-28T15:00:00+08:00", "cases": [{
                "case_id": case.case_id, "query": case.query, "user_need": "need", "must_answer": "core",
                "evidence_limitations": "limited", "reasonable_other_answers": "others", "evidence_status": "充分",
                "scoring_eligibility": "model_assisted", "review": {"revision_reason": "reviewed"},
                "candidate_facts": [{"claim": "example", "epistemic_type": "opinion", "message_ids": ["message:test"]}]}]},
        "evidence.json": {"gt_version": "gt1", "cases": [{"case_id": case.case_id, "evidence": [entry]}]},
        "search-initial.json": {"searched_at": "2026-10-28T13:00:00+08:00", "cases": [{"case_id": case.case_id,
                                 "searches": [{"fts_expression": "first"}]}]},
        "search-review.json": {"review_search_completed_at": "2026-10-28T14:00:00+08:00", "cases": [{
                                 "case_id": case.case_id, "searches": [{"fts_expression": "other"}]}]},
        "revision-log.json": {"revisions": [{"case_id": case.case_id}]},
    }
    for name, value in files.items():
        (tmp_path / name).write_text(json.dumps(value))
    with patch("scripts.verify_capability_bundle.audit_evidence", return_value={}):
        result = verify(tmp_path, tmp_path / "suite.json", tmp_path / "freeze.json", database)
        assert result["context_rows_checked"] == 1
        assert "do not establish semantic" in result["limitations"]
        files["evidence.json"]["cases"][0]["evidence"][0]["context"][0]["content_text"] = "changed"
        (tmp_path / "evidence.json").write_text(json.dumps(files["evidence.json"]))
        with pytest.raises(EvaluationContractError, match="saved context differs"):
            verify(tmp_path, tmp_path / "suite.json", tmp_path / "freeze.json", database)
        files["evidence.json"]["cases"][0]["evidence"][0]["context"][0]["content_text"] = "original"
        (tmp_path / "evidence.json").write_text(json.dumps(files["evidence.json"]))
        files["search-review.json"]["cases"][0]["searches"][0]["fts_expression"] = "first"
        (tmp_path / "search-review.json").write_text(json.dumps(files["search-review.json"]))
        with pytest.raises(EvaluationContractError, match="review search expressions missing"):
            verify(tmp_path, tmp_path / "suite.json", tmp_path / "freeze.json", database)
