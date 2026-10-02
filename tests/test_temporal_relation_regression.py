"""保存 low-r2 原始日期关系错误，复用既有 Evidence 与 Judge 契约。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from trivae.config.settings import ModelSettings
from trivae.evaluation.benchmark.judge import LLMClaimJudge, canonical_message_excerpt
from trivae.query.runtime.prompt import SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "evaluation/regressions/archify-temporal-relation.json"


def test_real_same_day_failure_conflicts_with_canonical_dates_and_preserves_original():
    """日期比较稳定否定旧同日关系；保留错误 Claim、finding、criterion 和绑定。"""
    case = json.loads(FIXTURE.read_text())
    original = json.loads((ROOT / case["source_artifact"]).read_text())
    assert case["observed_content_block"] == original["answer_artifact"]["content_blocks"][1]
    assert case["observed_evidence"] == original["answer_artifact"]["evidence_items"][1]
    assert case["citation_binding"] == original["answer_artifact"]["citation_bindings"][1]
    # fixture 的时间来自真实来源快照，而不是从错误 finding 再提取“同日”。
    sources = case["canonical_sources"]
    dates = [datetime.fromtimestamp(s["snapshot"]["timestamp_ms"] / 1000,
        tz=UTC) for s in sources]
    actual_same_day = dates[0].date() == dates[1].date()
    assert actual_same_day == case["expected_relation"]["same_day"]
    assert actual_same_day != case["observed_relation"]["same_day"]
    assert (dates[1] - dates[0]).total_seconds() == case["expected_relation"]["elapsed_seconds"]
    # 正确排序与倒序对照；不引入自然语言 regex 判定或生产硬拒绝。
    assert dates[0] < dates[1]
    assert not dates[1] < dates[0]
    assert [s["internal_message_id"] for s in sources] == [case["expected_relation"]["earlier_message_id"],
        case["expected_relation"]["later_message_id"]]
    assert "同一天" in case["observed_content_block"]["text"]
    assert "同日" in case["observed_evidence"]["finding"]
    assert "同日" in case["observed_evidence"]["criterion"]


def test_existing_judge_receives_canonical_dates_and_keeps_unsupported_relation():
    """无 Provider 验证日期输入和既有判定 parser；mock verdict 不冒充模型质量验证。"""
    case = json.loads(FIXTURE.read_text())
    excerpts = {s["internal_message_id"]: canonical_message_excerpt(
        timestamp_ms=s["snapshot"]["timestamp_ms"], content=s["snapshot"]["excerpt"] + "长正文" * 300)
        for s in case["canonical_sources"]}
    # 单次 mock 仅检查既有 Judge contract 能承载该失败的 judgment；不增加真实请求。
    response = {"claims": [{"block_id": "claim-2", "text": "7k 与 9.5k 在同一天", "is_factual": True, "supported": False}],
        "citations": [{"content_block_id": "claim-2", "evidence_ids": ["e2"], "verdict": "partially_supported"}]}
    settings = ModelSettings(api_key="provider-free", base_url="https://invalid.test", provider="deepseek",
        model_name="deepseek-flash", max_turns=8)
    with patch.object(LLMClaimJudge, "_complete", new_callable=AsyncMock, return_value=json.dumps(response)) as complete:
        judgment = asyncio.run(LLMClaimJudge(settings).judge(run_id=case["source_run_id"], case_id=case["case_id"],
            variant_id="saved-regression", content_blocks=[case["observed_content_block"]],
            citation_bindings=[case["citation_binding"]], evidence_excerpts=excerpts))
    payload = complete.call_args.args[0]
    assert "2026-07-23T09:25:23Z" in payload["evidence_excerpts"][case["expected_relation"]["earlier_message_id"]]
    assert "2026-08-06T02:40:20Z" in payload["evidence_excerpts"][case["expected_relation"]["later_message_id"]]
    assert all(len(s) <= 400 for s in payload["evidence_excerpts"].values())
    assert judgment.claims[0].supported is False
    assert judgment.citations[0].verdict == case["expected_citation_verdict"]
    assert judgment.verification_status == "llm_assisted_provisional"
    assert "finding, or criterion" in SYSTEM_PROMPT
