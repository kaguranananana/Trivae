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
    CAPABILITY_AXES_V3,
    JUDGE_PROMPT,
    JUDGE_PROMPT_V2_1,
    JUDGE_PROMPT_V3,
    JUDGE_V1_PROMPT,
    PAIRWISE_JUDGE_PROMPT,
    RUBRIC_VERSION_V2_1,
    RUBRIC_VERSION_V3,
    aggregate_position_swapped_pairwise,
    axes_for_rubric,
    build_review_payload,
    compute_adjudication_priority,
    judge_prompt_for,
    parse_pairwise_judgment,
    parse_review,
    parse_review_v1,
    prepare_pairwise_input,
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


def test_v2_1_calibration_preserves_score_contract_and_v2_prompt():
    output = {
        "axes": {
            "task_satisfaction": {"score": 3, "reason": "原问题核心需求已满足。"},
            "answer_reliability": {"score": 3, "reason": "主结论可信，局部问题已记录。"},
        },
        "overall_rationale": "单个局部问题不改变整答结论。",
        "diagnostics": [{
            "type": "unsupported_assertion",
            "severity": "moderate",
            "primary_dimension": "answer_reliability",
            "answer_excerpt": "某个局部说法",
            "evidence": "输入材料没有支持该局部说法。",
            "impact": "该局部信息可能影响一个次级细节。",
        }],
    }
    review = parse_review(
        json.dumps(output, ensure_ascii=False), run_id="run", judge_identity="fixture:model",
        rubric_version=RUBRIC_VERSION_V2_1,
    )
    assert review.rubric_version == RUBRIC_VERSION_V2_1
    assert review.quality_axes["answer_reliability"]["score"] == 3
    assert review.diagnostics[0]["severity"] == "moderate"
    assert review.needs_adjudication
    assert judge_prompt_for("eval-rubric-v2") == JUDGE_PROMPT
    assert "GT 中更理想化的案例" in JUDGE_PROMPT_V2_1
    assert "severity 不机械映射为轴分" in JUDGE_PROMPT_V2_1
    assert "GT 中更理想化的案例" not in JUDGE_PROMPT


def test_v1_parser_still_rejects_incomplete_five_axis_output():
    axes = {axis: {"label": "pass", "reason": "supported"} for axis in CAPABILITY_AXES}
    del axes["factual_correctness"]
    with pytest.raises(EvaluationContractError, match="five quality axes"):
        parse_review_v1(json.dumps({"axes": axes}), run_id="run", judge_identity="fixture:model")


def test_v3_three_axis_parsing_and_tiered_adjudication_priority():
    assert axes_for_rubric(RUBRIC_VERSION_V3) == CAPABILITY_AXES_V3
    assert judge_prompt_for(RUBRIC_VERSION_V3) == JUDGE_PROMPT_V3
    assert "evidence_grounding" in JUDGE_PROMPT_V3
    assert "epistemic_calibration" in JUDGE_PROMPT_V3
    assert "诚实保护" in JUDGE_PROMPT_V3
    assert "防割裂封顶" in JUDGE_PROMPT_V3

    # Passing scores with an isolated moderate diagnostic => priority='low', needs_adjudication=False
    low_payload = {
        "axes": {
            "task_satisfaction": {"score": 4, "reason": "完整回答核心问题。"},
            "evidence_grounding": {"score": 4, "reason": "具体事实与引用完全一致。"},
            "epistemic_calibration": {"score": 3, "reason": "整体克制，仅有一处局部外推。"},
        },
        "overall_rationale": "主体可靠，局部表述略宽。",
        "diagnostics": [{
            "type": "unsupported_assertion",
            "severity": "moderate",
            "primary_dimension": "epistemic_calibration",
            "answer_excerpt": "普遍反馈不错",
            "evidence": "仅见 2 位群友正面评价。",
            "impact": "略微高估群内共识，但不改变主结论。",
        }],
    }
    low_review = parse_review(
        json.dumps(low_payload, ensure_ascii=False),
        run_id="run-low",
        judge_identity="fixture:model",
        rubric_version=RUBRIC_VERSION_V3,
    )
    assert low_review.rubric_version == RUBRIC_VERSION_V3
    assert low_review.adjudication_priority == "low"
    assert not low_review.needs_adjudication
    restored = EvaluationReview.from_dict(low_review.to_dict())
    assert restored.adjudication_priority == "low"
    assert restored.quality_axes == low_review.quality_axes

    # Medium priority: a 2 score without severe/unknown/cross-axis conflict
    assert compute_adjudication_priority(
        scores={"task_satisfaction": 3, "evidence_grounding": 4, "epistemic_calibration": 2},
        diagnostics=[],
    ) == "medium"

    # High priority: cross-axis conflict (task_satisfaction=4 while calibration<=2)
    conflict_payload = json.loads(json.dumps(low_payload))
    conflict_payload["axes"]["epistemic_calibration"]["score"] = 2
    conflict_review = parse_review(
        json.dumps(conflict_payload, ensure_ascii=False),
        run_id="run-conflict",
        judge_identity="fixture:model",
        rubric_version=RUBRIC_VERSION_V3,
    )
    assert conflict_review.adjudication_priority == "high"
    assert conflict_review.needs_adjudication

    # High priority: unknown or severe or score <= 1
    assert compute_adjudication_priority(
        scores={"task_satisfaction": 3, "evidence_grounding": "unknown", "epistemic_calibration": 3},
        diagnostics=[],
    ) == "high"
    assert compute_adjudication_priority(
        scores={"task_satisfaction": 3, "evidence_grounding": 3, "epistemic_calibration": 3},
        diagnostics=[{"severity": "severe"}],
    ) == "high"
    assert compute_adjudication_priority(
        scores={"task_satisfaction": 4, "evidence_grounding": 4, "epistemic_calibration": 4},
        diagnostics=[],
    ) == "none"

    # Rejects v2 primary_dimension under v3
    bad_dim = json.loads(json.dumps(low_payload))
    bad_dim["diagnostics"][0]["primary_dimension"] = "answer_reliability"
    with pytest.raises(EvaluationContractError, match="primary_dimension"):
        parse_review(
            json.dumps(bad_dim, ensure_ascii=False),
            run_id="run-bad",
            judge_identity="fixture:model",
            rubric_version=RUBRIC_VERSION_V3,
        )


def test_v3_input_enriches_time_sender_far_reply_same_ms_and_deduplicates_threads(tmp_path):
    base_case = _case()
    case = replace(
        base_case,
        time_context={"as_of": "2026-10-28T12:00:00+08:00", "data_cutoff": "2026-10-27T21:44:51+08:00"},
    )
    artifact = _artifact()
    item = artifact.evidence_items[0]
    src0 = item.sources[0]
    ref_reply = replace(src0.reference, session_id="session:test", internal_message_id="m-reply")
    ref_peer = replace(src0.reference, session_id="session:test", internal_message_id="m-peer")
    item = replace(
        item,
        sources=(
            replace(src0, reference=ref_reply),
            replace(src0, reference=ref_peer),
        ),
    )
    artifact = replace(artifact, evidence_items=(item, artifact.evidence_items[1]))
    artifact_dict = json.loads(serialize_answer_artifact(artifact))

    database = tmp_path / "canonical.sqlite3"
    ts_base = 1793000000000  # 2026-10-26T15:33:20+08:00
    with sqlite3.connect(database) as con:
        con.executescript(
            "CREATE TABLE chat_sessions(session_id TEXT PRIMARY KEY, session_name TEXT);"
            "CREATE TABLE users(user_id TEXT PRIMARY KEY, display_name TEXT);"
            "CREATE TABLE messages("
            "internal_message_id TEXT PRIMARY KEY, session_id TEXT, source_message_id TEXT, "
            "timestamp INTEGER, sender_user_id TEXT, sender_name TEXT, sender_nickname TEXT, "
            "sender_group_card TEXT, content_text TEXT, reply_to_source_message_id TEXT);"
        )
        con.execute("INSERT INTO chat_sessions VALUES ('session:test', '测试技术群')")
        con.execute("INSERT INTO users VALUES ('u-bot', 'JoyeBot')")
        # Far reply target sitting 5 messages earlier (outside ±3 window)
        con.execute(
            "INSERT INTO messages VALUES ('m-target','session:test','src-target',?,'u-alice','Alice',NULL,'群友Alice','原问题：模型A好用吗',NULL)",
            (ts_base - 60000,),
        )
        for i in range(1, 5):
            con.execute(
                "INSERT INTO messages VALUES (?, 'session:test', ?, ?, 'u-noise', 'Noise', NULL, NULL, ?, NULL)",
                (f"m-noise-{i}", f"src-noise-{i}", ts_base - 50000 + i * 1000, f"中间噪声 {i}"),
            )
        # Same-millisecond concurrent peer + cited reply
        con.execute(
            "INSERT INTO messages VALUES ('m-peer','session:test','src-peer',?,'u-bot',NULL,NULL,NULL,'机器人同步消息',NULL)",
            (ts_base,),
        )
        con.execute(
            "INSERT INTO messages VALUES ('m-reply','session:test','src-reply',?,'u-bob','Bob','小Bob',NULL,'不好用，容易断连','src-target')",
            (ts_base,),
        )

    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row
    try:
        truth = {"case_id": case.case_id, "version": case.version, "query": case.query, "candidate_facts": []}
        packet = {"case_id": case.case_id, "case_version": case.version, "evidence": []}
        v3_payload = build_review_payload(
            case=case, truth=truth, packet=packet, artifact=artifact_dict, con=con, rubric_version=RUBRIC_VERSION_V3
        )
    finally:
        con.close()

    # Compact answer keeps lossless content_blocks and strips heavy snapshot blobs
    assert v3_payload["answer"]["content_blocks"] == artifact_dict["content_blocks"]
    assert "evidence_items" not in v3_payload["answer"]
    assert v3_payload["answer"]["evidence_links"][0]["source_message_ids"] == ["m-reply", "m-peer"]

    # Deduplicated thread resolves readable time, sender_display, same-ms peer, and far-reply target
    assert len(v3_payload["evidence_threads"]) == 1
    thread = v3_payload["evidence_threads"][0]
    assert thread["session_name"] == "测试技术群"
    by_id = {m["internal_message_id"]: m for m in thread["messages"]}
    assert len(by_id) == len(thread["messages"])  # strictly deduplicated
    assert "m-target" in by_id
    assert by_id["m-target"]["is_reply_target"] is True
    assert by_id["m-target"]["sender_display"] == "群友Alice"
    assert by_id["m-peer"]["sender_display"] == "JoyeBot"
    assert by_id["m-reply"]["sender_display"] == "小Bob"
    assert by_id["m-reply"]["reply_to_internal_message_id"] == "m-target"
    assert by_id["m-reply"]["is_cited"] is True
    assert by_id["m-reply"]["timestamp_iso"].endswith("+08:00")


def test_blind_pairwise_input_parsing_and_position_swap_aggregation(tmp_path):
    assert "answer_a" in PAIRWISE_JUDGE_PROMPT and "answer_b" in PAIRWISE_JUDGE_PROMPT
    case = _case()
    artifact = _artifact()
    item = artifact.evidence_items[0]
    src = item.sources[0]
    ref_a = replace(src.reference, session_id="session:test", internal_message_id="m-a")
    ref_b = replace(src.reference, session_id="session:test", internal_message_id="m-b")
    art_a = json.loads(
        serialize_answer_artifact(
            replace(artifact, evidence_items=(replace(item, sources=(replace(src, reference=ref_a),)), artifact.evidence_items[1]))
        )
    )
    art_b = json.loads(
        serialize_answer_artifact(
            replace(artifact, evidence_items=(replace(item, sources=(replace(src, reference=ref_b),)), artifact.evidence_items[1]))
        )
    )

    database = tmp_path / "canonical.sqlite3"
    with sqlite3.connect(database) as con:
        con.executescript(
            "CREATE TABLE messages(internal_message_id TEXT, session_id TEXT, timestamp INTEGER, "
            "sender_user_id TEXT, content_text TEXT, reply_to_source_message_id TEXT);"
        )
        con.execute("INSERT INTO messages VALUES ('m-a','session:test',1000,'u1','msg A',NULL)")
        con.execute("INSERT INTO messages VALUES ('m-b','session:test',2000,'u2','msg B',NULL)")

    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row
    try:
        pw_input = prepare_pairwise_input(
            case=case,
            truth={"case_id": case.case_id},
            packet={"evidence": []},
            answer_a=art_a,
            answer_b=art_b,
            con=con,
        )
    finally:
        con.close()

    mids = [m["internal_message_id"] for m in pw_input["evidence_threads"][0]["messages"]]
    assert mids == ["m-a", "m-b"]
    assert "run_id" not in json.dumps(pw_input["answer_a"])

    fwd_raw = json.dumps({
        "overall_winner": "B",
        "overall_rationale": "B 覆盖更全且更克制。",
        "axes": {
            "task_satisfaction": {"winner": "B", "reason": "B 补齐了近期体验。"},
            "evidence_grounding": {"winner": "tie", "reason": "硬事实均准确。"},
            "epistemic_calibration": {"winner": "B", "reason": "B 明确标注了个例边界。"},
        },
        "key_differences": ["B 覆盖 10 月新讨论"],
    }, ensure_ascii=False)
    rev_consistent_raw = json.dumps({
        "overall_winner": "A",
        "overall_rationale": "A 覆盖更全且更克制。",
        "axes": {
            "task_satisfaction": {"winner": "A", "reason": "A 补齐了近期体验。"},
            "evidence_grounding": {"winner": "tie", "reason": "硬事实均准确。"},
            "epistemic_calibration": {"winner": "B", "reason": "位置翻转变了。"},
        },
        "key_differences": ["A 覆盖 10 月新讨论"],
    }, ensure_ascii=False)

    fwd = parse_pairwise_judgment(
        fwd_raw, case_id=case.case_id, arm_a="baseline", arm_b="candidate", judge_identity="fixture:pw"
    )
    rev = parse_pairwise_judgment(
        rev_consistent_raw, case_id=case.case_id, arm_a="candidate", arm_b="baseline", judge_identity="fixture:pw"
    )
    agg = aggregate_position_swapped_pairwise(fwd, rev)
    assert agg["overall_winner"] == "candidate"
    assert agg["overall_consistent"] is True
    assert agg["axes"]["task_satisfaction"]["winner"] == "candidate"
    assert agg["axes"]["evidence_grounding"]["winner"] == "tie"
    assert agg["axes"]["epistemic_calibration"]["winner"] == "tie_position_inconsistent"
    assert agg["axes"]["epistemic_calibration"]["consistent"] is False
