"""零 Provider 的筛选契约与真实 Application/SDK 首调用截停测试。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message, function_call
from agents.usage import Usage
from openai.types.responses.response_usage import InputTokensDetails

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
                          function_call("get_message_context", {"source_id": "m1-1", "context_after": 20}, call_id="two")],
                  usage=Usage(requests=1, input_tokens=100, output_tokens=20, total_tokens=120,
                              input_tokens_details=InputTokensDetails(cached_tokens=17, cache_write_tokens=0))),
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
            # 工具前终止不能丢掉SDK已经记录的真实usage；两个并行call不得重复累加。
            assert runtime.probe_usage == {"requests": 1, "input_tokens": 100, "output_tokens": 20,
                                           "total_tokens": 120, "cached_input_tokens": 17}
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


def test_historical_import_rejects_failed_candidate_without_provider(tmp_path):
    """明确导入边界拒绝旧失败candidate；不能用更短文本覆盖production baseline。"""
    from scripts.freeze_recorded_prompt_baseline import freeze_recorded_cell
    from tests.test_evaluation import _snapshot

    write_artifact(tmp_path / "result.json", {"variant": "candidate"})
    write_artifact(tmp_path / "initial_contract.json", {"instructions": SYSTEM_PROMPT})
    with pytest.raises(EvaluationContractError, match="production prompt baseline"):
        freeze_recorded_cell(tmp_path, snapshot=_snapshot(), commit="test", policy_tags=("discussion",))


def test_static_prompt_responsibility_mapping_covers_exact_production_wording():
    """L0检查92条mapping与224行实际原文，防止审计脱离当前baseline。"""
    import re
    from pathlib import Path

    root = Path(__file__).parents[1]
    matrix = (root / ".trellis/tasks/10-05-prompt-policy-audit/prompt-responsibility-matrix.md").read_text()
    original = (root / "src/trivae/query/runtime/prompt.py").read_text().splitlines()
    rows = [re.split(r"(?<!\\)\|", line)[1:-1] for line in matrix.splitlines() if re.match(r"\| P\d+ \|", line)]
    assert len(rows) == 92
    covered = set()
    for index, fields in enumerate(rows, 1):
        # 十列均须保留；缺结尾分隔符会丢失Provider预算列，不能让定位测试漏检。
        assert len(fields) == 10
        assert fields[0].strip() == f"P{index:02d}"
        span = fields[2].strip().removeprefix("prompt.py L").split("–")
        start, end = int(span[0]), int(span[-1])
        covered.update(range(start, end + 1))
        wording = "\n".join(original[start - 1 : end]).removeprefix('SYSTEM_PROMPT = """')
        # 精确语义片段可从行中间开始；仍必须属于所报当前源码范围。
        quoted = fields[1].strip().replace("<br>", "\n").replace("\\|", "|")
        assert quoted in wording
        # 声明最小行范围，防止用大段覆盖掩盖错位。
        assert quoted.splitlines()[0] in original[start - 1]
        assert quoted.splitlines()[-1] in original[end - 1]
        assert set(fields[3].strip().split("/")) <= set("ABCDEFG")
        assert all(field.strip() for field in fields)
    assert covered == set(range(7, 231))
    # 候选机械片段必须由相应规则实际引用，不只靠Rule ID名称或总行覆盖。
    import json

    manifest = json.loads(
        (root / ".trellis/tasks/10-05-prompt-policy-audit/research/optimization-candidates.json").read_text()
    )
    quoted_by_rule = {fields[0].strip(): fields[1].strip().replace("<br>", "\n").replace("\\|", "|") for fields in rows}
    preceding = []
    for item in manifest:
        quoted = quoted_by_rule[item["rule"].split(":")[0]]
        # P05基于P03已经删除dense片段的同句；按顺序重建该规则局部原文。
        for removed in preceding:
            quoted = quoted.replace(removed, "")
        assert item["removed"].strip() in quoted
        preceding.append(item["removed"])


def test_cli_does_not_repeat_baseline_or_probe_and_rejects_regression_before_provider(tmp_path, monkeypatch, capsys):
    """收口：candidate+2不能变成whole-suite/paired repeat，明确退步不构造Provider。"""
    from scripts import run_prompt_screening as cli

    case = _case()
    case_path = tmp_path / "case.json"
    case.to_json(case_path)
    prior = tmp_path / "prior.json"
    write_artifact(prior, {"kind": "candidate_screen", "conditions": {"case": case.identity}})
    monkeypatch.setattr(cli, "load_settings", lambda: pytest.fail("provider settings must not be loaded"))
    common = ["--case", str(case_path), "--database", str(tmp_path / "canonical.sqlite3"),
        "--output", str(tmp_path / "output"), "--candidate-prompt", str(tmp_path / "prompt.txt"),
        "--repeat-on-failure", str(prior), "--candidate-extra", "2", "--max-provider-calls", "2"]
    args = cli.parser().parse_args(["--mode", "full-gate", "--review", "borderline",
                                   "--repeat-reason", "provider_randomness", *common])
    with pytest.raises(EvaluationContractError, match="repeat-on-failure"):
        asyncio.run(cli.execute(args))
    args = cli.parser().parse_args(["--mode", "candidate-only", "--baseline-dir", str(tmp_path / "baseline"),
                                   "--review", "regression", *common])
    asyncio.run(cli.execute(args))
    assert json.loads(capsys.readouterr().out) == {"decision": "rejected", "provider_calls": 0}


def test_frozen_baseline_drift_names_changed_conditions_without_dumping_values():
    """新SDK与旧冻结记录的真实差异可定位，仍拒绝复用，不输出完整请求或值。"""
    original = {**conditions(), "tool_contract": [{"name": "execute_sql", "schema": {"minimum": 1}}]}
    frozen = {"kind": "frozen_baseline", "prompt": SYSTEM_PROMPT, "commit": "baseline",
              "conditions": original, "run": {"run_id": "frozen"}, "trace": {"trace_id": "trace"}}
    changed = {**original, "tool_contract": [{"name": "execute_sql", "schema": {"minimum": 0}}], "tool_budget": 4}
    with pytest.raises(EvaluationContractError) as error:
        verify_frozen_baseline(frozen, changed, SYSTEM_PROMPT)
    assert str(error.value) == "frozen execution conditions drifted (tool_budget, tool_contract); refusing provider call"
    assert "minimum" not in str(error.value)
    # 完全相同的原条件仍能复用，诊断改进不能偷偷放宽或收紧相等条件。
    verify_frozen_baseline(frozen, original, SYSTEM_PROMPT)
