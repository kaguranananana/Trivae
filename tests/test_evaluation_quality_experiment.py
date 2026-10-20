"""实验脚本零成本回归：预算持久化、条件门禁和真实 Application 装配。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import httpx2 as httpx
import pytest

from scripts.evaluation_quality_experiment import (
    BudgetExhausted,
    HttpLedger,
    execute,
    parser,
    verify_conditions,
)
from trivae.bootstrap.application import create_application
from trivae.capabilities.contracts import ExecutionScope
from trivae.config.settings import ModelSettings
from trivae.evaluation.contracts import (
    CaseProvenance,
    DatasetSnapshot,
    EvaluationCaseBundle,
    EvaluationContractError,
    utc_now,
)
from trivae.query.runtime.contracts import RuntimeEvent, RuntimeResult
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter


def test_ledger_debits_before_send_and_preserves_failures(tmp_path: Path) -> None:
    """失败和中断都保留 debit，重开脚本不重置总量。"""
    path = tmp_path / "http.jsonl"
    ledger = HttpLedger(path, 2)
    number = ledger.debit(arm="baseline", case_id="case-1", output="private")
    assert HttpLedger(path, 2).count == 1
    ledger.finish(number, error_type="ReadError")
    HttpLedger(path, 2).debit(arm="candidate", case_id="case-1", output="private")
    with pytest.raises(BudgetExhausted):
        ledger.debit(arm="candidate", case_id="case-2", output="private")
    assert ledger.count == 2
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["budget", "started", "finished", "started"]
    with pytest.raises(EvaluationContractError, match="differs"):
        HttpLedger(path, 3)
    with pytest.raises(EvaluationContractError, match="120"):
        HttpLedger(tmp_path / "enlarged.jsonl", 121)


def test_condition_gate_only_excludes_arm_and_commit() -> None:
    """失败 Baseline 也参与同条件比较；不因为失败替换 GT。"""
    baseline = {"arm": "baseline", "commit": "before", "case": {"version": 1}, "prompt": "frozen"}
    verify_conditions(baseline, {**baseline, "arm": "candidate", "commit": "after"})
    with pytest.raises(EvaluationContractError, match="prompt"):
        verify_conditions(baseline, {**baseline, "prompt": "changed"})
    with pytest.raises(EvaluationContractError, match="case"):
        verify_conditions(baseline, {**baseline, "case": {"version": 2}})


def test_prompt_treatment_requires_explicit_opt_in_and_keeps_full_conditions() -> None:
    """默认拒绝 Prompt 漂移；显式 treatment 仅比较移除基础前缀后的相同后缀。"""
    baseline = {"arm": "baseline", "commit": "before", "prompt": "old base\n",
                "initial_instructions": "old base\nTool-round budget: 4 remaining.",
                "budget": 4, "tools": ["lexical_search"], "case": {"version": 1}}
    candidate = {**baseline, "arm": "candidate", "commit": "after", "prompt": "new base\n",
                 "initial_instructions": "new base\nTool-round budget: 4 remaining."}
    with pytest.raises(EvaluationContractError, match="prompt"):
        verify_conditions(baseline, candidate)
    difference = verify_conditions(baseline, candidate, prompt_treatment=True)
    assert "--- baseline/prompt" in difference
    assert "+++ candidate/prompt" in difference
    assert "-old base" in difference and "+new base" in difference
    # 条件原文不能被比较函数剥离或改写，方便复核真实输入。
    assert baseline["prompt"] == "old base\n"
    assert candidate["initial_instructions"] == "new base\nTool-round budget: 4 remaining."


@pytest.mark.parametrize(("field", "changed"), (
    ("initial_instructions", "new base\nTool-round budget: 5 remaining."),
    ("budget", 5),
    ("tools", ["semantic_search"]),
    ("case", {"version": 2}),
))
def test_prompt_treatment_rejects_other_condition_drift(field: str, changed: object) -> None:
    """基础 Prompt 变更不能掩盖动态后缀、预算、工具或 Case 漂移。"""
    baseline = {"prompt": "old base\n", "initial_instructions": "old base\nTool-round budget: 4 remaining.",
                "budget": 4, "tools": ["lexical_search"], "case": {"version": 1}}
    candidate = {**baseline, "prompt": "new base\n",
                 "initial_instructions": "new base\nTool-round budget: 4 remaining.", field: changed}
    with pytest.raises(EvaluationContractError, match=field):
        verify_conditions(baseline, candidate, prompt_treatment=True)


@pytest.mark.parametrize("side", ("baseline", "candidate"))
def test_prompt_treatment_requires_each_own_prefix(side: str) -> None:
    """两侧 instructions 都必须以各自记录的基础 Prompt 开头。"""
    baseline = {"prompt": "old base", "initial_instructions": "old base suffix"}
    candidate = {"prompt": "new base", "initial_instructions": "new base suffix"}
    target = baseline if side == "baseline" else candidate
    target["initial_instructions"] = "different prefix suffix"
    with pytest.raises(EvaluationContractError, match="own prompt"):
        verify_conditions(baseline, candidate, prompt_treatment=True)


@pytest.mark.parametrize("send_mode", ("none", "mock_http", "mock_error", "mock_budget"))
def test_real_application_writes_private_evidence_without_provider(tmp_path: Path, send_mode: str) -> None:
    """真实 Runner/Query/Trace 装配，只将模型执行替换为确定性输出。"""
    database = tmp_path / "canonical.sqlite3"
    semantic = tmp_path / "canonical.semantic.sqlite3"
    with create_application(database, semantic_index_path=semantic):
        pass
    snapshot = DatasetSnapshot.from_database(database)
    case = EvaluationCaseBundle(
        case_id="quality-0", version=1, suite_tags=("unit-test",), query="无结果时明确说明", dataset_snapshot=snapshot,
        data_access_scope=ExecutionScope(), uncertainty_constraints=("不得编造",),
        provenance=CaseProvenance("unit-test", "zero-cost regression", utc_now()),
    )
    cases = tmp_path / "cases"
    cases.mkdir()
    for number in range(6):
        replace(case, case_id=f"quality-{number}").to_json(cases / f"quality-{number}.json")
    settings = ModelSettings(api_key="unit-test-secret", provider="deepseek", model_name="deepseek-flash",
                             base_url="https://api.deepseek.com", max_turns=8)

    async def completed(self, request):
        # 公共 RuntimeResult 不携带 SDK raw result 或 hidden reasoning。
        return RuntimeResult(final_answer="未找到相关消息。", provider="deepseek", model="deepseek-flash",
                             termination="completed", tool_calls=(), usage={"total_tokens": 9})

    async def completed_stream(self, request, abort_event=None):
        if send_mode != "none":
            def transport(provider_request):
                if send_mode == "mock_error":
                    raise httpx.ReadError("simulated transport failure", request=provider_request)
                return httpx.Response(200, json={"mock": True})

            # MockTransport 仍经过被补丁包裹的实际发送边界，但不会访问外网。
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                await client.post("https://api.deepseek.com/v1/chat/completions")
        result = await completed(self, request)
        yield RuntimeEvent("completed", "deepseek", "deepseek-flash", 1, result=result)

    output = tmp_path / "baseline"
    arguments = ["--database", str(database), "--semantic-index", str(semantic), "--cases-dir", str(cases),
                 "--output", str(output), "--arm", "baseline", "--env-file", str(tmp_path / "missing.env")]
    for number in range(6):
        arguments.extend(["--case", f"quality-{number}"])
    if send_mode == "mock_budget":
        arguments.extend(["--max-http-requests", "2"])
    # 禁止真实网络；任何意外 Provider 调用立即使测试失败。
    with (
        patch("scripts.evaluation_quality_experiment.load_settings", return_value=settings),
        patch("scripts.evaluation_quality_experiment.load_environment_file"),
        patch("scripts.evaluation_quality_experiment.subprocess.run") as ignored,
        patch("scripts.evaluation_quality_experiment.subprocess.check_output", return_value="test-commit\n"),
        patch.object(OpenAIAgentsRuntimeAdapter, "run", completed),
        patch.object(OpenAIAgentsRuntimeAdapter, "stream", completed_stream),
        patch("httpx2.AsyncHTTPTransport.handle_async_request", side_effect=AssertionError("network forbidden")),
    ):
        ignored.return_value.returncode = 0
        asyncio.run(execute(parser().parse_args(arguments)))
    summary = json.loads((output / "summary.json").read_text())
    assert summary["record_count"] == 6
    expected_requests = {"none": 0, "mock_budget": 2}.get(send_mode, 6)
    assert summary["global_http_requests"] == expected_requests
    if send_mode == "mock_budget":
        assert [row["status"] for row in summary["records"][2:]] == ["not_run_budget"] * 4
    record = json.loads((output / "quality-0.json").read_text())
    if send_mode == "mock_error":
        assert record["status"] == "exception"
        assert record["error_type"] == "ReadError"
        rows = [json.loads(line) for line in (tmp_path / "http-budget.jsonl").read_text().splitlines()]
        assert sum(row["event"] == "started" for row in rows) == 6
        assert sum(row.get("error_type") == "ReadError" for row in rows) == 6
        return
    assert record["status"] == "completed"
    assert record["run"]["query_result"]["is_successful"] is True
    assert record["result"]["runtime_result"]["usage"] == {"total_tokens": 9}
    assert "artifact_capture_error" not in record
    assert (output / "traces" / "quality-0.json").is_file()
    assert (output / "traces" / "quality-0.log").is_file()
    assert (output / "cases" / "quality-0.json").is_file()
    conditions = json.loads((output / "conditions" / "quality-0.json").read_text())
    assert len(conditions["tools"]) == 7
    assert conditions["sdk_max_retries"] == 0
    assert "unit-test-secret" not in (output / "conditions" / "quality-0.json").read_text()
