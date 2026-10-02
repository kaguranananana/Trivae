"""Judge 失败透明性：输入读取失败不得变成低分，原始错误必须可定位。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import OpenAIError

from trivae.capabilities.contracts import ExecutionScope, ToolEnvelope, ToolError
from trivae.config.settings import ModelSettings
from trivae.evaluation.benchmark.judge import LLMClaimJudge
from trivae.evaluation.benchmark.orchestrator import judge_records
from trivae.evaluation.contracts import EvaluationContractError


@pytest.fixture
def settings():
    """隔离真实 provider，所有测试不发起网络请求。"""
    return ModelSettings(api_key="test", base_url="http://localhost", provider="deepseek", model_name="test", max_turns=8)


def _application():
    """提供最小已有 Run 投影，检验 judge 入口的错误处理。"""
    app = MagicMock()
    app.read_evaluation_run.return_value = SimpleNamespace(query_result={
        "content_blocks": [{"block_id": "b1", "text": "事实"}],
        "citation_bindings": [],
        "evidence_sources": {"sources": [{"message_ids": ["m1"]}]},
    })
    app.invoke_tool.return_value = ToolEnvelope(
        status="error", data=None, meta={}, error=ToolError(code="SOURCE_MISSING", message="source m1 was removed"),
    )
    return app


def _run(app, settings, output: Path):
    case = SimpleNamespace(data_access_scope=ExecutionScope())
    with patch("trivae.evaluation.benchmark.orchestrator.load_cases_dir", return_value={"c1": case}):
        return judge_records(
            application=app, settings=settings, output_path=output, cases_dir=output.parent,
            records=[{"run_id": "r1", "case_id": "c1", "variant_id": "D"}],
        )


def test_evidence_error_prevents_judge_and_preserves_reason(tmp_path, settings):
    """真实 Tool error 应产生 judge_failed，而不是把空证据交给模型评分。"""
    output = tmp_path / "judgments.json"
    with patch.object(LLMClaimJudge, "judge", new_callable=AsyncMock) as judge:
        result = _run(_application(), settings, output)
    judge.assert_not_awaited()
    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert result["judged"] == 0
    assert "SOURCE_MISSING: source m1 was removed" in json.loads(output.read_text())[0]["error"]


def test_provider_error_is_recorded_in_failed_item(tmp_path, settings):
    """单条 provider 错误落盘，完整原因不被异常类名覆盖。"""
    app = _application()
    app.invoke_tool.return_value = SimpleNamespace(
        error=None, data=SimpleNamespace(messages=[SimpleNamespace(timestamp=1784798723000, normalized_content="原始证据")]),
    )
    output = tmp_path / "judgments.json"
    with patch.object(LLMClaimJudge, "judge", new_callable=AsyncMock, side_effect=EvaluationContractError("provider timeout after 20s")):
        result = _run(app, settings, output)
    assert result["failed"] == 1
    assert json.loads(output.read_text())[0]["error"] == "provider timeout after 20s"


def test_corrupt_results_are_not_overwritten(tmp_path, settings):
    """已有结果损坏时显式拒绝，确保人工检查材料原封保留。"""
    output = tmp_path / "judgments.json"
    output.write_text("[{broken")
    app = _application()
    with pytest.raises(EvaluationContractError, match="cannot read existing judge results"):
        _run(app, settings, output)
    assert output.read_text() == "[{broken"
    app.read_evaluation_run.assert_not_called()


def test_judge_provider_wrapper_keeps_root_message(settings):
    """包装 OpenAI 错误时保留原文和异常链。"""
    client = AsyncMock()
    client.chat.completions.create.side_effect = OpenAIError("upstream service unavailable")
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch("trivae.evaluation.benchmark.judge.AsyncOpenAI", return_value=context):
        with pytest.raises(EvaluationContractError, match="upstream service unavailable") as error:
            asyncio.run(LLMClaimJudge(settings)._complete({}, session_id="r1"))
    assert isinstance(error.value.__cause__, OpenAIError)


def test_failed_item_does_not_enter_quality_denominator(tmp_path, settings):
    """恢复已有成功判定时，新增输入故障不作为零分混入质量分母。"""
    output = tmp_path / "judgments.json"
    output.write_text(json.dumps([{
        "run_id": "previous", "grounded_claim_rate": 0.75, "citation_correctness": 0.5,
        "verification_status": "llm_assisted_provisional",
    }]))
    result = _run(_application(), settings, output)
    assert result["status"] == "partial"
    assert result["judged"] == 1
    assert result["failed"] == 1
    assert result["grounded_claim_rate_macro"] == 0.75
    assert result["citation_correctness_macro"] == 0.5


def test_judge_cli_returns_nonzero_for_partial_batch(tmp_path, settings):
    """调用方可通过退出码识别部分判定失败，不会误报整批成功。"""
    from trivae.interfaces import cli

    records = tmp_path / "records.json"
    records.write_text("[]")
    args = SimpleNamespace(
        benchmark_command="judge", records=records, database=tmp_path / "canonical.sqlite3",
        evaluation_database=tmp_path / "evaluation.sqlite3", cases_dir=tmp_path, output=tmp_path / "judgments.json",
    )
    with (
        patch.object(cli, "create_application"),
        patch.object(cli, "load_settings", return_value=settings),
        patch("trivae.evaluation.benchmark.orchestrator.judge_records", return_value={"status": "partial", "failed": 1}),
    ):
        assert cli._run_benchmark_command(args) == 1


@pytest.mark.parametrize("provider,expected", [
    ("opencode-go", {"x-opencode-session": "run:stable", "User-Agent": "trivae/0.1.0"}),
    ("deepseek", None),
])
def test_judge_uses_provider_session_contract(settings, provider, expected):
    """同一被评测 Run 的请求使用稳定会话头，其他 provider 不附加 Go 协议。"""
    from dataclasses import replace

    client = AsyncMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{}'))],
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    with patch("trivae.evaluation.benchmark.judge.AsyncOpenAI", return_value=context) as constructor:
        model_name = "deepseek-v4-flash" if provider == "opencode-go" else "deepseek-flash"
        judge = LLMClaimJudge(replace(settings, provider=provider, model_name=model_name))
        assert asyncio.run(judge._complete({}, session_id="run:stable")) == '{}'
    assert constructor.call_args.kwargs['default_headers'] == expected
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["reasoning_effort"] == "low"
    assert create_kwargs["max_tokens"] == settings.max_output_tokens


def test_existing_judge_entrypoint_preserves_canonical_time_in_evidence(tmp_path, settings):
    """真实 judge_records 投影包含来源日期，不能只测试孤立的格式函数。"""
    app = _application()
    app.invoke_tool.return_value = SimpleNamespace(error=None,
        data=SimpleNamespace(messages=[SimpleNamespace(timestamp=1784798723000, normalized_content="已经7k了")]))
    response = json.dumps({"claims": [{"block_id": "b1", "text": "错误同日关系", "is_factual": True, "supported": False}],
        "citations": []})
    with patch.object(LLMClaimJudge, "_complete", new_callable=AsyncMock, return_value=response) as complete:
        result = _run(app, settings, tmp_path / "judgments.json")
    assert result["failed"] == 0
    excerpt = complete.call_args.args[0]["evidence_excerpts"]["m1"]
    assert "2026-07-23T09:25:23Z" in excerpt
    assert "message_content: 已经7k了" in excerpt
