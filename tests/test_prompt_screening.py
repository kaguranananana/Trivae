"""零 Provider 的筛选契约与真实 Application/SDK 首调用截停测试。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call

from tests.test_evaluation import _case
from trivae.bootstrap.application import create_application
from trivae.evaluation.contracts import EvaluationContractError
from trivae.evaluation.prompt_screening import (
    ProviderCallBudget,
    ScreeningRuntime,
    candidate_repeat_count,
    read_artifact,
    screening_conditions,
    select_policy_cases,
    verify_frozen_baseline,
    write_artifact,
)
from trivae.query.contracts import ExecutionOverride, QueryRequest
from trivae.query.runtime.prompt import SYSTEM_PROMPT


def conditions():
    """用现有 versioned case contract 构造稳定实验条件。"""
    return screening_conditions(_case(), provider="injected", model="test", settings={},
                                tool_budget=3, tools=("lexical_search",))


def test_frozen_baseline_reuses_exact_conditions_and_rejects_drift_before_query(tmp_path):
    """完整原文相等，无需新摘要算法；错误 baseline 在执行前拒绝。"""
    frozen = {"kind": "frozen_baseline", "prompt": SYSTEM_PROMPT, "commit": "baseline",
              "conditions": conditions(), "run": {"run_id": "frozen"}, "trace": {"trace_id": "trace"}}
    path = tmp_path / "baseline.json"
    write_artifact(path, frozen)
    verify_frozen_baseline(read_artifact(path), conditions(), SYSTEM_PROMPT)
    for key, value in (("query", "different"), ("scope", {}), ("model", "other"),
                       ("snapshot", {}), ("tool_budget", 4), ("route", "planned")):
        with pytest.raises(EvaluationContractError, match="drifted"):
            verify_frozen_baseline(frozen, {**conditions(), key: value}, SYSTEM_PROMPT)
    for override in ({"prompt": "old failed candidate"}, {"kind": "candidate_screen"}, {"trace": None}):
        with pytest.raises(EvaluationContractError):
            verify_frozen_baseline({**frozen, **override}, conditions(), SYSTEM_PROMPT)
    with pytest.raises(FileExistsError):
        write_artifact(path, frozen)


def test_policy_selection_has_no_implicit_full_suite():
    """复用 suite_tags，只选被修改的 policy，空选择显式失败。"""
    case = replace(_case(), suite_tags=("discussion", "negative"))
    unrelated = replace(_case(case_id="other"), suite_tags=("inventory",))
    assert select_policy_cases((case, unrelated), "discussion") == (case,)
    with pytest.raises(EvaluationContractError, match="no cases"):
        select_policy_cases((case,), "temporal")
    with pytest.raises(EvaluationContractError, match="duplicate"):
        select_policy_cases((case, case), "discussion")


def test_repeats_are_single_case_explicit_and_regression_stops():
    """明确质量退步不追加；borderline 才允许针对该 case 再跑两次。"""
    assert candidate_repeat_count("regression", 2, "provider_randomness") == 0
    assert candidate_repeat_count("borderline", 2, "provider_randomness") == 2
    assert candidate_repeat_count("pending", 0, None) == 0
    with pytest.raises(EvaluationContractError):
        candidate_repeat_count("pending", 2, None)


def test_provider_budget_blocks_before_send_and_keeps_only_request_body():
    """HTTP hook 覆盖每次真实 attempt；0 预算不允许发送任何请求。"""
    request = SimpleNamespace(content=b'{"model":"test","messages":[]}', headers={"Authorization": "secret"})

    async def check():
        budget = ProviderCallBudget(1)
        await budget.before_request(request)
        assert budget.requests == [{"model": "test", "messages": []}]
        with pytest.raises(EvaluationContractError, match="exhausted"):
            await budget.before_request(request)
        with pytest.raises(EvaluationContractError):
            await ProviderCallBudget(0).before_request(request)
        assert len(budget.requests) == 1
    asyncio.run(check())


def test_first_tool_probe_uses_application_and_executes_no_tool_or_second_model_turn(tmp_path):
    """同一生产 query/SDK loop；多个首轮 tool call 均拦截，不跑后续模型或 Host。"""
    model = ScriptedModel([
        ModelStep(output=[function_call("lexical_search", {"keyword": "Agent", "limit": 5}, call_id="one"),
                          function_call("get_message_context", {"source_id": "m1-1", "context_after": 20}, call_id="two")]),
        ModelStep(output=[assistant_message("should never run")]),
    ])
    runtime = ScreeningRuntime(model=model, first_tool=True)
    application = create_application(tmp_path / "probe.sqlite3", agent_runtime=runtime)
    runtime.capability_registry = application.capability_registry

    async def check():
        try:
            result = await application.query(QueryRequest("请核对后续推荐", _case().data_access_scope,
                trace_profile="debug", available_capabilities=("lexical_search", "get_message_context"),
                execution_override=ExecutionOverride(forced_route="standard_execution")))
            assert result.runtime_result.termination == "failed"
            assert result.runtime_result.error.exception_type == "FirstToolProbeStop"
            assert result.runtime_result.tool_calls == ()
            assert result.runtime_result.tool_results == ()
            assert [call["name"] for call in runtime.probe_calls] == ["lexical_search", "get_message_context"]
            assert runtime.probe_calls[1]["arguments"]["context_after"] == 20
            trace = application.read_trace(result.trace_id)
            assert sum(item.operation == "model.turn" and item.phase == "started" for item in trace.timeline) == 1
            assert not any(item.operation == "tool.call.started" for item in trace.timeline)
        finally:
            await application.aclose()
    asyncio.run(check())


def test_candidate_injection_preserves_dynamic_suffix_and_production_prompt(tmp_path):
    """候选只替换 Base，原始 production 常量和动态预算保持不变。"""
    model = ScriptedModel([ModelStep(output=[assistant_message(json.dumps({"claims": []}))])])
    runtime = ScreeningRuntime(model=model, prompt="test candidate")
    application = create_application(tmp_path / "injection.sqlite3", agent_runtime=runtime)
    runtime.capability_registry = application.capability_registry
    from trivae.query.runtime.openai_adapter import _RunState
    request = QueryRequest("test", _case().data_access_scope).to_runtime_request()
    try:
        agent = runtime._build_agent(request, runtime._build_context(request), _RunState("injected", "test"))
        assert agent.instructions(None, agent).startswith("test candidate\nTool-round budget: 0 consumed, 3 remaining")
        assert SYSTEM_PROMPT.startswith("You answer the user's question")
    finally:
        application.close()


def test_cli_freeze_then_candidate_only_runs_candidate_once_and_builds_comparison(tmp_path, monkeypatch):
    """真实 Runner/Application freeze 后只跑候选；无重付 baseline、无 semantic 自动放行。"""
    from scripts import run_prompt_screening as cli

    database = tmp_path / "canonical.sqlite3"
    app = create_application(database)
    try:
        case = replace(_case(), dataset_snapshot=app.materialize_evaluation_snapshot(), reference_findings=())
    finally:
        app.close()
    case_path = tmp_path / "case.json"
    case.to_json(case_path)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text(SYSTEM_PROMPT)
    models = []
    settings = SimpleNamespace(provider="injected", model_name="test", to_safe_dict=lambda: {})
    monkeypatch.setattr(cli, "load_environment_file", lambda _: None)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    def injected_runtime(**kwargs):
        # 同一正式 runtime 子类，仅 Provider 端口注入 ScriptedModel，全部执行语义保持。
        model = ScriptedModel([ModelStep(output=[assistant_message(json.dumps({"claims": [{
            "text": "fixture answer", "finding": "fixture", "criterion": "no tool used",
            "sufficiency": "insufficient", "sources": [], "limitations": [],
        }], "limitations": []}))])])
        models.append(model)
        runtime = ScreeningRuntime(model=model, provider_name="injected", model_name="test",
                                   first_tool=kwargs["first_tool"])
        runtime._provider_client = SimpleNamespace(_client=SimpleNamespace(event_hooks={}), close=_async_noop)
        return runtime
    monkeypatch.setattr(cli, "ScreeningRuntime", injected_runtime)
    common = ["--case", str(case_path), "--database", str(database), "--max-provider-calls", "2"]
    frozen_dir = tmp_path / "frozen"
    args = cli.parser().parse_args(["--mode", "freeze-baseline", "--output", str(frozen_dir), *common])
    asyncio.run(cli.execute(args))
    output = tmp_path / "candidate"
    args = cli.parser().parse_args(["--mode", "candidate-only", "--baseline-dir", str(frozen_dir),
        "--candidate-prompt", str(prompt_path), "--output", str(output), *common])
    asyncio.run(cli.execute(args))
    assert len(models) == 2
    assert len(list(output.glob("*-candidate-*.json"))) == 1
    assert not list(output.glob("*-baseline-*.json"))
    comparison = read_artifact(output / f"{case.case_id}-comparison-0.json")
    assert comparison["status"] == "pending_review"
    assert len(comparison["baseline_run_ids"]) == len(comparison["candidate_run_ids"]) == 1


async def _async_noop():
    """测试客户端无资源；关闭接口与 AsyncOpenAI 保持相同 await 形态。"""
