"""Exercise the installed SDK transport as well as the OAuth HTTP client, without network."""
import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import httpx2
import pytest
from openai import APIStatusError, AsyncOpenAI, DefaultAsyncHttpxClient

_SPEC = importlib.util.spec_from_file_location(
    "research_meter", Path(__file__).resolve().parents[1] / "research/agent-quality-20261029/model_request_meter.py",
)
_METER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_METER)


@pytest.mark.parametrize("library", [httpx, httpx2])
def test_meter_counts_failed_sends_and_rejects_next_send(tmp_path, library):
    (tmp_path / "budget.json").write_text(json.dumps({"deepseekRemaining": 1, "judgeRemaining": 1}))
    (tmp_path / "LEDGER.md").write_text("test\n")
    sends = []

    def handle(request):
        sends.append(request.method)
        return library.Response(503)

    async def run():
        restore = _METER.install_meter("agent", "test", tmp_path / "events", research=tmp_path)
        try:
            async with library.AsyncClient(transport=library.MockTransport(handle)) as client:
                await client.get("https://example.test/models")
                await client.post("https://example.test/chat/completions")
                with pytest.raises(RuntimeError, match="budget exhausted"):
                    await client.post("https://example.test/chat/completions")
        finally:
            restore()

    asyncio.run(run())
    assert sends == ["GET", "POST"]
    assert json.loads((tmp_path / "budget.json").read_text())["deepseekRemaining"] == 0
    events = [json.loads(line) for line in (tmp_path / "events/http-events.jsonl").read_text().splitlines()]
    assert [(e["event"], e.get("status")) for e in events] == [("sending", None), ("headers_received", 503)]


def test_meter_covers_installed_openai_default_httpx2_client(tmp_path):
    (tmp_path / "budget.json").write_text(json.dumps({"deepseekRemaining": 250, "judgeRemaining": 32}))
    (tmp_path / "LEDGER.md").write_text("test\n")

    async def run():
        restore = _METER.install_meter("agent", "sdk-default", tmp_path / "events", research=tmp_path)
        try:
            # This is the SDK's actual default client class, not an httpx replacement.
            transport = httpx2.MockTransport(lambda r: httpx2.Response(503, json={"error": {"message": "test"}}))
            async with AsyncOpenAI(
                api_key="test", base_url="https://example.test", max_retries=0,
                http_client=DefaultAsyncHttpxClient(transport=transport, trust_env=False),
            ) as client:
                assert isinstance(client._client, httpx2.AsyncClient)
                with pytest.raises(APIStatusError):
                    await client.chat.completions.create(model="test", messages=[{"role": "user", "content": "test"}])
        finally:
            restore()

    asyncio.run(run())
    assert json.loads((tmp_path / "budget.json").read_text())["deepseekRemaining"] == 249
    assert (tmp_path / "LEDGER.md").read_text().count("agent-001") == 1
