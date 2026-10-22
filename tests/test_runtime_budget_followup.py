"""实验请求门禁的零费用测试，确保失败计入且 Case/全局上限在发送前生效。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from scripts.run_runtime_budget_followup import RequestBudgetExceeded, RequestLedger, read_json, write_json


def ledger_path(tmp_path):
    """创建独立账本；测试不读取真实实验记录或凭证。"""
    path = tmp_path / "ledger.json"
    write_json(path, {"maximum": 12, "maximum_per_case": 4, "used": 0,
                      "attempts": [], "blocked": [], "attempted_cases": []})
    return path


def body(effort="medium"):
    """最小实际 HTTP 投影，覆盖模型和 effort 的发送前约束。"""
    return {"model": "gpt-6.1-sol", "reasoning": {"effort": effort}, "store": False, "stream": True}


def test_failed_transport_still_debits_before_send(tmp_path):
    path = ledger_path(tmp_path)

    def fail(request):
        # transport 执行前必须已经能从磁盘看到预扣次数。
        assert read_json(path)["used"] == 1
        raise httpx.ConnectError("fixture connection failure")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail),
                                     event_hooks={"request": [RequestLedger(path, "matt").before_request]}) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post("https://api.openai.com/v1/responses", json=body())

    asyncio.run(scenario())
    assert read_json(path)["used"] == 1


def test_case_and_global_caps_never_send_extra_http(tmp_path):
    path = ledger_path(tmp_path)
    sent = []

    def success(request):
        sent.append(request)
        return httpx.Response(200, json={})

    async def scenario():
        for case in ("matt", "miner", "written"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(success),
                                         event_hooks={"request": [RequestLedger(path, case).before_request]}) as client:
                for _ in range(4):
                    await client.post("https://api.openai.com/v1/responses", json=body())
                with pytest.raises(RequestBudgetExceeded):
                    await client.post("https://api.openai.com/v1/responses", json=body())

    asyncio.run(scenario())
    record = read_json(path)
    assert len(sent) == record["used"] == 12
    assert len(record["blocked"]) == 3
    assert all(item["reason"] == "EXPERIMENT_HTTP_LIMIT" for item in record["blocked"])


def test_effort_drift_rejected_before_debit(tmp_path):
    path = ledger_path(tmp_path)
    request = httpx.Request("POST", "https://api.openai.com/v1/responses", content=json.dumps(body("high")))
    with pytest.raises(RuntimeError, match="effort changed"):
        asyncio.run(RequestLedger(path, "matt").before_request(request))
    assert read_json(path)["used"] == 0
