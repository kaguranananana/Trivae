"""冻结 Plan 原样注入、固定四次顺序和真实生产输入隔离的无 Provider 检查。"""

from __future__ import annotations

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation/planner-p1-stability"))
from run_frozen_plan_replay import (  # noqa: E402
    CASE_ID,
    SOURCE,
    FrozenPlanner,
    agent_projection,
    load_plan,
    replay_order,
    snapshot_content,
    without_guidance,
)

from trivae.capabilities import CapabilityRegistry, ExecutionScope  # noqa: E402
from trivae.config.settings import ModelSettings  # noqa: E402
from trivae.query.contracts import ExecutionOverride, QueryRequest  # noqa: E402
from trivae.query.orchestrator import QueryOrchestrator  # noqa: E402
from trivae.query.planner import render_plan_guidance  # noqa: E402
from trivae.query.router import RuleRouter  # noqa: E402
from trivae.query.runtime.contracts import RuntimeResult  # noqa: E402
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter  # noqa: E402

TOOLS = tuple(json.loads((SOURCE / "variants.json").read_text())["low"]["available_tools"])


def test_replay_order_has_exactly_two_runs_per_plan_and_reverses_second_pair():
    """有界四次、每侧两次，第二块反转第一块的执行顺序。"""
    rows = replay_order(20261003)
    assert rows == replay_order(20261003)
    assert len(rows) == 4
    assert {(r["treatment"], r["attempt"]) for r in rows} == {(t, a) for t in ("low", "none") for a in (1, 2)}
    assert [r["treatment"] for r in rows[:2]] == [r["treatment"] for r in rows[2:]][::-1]


def test_source_plan_uses_production_parser_without_changing_original_guidance():
    """真实保存的两个 Plan 再读取后，renderer 输出与原请求末尾完全一致。"""
    for treatment in ("low", "none"):
        plan = load_plan(SOURCE, treatment, TOOLS)
        original = json.loads((SOURCE / "raw" / f"{CASE_ID}-{treatment}-a1.json").read_text())
        body = original["provider_requests"][1]["serialized_request"]
        assert body["messages"][0]["content"].endswith("\n" + render_plan_guidance(plan))


def test_failed_source_plan_is_rejected_before_any_runtime_attempt(tmp_path):
    """不把历史失败或 skip 状态伪装成有效 Plan treatment。"""
    (tmp_path / "raw").mkdir()
    row = json.loads((SOURCE / "raw" / f"{CASE_ID}-low-a1.json").read_text())
    row["planner"]["failure"] = {"code": "invalid_output"}
    (tmp_path / "raw" / f"{CASE_ID}-low-a1.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="successful Plan"):
        load_plan(tmp_path, "low", TOOLS)


def test_initial_http_body_normalization_preserves_all_non_guidance_fields():
    """实际序列化请求只有 guidance 不同；输入或参数污染不可被剥离逻辑掩盖。"""
    bodies = []
    for treatment in ("low", "none"):
        row = json.loads((SOURCE / "raw" / f"{CASE_ID}-{treatment}-a1.json").read_text())
        body = row["provider_requests"][1]["serialized_request"]
        guidance = render_plan_guidance(load_plan(SOURCE, treatment, TOOLS))
        bodies.append(without_guidance(body, guidance))
        changed = deepcopy(body)
        changed["max_tokens"] += 1
        assert without_guidance(changed, guidance) != bodies[-1]
        with pytest.raises(ValueError, match="exact frozen guidance"):
            without_guidance(body, guidance + " changed")
    assert bodies[0] == bodies[1]


def test_frozen_planner_passes_through_production_orchestrator_without_provider():
    """生产 Orchestrator 渲染 guidance；冻结注入不创建假的 Provider observation。"""
    async def check():
        plans = {t: load_plan(SOURCE, t, TOOLS) for t in ("low", "none")}
        planner = FrozenPlanner(plans)

        class RecordingRuntime:
            """只在无 Provider 测试中观测真实 Orchestrator 编译的请求。"""
            def __init__(self):
                self.requests = []

            async def run(self, request):
                self.requests.append(request)
                return RuntimeResult(final_answer=None, provider="test", model="test", termination="failed", tool_calls=())

        runtime = RecordingRuntime()
        orchestrator = QueryOrchestrator(runtime, RuleRouter(), planner, capability_names=TOOLS)
        request = QueryRequest(query="archify 项目最近发展怎么样？star 数有被提到过吗？", scope=ExecutionScope(),
            available_capabilities=TOOLS, execution_override=ExecutionOverride(forced_route="planned_execution"))
        for treatment in ("low", "none"):
            planner.treatment = treatment
            result = await orchestrator.run(request)
            assert result.plan == plans[treatment]
            assert runtime.requests[-1].plan_guidance == render_plan_guidance(plans[treatment])
        assert planner.calls == 2
        assert (await planner.plan(request.to_context())).observation is None
    asyncio.run(check())


def test_agent_builder_has_same_input_schema_and_settings_outside_guidance():
    """直接核对生产 builder，不伪造正式 E2E。"""
    async def check():
        runtime = OpenAIAgentsRuntimeAdapter(settings=ModelSettings(api_key="provider-free", base_url="https://invalid.test",
            provider="deepseek", model_name="deepseek-flash", max_turns=8), capability_registry=CapabilityRegistry())
        try:
            # 无能力注册的 builder 测试仍使用同一生产 system 和 ModelSettings。
            request = QueryRequest(query="archify", scope=ExecutionScope(), available_capabilities=())
            projections = []
            for t in ("low", "none"):
                plan = load_plan(SOURCE, t, TOOLS)
                projection = agent_projection(runtime, request, plan)
                suffix = "\n" + render_plan_guidance(plan)
                projection["instructions"] = projection["instructions"][:-len(suffix)]
                projections.append(projection)
            assert projections[0] == projections[1]
            # SDK 的正式 JSON 包含其它 nullable 字段；effort 是需要固定的执行语义。
            assert projections[0]["model_settings"]["reasoning"]["effort"] == "low"
            assert runtime._provider_client.max_retries == 0
        finally:
            await runtime.aclose()
    asyncio.run(check())


def test_snapshot_materialization_timestamp_does_not_hide_actual_data_drift():
    """观测时间可变化，消息数或任何其它快照字段变化必须仍被检查发现。"""
    original = json.loads((SOURCE / "manifest.json").read_text())["snapshot"]
    changed = deepcopy(original)
    changed["created_at"] = "2026-10-02T08:00:00+00:00"
    assert snapshot_content(changed) == snapshot_content(original)
    changed["message_count"] += 1
    assert snapshot_content(changed) != snapshot_content(original)
