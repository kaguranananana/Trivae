"""Offline quality review can evaluate evidence outside the reference packet."""
import json
import sqlite3
from dataclasses import replace
from unittest.mock import patch

import pytest

from tests.test_conversation import _artifact
from tests.test_evaluation import _case
from tests.test_evaluation_platform import _local_run
from trivae.conversation.serialization import serialize_answer_artifact
from trivae.evaluation.capability_audit import CAPABILITY_AXES
from trivae.evaluation.capability_judge import JUDGE_PROMPT, parse_review, prepare_review_input
from trivae.evaluation.contracts import EvaluationContractError


def test_review_reloads_alternative_citation_and_preserves_full_answer(tmp_path):
    case = _case()
    artifact = _artifact()
    item = artifact.evidence_items[0]
    source = item.sources[0]
    alternative = replace(source.reference, session_id="session:test", internal_message_id="alternative")
    item = replace(item, sources=(replace(source, reference=alternative),))
    artifact = replace(artifact, evidence_items=(item, artifact.evidence_items[1]))
    database = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(database) as con:
        con.executescript("CREATE TABLE messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
                          "sender_user_id TEXT, content_text TEXT, reply_to_source_message_id TEXT); "
                          "CREATE TABLE conversation_messages(conversation_id TEXT, role TEXT, ordinal INTEGER, "
                          "answer_artifact_json TEXT);")
        con.execute("INSERT INTO messages VALUES ('alternative','session:test',200,'user','full source',NULL)")
        con.execute("INSERT INTO conversation_messages VALUES ('conversation','assistant',0,?)",
                    (serialize_answer_artifact(artifact),))
    run = replace(_local_run(tmp_path, case), terminal_status="completed", query_result={"conversation_id": "conversation"})
    truth = {"case_id": case.case_id, "version": case.version, "query": case.query,
             "scoring_eligibility": "model_assisted", "candidate_facts": [{"message_ids": ["different-reference"]}]}
    packet = {"case_id": case.case_id, "case_version": case.version, "evidence": []}
    with patch("trivae.evaluation.capability_judge.DatasetSnapshot.from_database", return_value=case.dataset_snapshot):
        result = prepare_review_input(case=case, truth=truth, packet=packet, run=run, database=database)
        assert result["answer_cited_messages"][0]["internal_message_id"] == "alternative"
        assert result["answer_cited_messages"][0]["content_text"] == "full source"
        assert result["answer_artifact"]["content_blocks"][0]["text"] == artifact.content_blocks[0].text
        with sqlite3.connect(database) as con:
            con.execute("UPDATE messages SET session_id='other' WHERE internal_message_id='alternative'")
        with pytest.raises(EvaluationContractError, match="cannot be verified"):
            prepare_review_input(case=case, truth=truth, packet=packet, run=run, database=database)
    assert "不要要求" in JUDGE_PROMPT


def test_judge_labels_are_provisional_and_incomplete_outputs_fail():
    axes = {axis: {"label": "pass", "reason": "supported"} for axis in CAPABILITY_AXES}
    axes["evidence_recall"]["label"] = "unknown"
    review = parse_review(json.dumps({"axes": axes}), run_id="run", judge_identity="fixture:model")
    assert review.reviewer_type == "model_assisted"
    assert review.needs_adjudication
    assert review.quality_axes["evidence_recall"]["label"] == "unknown"
    del axes["factual_correctness"]
    with pytest.raises(EvaluationContractError, match="five quality axes"):
        parse_review(json.dumps({"axes": axes}), run_id="run", judge_identity="fixture:model")
