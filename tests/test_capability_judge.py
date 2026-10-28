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
from trivae.evaluation.capability_judge import (
    JUDGE_PROMPT,
    JUDGE_V1_PROMPT,
    parse_review,
    parse_review_v1,
    prepare_review_input,
)
from trivae.evaluation.contracts import EvaluationContractError, EvaluationReview


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
    assert "不要求复述固定措辞" in JUDGE_PROMPT


def test_v1_judge_review_remains_readable_and_versioned():
    axes = {axis: {"label": "pass", "reason": "supported"} for axis in CAPABILITY_AXES}
    axes["evidence_recall"]["label"] = "unknown"
    review = parse_review_v1(json.dumps({"axes": axes}), run_id="run", judge_identity="fixture:model")
    assert review.reviewer_type == "model_assisted"
    assert review.rubric_version == "eval-rubric-v1"
    assert review.needs_adjudication
    assert review.quality_axes["evidence_recall"]["label"] == "unknown"
    assert "pass 表示未发现无依据断言" in JUDGE_V1_PROMPT
    legacy_payload = review.to_dict()
    legacy_payload.pop("diagnostics")
    restored = EvaluationReview.from_dict(legacy_payload)
    assert restored.rubric_version == "eval-rubric-v1"
    assert restored.diagnostics == ()


def test_v2_judge_scores_unknown_and_structured_diagnostics_round_trip():
    output = {
        "axes": {
            "task_satisfaction": {"score": 3, "reason": "核心需求已回答，次要细节略过。"},
            "answer_reliability": {"score": "unknown", "reason": "现有材料无法核实关键结论。"},
        },
        "overall_rationale": "主要问题是证据范围不足。",
        "diagnostics": [{
            "type": "omitted_key_information",
            "severity": "minor",
            "primary_dimension": "task_satisfaction",
            "answer_excerpt": None,
            "evidence": "用户要求的时间范围未见回答，也无相关参考证据。",
            "impact": "用户无法确认建议是否适用于近期情况。",
        }],
    }
    review = parse_review(json.dumps(output, ensure_ascii=False), run_id="run", judge_identity="fixture:model")
    assert review.rubric_version == "eval-rubric-v2"
    assert review.quality_axes["task_satisfaction"]["score"] == 3
    assert review.quality_axes["answer_reliability"]["score"] == "unknown"
    assert review.needs_adjudication
    restored = EvaluationReview.from_dict(review.to_dict())
    assert restored.diagnostics == tuple(output["diagnostics"])
    assert "五个" not in JUDGE_PROMPT
    assert "未提供或未找到证据不等于事实已被证明为假" in JUDGE_PROMPT


def test_v2_judge_rejects_invalid_scores_and_malformed_diagnostics():
    base = {
        "axes": {
            "task_satisfaction": {"score": 4, "reason": "完整。"},
            "answer_reliability": {"score": 3, "reason": "关键事实有支持。"},
        },
        "overall_rationale": "核心回答可靠。",
        "diagnostics": [],
    }
    invalid_score = json.loads(json.dumps(base))
    invalid_score["axes"]["task_satisfaction"]["score"] = True
    with pytest.raises(EvaluationContractError, match="v2 assessment"):
        parse_review(json.dumps(invalid_score), run_id="run", judge_identity="fixture:model")

    invalid_diagnostic = json.loads(json.dumps(base))
    invalid_diagnostic["diagnostics"] = [{"type": "citation_mismatch", "severity": "severe"}]
    with pytest.raises(EvaluationContractError, match="diagnostic 0"):
        parse_review(json.dumps(invalid_diagnostic), run_id="run", judge_identity="fixture:model")


def test_v2_partial_score_is_flagged_for_human_adjudication():
    output = {
        "axes": {
            "task_satisfaction": {"score": 4, "reason": "核心需求完整满足。"},
            "answer_reliability": {"score": 2, "reason": "存在影响部分结论的证据错配。"},
        },
        "overall_rationale": "主结论仍有可靠部分，但一个重要分支需要人工核对。",
        "diagnostics": [],
    }
    review = parse_review(json.dumps(output, ensure_ascii=False), run_id="run", judge_identity="fixture:model")
    assert review.needs_adjudication


def test_v2_moderate_diagnostic_is_flagged_even_with_passing_score():
    output = {
        "axes": {
            "task_satisfaction": {"score": 4, "reason": "核心需求完整满足。"},
            "answer_reliability": {"score": 3, "reason": "主结论可信，但有一个实质性边界问题。"},
        },
        "overall_rationale": "应由人工确认中等问题与合格评分是否一致。",
        "diagnostics": [{
            "type": "unsupported_assertion",
            "severity": "moderate",
            "primary_dimension": "answer_reliability",
            "answer_excerpt": "未提供依据的关键细节",
            "evidence": "冻结证据未能支持该细节。",
            "impact": "该细节可能影响用户选择。",
        }],
    }
    review = parse_review(json.dumps(output, ensure_ascii=False), run_id="run", judge_identity="fixture:model")
    assert review.quality_axes["answer_reliability"]["score"] == 3
    assert review.needs_adjudication


def test_v1_parser_still_rejects_incomplete_five_axis_output():
    axes = {axis: {"label": "pass", "reason": "supported"} for axis in CAPABILITY_AXES}
    del axes["factual_correctness"]
    with pytest.raises(EvaluationContractError, match="five quality axes"):
        parse_review_v1(json.dumps({"axes": axes}), run_id="run", judge_identity="fixture:model")
