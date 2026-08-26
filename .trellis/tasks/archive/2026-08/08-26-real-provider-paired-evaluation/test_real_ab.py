"""验证真实 Provider runner 的预算解析与 timeout 失败边界。"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

_RUNNER_PATH = Path(__file__).with_name("real_ab.py")
_RUNNER_SPEC = importlib.util.spec_from_file_location("trivae_real_ab_runner_test", _RUNNER_PATH)
if _RUNNER_SPEC is None or _RUNNER_SPEC.loader is None:
    raise RuntimeError("cannot load real Provider runner for task-local tests")
_runner = importlib.util.module_from_spec(_RUNNER_SPEC)
sys.modules[_RUNNER_SPEC.name] = _runner
_RUNNER_SPEC.loader.exec_module(_runner)


def test_budget_checker_accepts_fixed_16k_snapshot() -> None:
    """fixed snapshot 不应因为没有 context window 而被 dynamic 校验误判。"""

    snapshot = {
        "budget_mode": "fixed",
        "context_window_tokens": None,
        "context_window_source": "not_used",
        "effective_per_call_tool_result_budget": 16_000,
        "per_call_tool_result_ceiling": 16_000,
    }

    assert _runner._budget_resolution_status("fixed-16k", [snapshot]) == "passed"


def test_budget_checker_accepts_dynamic_pool_after_consumption() -> None:
    """run pool 消耗后 effective budget 变小仍属于合法 dynamic resolution。"""

    snapshot = {
        "budget_mode": "dynamic",
        "context_window_tokens": 1_000_000,
        "context_window_source": "verified_model_registry",
        "effective_per_call_tool_result_budget": 64_000,
        "per_call_tool_result_ceiling": 128_000,
        "run_tool_evidence_budget": 128_000,
    }

    assert _runner._budget_resolution_status("dynamic-run-128k", [snapshot]) == "passed"


def test_cell_timeout_is_not_quality_eligible() -> None:
    """OS worker timeout 必须产生显式失败行，而不是伪造 completed 结果。"""

    timeout = subprocess.TimeoutExpired(["worker"], 0.1)
    with patch.object(_runner.subprocess, "run", side_effect=timeout):
        row = _runner._run_cell_in_worker(
            "fixed-16k",
            "github_skills_resources",
            1,
            {},
            Path("/tmp/trivae-real-paired-test-quality"),
            0.1,
            False,
        )

    assert row["status"] == "cell_timeout"
    assert row["quality_eligible"] is False
    assert row["request_id"] == "1m-paired-v2-fixed-16k-github_skills_resources-r1"
