"""最终工程实验的规模、生产边界、预检失败和实际请求隔离回归。"""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation/planner-p1-stability"))
from run_engineering_closure import (  # noqa: E402
    CASE_IDS,
    ProductionPlanner,
    execute,
    schedule,
    serialize_planner,
    verify_initial_requests,
)

from trivae.capabilities import ExecutionScope  # noqa: E402
from trivae.config.settings import ModelSettings  # noqa: E402
from trivae.query.contracts import ExecutionOverride, QueryRequest  # noqa: E402
from trivae.query.orchestrator import QueryOrchestrator  # noqa: E402
from trivae.query.planner import SoftPlanner  # noqa: E402
from trivae.query.router import RuleRouter  # noqa: E402
from trivae.query.runtime.contracts import RuntimeResult  # noqa: E402
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter  # noqa: E402


def test_final_schedule_is_exactly_sixteen_counterbalanced_without_effort_treatments():
    """不让历史 low/none 或 repeat 研究设置污染本轮。"""
    order = schedule(20261004)
    assert len(order) == 16 and order == schedule(20261004)
    assert {(r["case_id"], r["treatment"]) for r in order} == {(c, t) for c in CASE_IDS for t in ("standard", "planned")}
    assert all(r["attempt"] == 1 for r in order)
    for index in range(0, 16, 2):
        assert order[index]["case_id"] == order[index + 1]["case_id"]
        assert order[index]["treatment"] != order[index + 1]["treatment"]
    assert sum(order[i]["treatment"] == "standard" for i in range(0, 16, 2)) == 4


def test_preflight_uses_current_production_planner_method_without_network():
    """SDK 真实 serializer 的 none 档位，与 Router/Runtime low 分离。"""
    async def check():
        runtime = OpenAIAgentsRuntimeAdapter(settings=ModelSettings(api_key="provider-free", base_url="https://invalid.test",
            provider="deepseek", model_name="deepseek-flash", max_turns=8))
        try:
            body = await serialize_planner(runtime, "fixed P1 prompt")
            assert body["reasoning_effort"] == "none"
            assert body["max_tokens"] == 2048
            assert runtime.completion_request_projection()["reasoning_effort"] == "low"
            assert runtime._resolved_reasoning_effort() == "low"
            assert runtime._provider_client.max_retries == 0
        finally:
            await runtime.aclose()
    asyncio.run(check())


def test_actual_request_comparison_only_allows_exact_production_guidance():
    """剥离 guidance 不能隐藏 schema、预算或 Query 漂移。"""
    standard = {"messages": [{"role": "system", "content": "production"}, {"role": "user", "content": "query"}],
        "max_tokens": 16384, "tools": [{"name": "get_message_context"}], "reasoning_effort": "low"}
    planned = deepcopy(standard)
    planned["messages"][0]["content"] += "\nsoft guidance"
    verify_initial_requests(standard, planned, "soft guidance")
    verify_initial_requests(standard, standard, None)
    planned["max_tokens"] += 1
    with pytest.raises(ValueError, match="beyond rendered"):
        verify_initial_requests(standard, planned, "soft guidance")


def test_forced_paths_share_runtime_and_call_planner_zero_or_once():
    """真实 Orchestrator 控制介入，Planner wrapper 只观测 soft guidance。"""
    async def check():
        raw = json.dumps({"version": 1, "title": "证据调查", "intent": "evidence",
            "steps": [{"goal": "确认来源", "suggested_tools": [], "evidence_needed": ["直接消息"]}],
            "success_criteria": ["来源支持结论"]})
        planner = ProductionPlanner(SoftPlanner(lambda _: raw))

        class Runtime:
            """离线替身只记录生产编排输入，不执行 Provider。"""
            def __init__(self):
                self.requests = []

            async def run(self, request):
                self.requests.append(request)
                return RuntimeResult(final_answer=None, provider="test", model="test", termination="failed", tool_calls=())

        runtime = Runtime()
        orchestrator = QueryOrchestrator(runtime, RuleRouter(), planner, capability_names=())
        for treatment, expected in (("standard", 0), ("planned", 1)):
            request = QueryRequest(query="确认来源", available_capabilities=(), scope=ExecutionScope(),
                execution_override=ExecutionOverride(forced_route=f"{treatment}_execution"))
            await orchestrator.run(request)
            assert planner.calls == expected
        assert len(runtime.requests) == 2
        assert runtime.requests[0].plan_guidance is None
        assert runtime.requests[1].plan_guidance
    asyncio.run(check())


def test_configuration_preflight_failure_is_saved_with_zero_calls_and_no_attempts(tmp_path, monkeypatch):
    """失败目录保留；既不创建正式 attempt，也不重复付费请求。"""
    import run_engineering_closure as runner

    def fail():
        raise ValueError("reproduced configuration failure")
    monkeypatch.setattr(runner, "load_environment_file", fail)
    output = tmp_path / "preflight"
    with pytest.raises(ValueError, match="configuration failure"):
        asyncio.run(execute(output, tmp_path / "db", 20261004, True))
    failure = json.loads((output / "failure.json").read_text())
    assert failure["formal_attempts"] == failure["provider_calls"] == 0
    assert not (output / "attempts.jsonl").exists()
    with pytest.raises(FileExistsError):
        asyncio.run(execute(output, tmp_path / "db", 20261004, True))
