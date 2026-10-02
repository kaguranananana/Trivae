"""实验隔离、真实请求计数、未知 usage 与 blind packet 的 provider-free 回归。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx2 as httpx
import pytest

# experiment runner 保留历史独立脚本布局，测试只导入实验目录，不改变生产 import。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluation/planner-p1-stability"))
from run_p1_e2e import (  # noqa: E402
    CASE_IDS,
    HTTPRecorder,
    ObservedStream,
    blind_packet,
    load_cases,
    public_fields,
    response_projection,
    schedule,
    serialize_preflight,
    usage_for,
)

from trivae.config.settings import ModelSettings  # noqa: E402
from trivae.evaluation.contracts import EvaluationCaseBundle  # noqa: E402
from trivae.query.runtime.openai_adapter import OpenAIAgentsRuntimeAdapter  # noqa: E402


def test_schedule_is_bounded_paired_and_counterbalanced():
    """每侧每 case 恰好一次且相邻，避免错误的先跑整组设计。"""
    order = schedule(20261002, 1)
    assert len(order) == 16
    assert order == schedule(20261002, 1)
    assert {(r["case_id"], r["treatment"]) for r in order} == {(c, e) for c in CASE_IDS for e in ("low", "none")}
    for i in range(0, 16, 2):
        assert order[i]["case_id"] == order[i + 1]["case_id"]
        assert order[i]["treatment"] != order[i + 1]["treatment"]
    assert order[0]["treatment"] != order[2]["treatment"]


def test_unknown_usage_does_not_become_zero_or_hide_partial_observation():
    """一条请求缺失字段时整体 total 未知，但保留实际观察到的分量。"""
    requests = [{"response": {"chunks": [{"usage": {"prompt_tokens": 10, "completion_tokens": 4,
        "completion_tokens_details": {"reasoning_tokens": 3}}}]}}, {"response": None}]
    total = usage_for(requests)
    assert total["input_tokens"] == {"total": None, "observed_sum": 10, "observed_requests": 1, "requests": 2}
    assert total["reasoning_tokens"]["total"] is None
    assert total["reasoning_tokens"]["observed_sum"] == 3
    assert total["cached_input_tokens"]["total"] is None


def test_serialization_diff_uses_actual_sdk_without_network():
    """使用 fake key + 禁止外部 transport 验证真实 SDK request body，只改变 effort。"""
    async def check():
        runtime = OpenAIAgentsRuntimeAdapter(settings=ModelSettings(api_key="provider-free", base_url="https://invalid.test",
            provider="deepseek", model_name="deepseek-flash", max_turns=8))
        try:
            result = await serialize_preflight(runtime, "fixed canonical prompt")
            assert result["network_requests"] == 0
            assert result["differences"] == ["reasoning_effort"]
            assert result["requests"]["low"]["messages"] == result["requests"]["none"]["messages"]
            assert result["requests"]["none"]["max_tokens"] == 2048
            assert runtime._provider_client.max_retries == 0
            assert runtime.planner_completion_request_projection()["reasoning_effort"] == "none"
        finally:
            await runtime.aclose()
    asyncio.run(check())


def test_stream_observer_preserves_bytes_and_usage(tmp_path):
    """随机 transport 分块不改原始流，不保存 hidden reasoning，逐请求 usage 单独落盘。"""
    data = b'data: {"choices":[{"delta":{"reasoning_content":"private","content":"answer"},"finish_reason":"stop"}]}\n\ndata: {"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\ndata: [DONE]\n\n'
    async def check():
        recorder = HTTPRecorder(tmp_path)
        request = httpx.Request("POST", "https://invalid.test", json={"model": "deepseek-flash", "stream": True})
        await recorder.request(request)
        response = httpx.Response(200, request=request, stream=httpx.ByteStream(data))
        # 测试用异步分块 stream，模拟真实 httpx transport。
        class Source(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield data[:37]
                yield data[37:]
        response.stream = Source()
        await recorder.response(response)
        received = b"".join([chunk async for chunk in response.stream])
        assert received == data
        recorded = recorder.records(0)
        assert len(recorded) == 1
        assert recorded[0]["response"]["stream_complete"] is True
        assert usage_for(recorded)["input_tokens"]["total"] == 10
        assert "private" not in (tmp_path / "provider_responses.jsonl").read_text()
        assert "reasoning_content" not in (tmp_path / "provider_responses.jsonl").read_text()
    asyncio.run(check())


def test_http_failure_is_a_real_request_with_unknown_usage(tmp_path):
    """真实失败不能从请求 ledger 消失；没有响应时 usage 明确未知。"""
    async def check():
        recorder = HTTPRecorder(tmp_path)
        await recorder.request(httpx.Request("POST", "https://invalid.test", json={"messages": []}))
        records = recorder.records(0)
        assert len(records) == 1 and records[0]["response"] is None
        assert usage_for(records)["input_tokens"]["total"] is None
        assert len((tmp_path / "provider_requests.jsonl").read_text().splitlines()) == 1
    asyncio.run(check())


def test_blind_packet_hides_treatment_and_execution_metadata(tmp_path):
    """盲审仅携带问题/GT/答案，失败双方仍进入 packet。"""
    cases = [EvaluationCaseBundle.from_json(Path(row["source"])) for row in load_cases()]
    records = [{"case_id": c.case_id, "treatment": e, "final_answer": None,
                "answer_artifact": {"run_id": "secret-run", "created_at": "secret-time", "content_blocks": []}}
               for c in cases for e in ("low", "none")]
    blind_packet(tmp_path, cases, records, 1234)
    packet = json.loads((tmp_path / "packet.json").read_text())
    assert len(packet) == 8
    assert all(set(p["answers"]) == {"A", "B"} for p in packet)
    encoded = json.dumps(packet)
    assert "secret-run" not in encoded and "secret-time" not in encoded
    assert "treatment" not in encoded and "reasoning_effort" not in encoded
    assert "latency" not in encoded and "run_order" not in encoded
    assert all(p["answers"]["A"]["answer"] is None for p in packet)


def test_response_projection_keeps_public_error_and_finish_reason():
    """非流式 length 与 Provider error 仍可归因。"""
    projection = response_projection(b'{"choices":[{"finish_reason":"length","message":{"content":"","reasoning_content":"private"}}]}', False)
    assert projection["chunks"][0]["choices"][0]["finish_reason"] == "length"
    assert "reasoning_content" not in projection["chunks"][0]["choices"][0]["message"]
    assert public_fields({"completion_tokens_details": {"reasoning_tokens": 9}})["completion_tokens_details"]["reasoning_tokens"] == 9


def test_observer_propagates_transport_failure():
    """观测层不能吞掉 transport 错误，已收到数据仍交给归档回调。"""
    async def check():
        saved = []
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"received"
                raise httpx.ReadTimeout("transport timeout")
        stream = ObservedStream(Broken(), saved.append)
        with pytest.raises(httpx.ReadTimeout):
            async for _ in stream:
                pass
        assert saved == [b"received"]
    asyncio.run(check())


def test_interrupted_sse_preserves_complete_frames_and_marks_tail():
    """timeout 可能落在 frame 中间；尾部不冒充完整响应，既有 usage 仍保存。"""
    body = b'data: {"usage":{"prompt_tokens":7}}\n\ndata: {"cho'
    result = response_projection(body, True)
    assert result["chunks"] == [{"usage": {"prompt_tokens": 7}}]
    assert result["stream_complete"] is False
    assert result["incomplete_tail_bytes"] == len(b'data: {"cho')
