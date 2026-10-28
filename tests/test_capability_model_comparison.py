"""Model comparisons must detect changes to fixed experiment conditions."""
import json
from copy import deepcopy

import pytest

from scripts.compare_capability_models import review_conditions
from trivae.evaluation.experiment_manifest import compare_model_experiments


def test_model_comparison_detects_budget_prompt_router_and_protocol_changes(tmp_path):
    base = {
        "status": "completed", "suite": {"suite_id": "s", "version": 1},
        "cases": [{"case_id": "c", "version": 1}], "freeze_id": "f", "snapshot": {},
        "index_state": {}, "judge_version": "j", "repetitions": 1, "git_commit": "abc",
        "python": "3", "openai_agents_version": "1", "router_settings": {"enabled": False},
        "variant": {"variant_id": "a", "provider": "p", "model": "m1", "variant_fingerprint": "x",
                    "prompt_identity": "prompt-1", "available_tools": ["lexical_search"],
                    "budget": {"max_turns": 6}},
        "runtime_settings": {"provider": "p", "model_name": "m1", "base_url": "a",
                             "api_key_configured": True, "max_tool_rounds": 6},
        "runs": [{"run_id": "a", "case": "c@v1"}],
    }
    other = deepcopy(base)
    other["variant"].update(variant_id="b", provider="other", model="m2", variant_fingerprint="y")
    other["runtime_settings"].update(provider="other", model_name="m2", base_url="b")
    other["runs"][0]["run_id"] = "b"
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(base))
    b.write_text(json.dumps(other))
    assert compare_model_experiments(a, b)["comparable"]

    other["variant"]["prompt_identity"] = "changed"
    other["variant"]["budget"]["max_turns"] = 3
    other["runtime_settings"]["protocol"] = "different"
    other["router_settings"]["enabled"] = True
    b.write_text(json.dumps(other))
    result = compare_model_experiments(a, b)
    assert not result["comparable"]
    assert set(result["reasons"]) >= {"variant.prompt_identity differs", "variant.budget differs",
                                      "runtime_settings.protocol differs", "router_settings differs"}

    base["suite"]["suite_id"] = other["suite"]["suite_id"] = "capability-formal"
    a.write_text(json.dumps(base))
    b.write_text(json.dumps(other))
    assert "effective_model_treatment missing" in compare_model_experiments(a, b)["reasons"]


def test_review_comparison_requires_all_completed_runs_and_same_judge(tmp_path):
    runs = [{"run_id": "a", "terminal_status": "completed"}, {"run_id": "b", "terminal_status": "failed"}]
    with pytest.raises(ValueError, match="do not all have"):
        review_conditions(tmp_path, runs)
    review_dir = tmp_path / "review-a"
    review_dir.mkdir()
    (review_dir / "review.json").write_text(json.dumps({"run_id": "a", "reviewer_type": "model_assisted",
                                                         "rubric_version": "v1"}))
    (review_dir / "configuration.json").write_text(json.dumps({"rubric_version": "v1", "model": "judge"}))
    (review_dir / "response.json").write_text(json.dumps({"model": "judge-version"}))
    assert review_conditions(tmp_path, runs)["actual_model"] == "judge-version"
