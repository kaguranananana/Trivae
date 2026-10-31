"""Explicit HTTP admission meter for this research only; never a product retry layer."""
from __future__ import annotations

import fcntl
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import httpx2

RESEARCH = Path(__file__).resolve().parent


def install_meter(role: str, label: str, output: Path, *, research: Path = RESEARCH):
    """Count each actual inference HTTP send, including failures and library retries.

    Endpoint metadata excludes headers, credentials, query parameters and bodies.
    Both sync and async clients are covered. Admission fails before the next send
    when the cumulative research allowance is empty.
    """
    output.mkdir(parents=True, exist_ok=True)
    key = {"agent": "deepseekRemaining", "judge": "judgeRemaining"}[role]
    budget_file = research / "budget.json"
    ledger = research / "LEDGER.md"
    lock_file = research / ".request-meter.lock"
    observations = output / "http-events.jsonl"

    def event(record):
        with observations.open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def admit(request):
        inference = request.method == "POST" and request.url.path.rstrip("/").endswith(
            "/chat/completions" if role == "agent" else "/responses"
        )
        if not inference:
            return None
        now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
        with lock_file.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            budget = json.loads(budget_file.read_text())
            if budget[key] <= 0:
                raise RuntimeError(f"Research cumulative {role} budget exhausted; HTTP not sent")
            ordinal = (250 if role == "agent" else 32) - budget[key] + 1
            request_id = f"{role}-{ordinal:03d}"
            with ledger.open("a") as stream:
                stream.write(f"| {now} | Codex R2 | {label}/{request_id} | "
                             f"{'DeepSeek deepseek-flash' if role == 'agent' else 'ChatGPT OAuth gpt-plus'} | "
                             f"1 | n/a（Run/response另存） | n/a | admitted; outcome见http-events.jsonl |\n")
            budget[key] -= 1
            budget_file.write_text(json.dumps(budget, indent=2) + "\n")
        event({"event": "sending", "id": request_id, "time": now, "role": role,
               "label": label, "host": request.url.host, "path": request.url.path})
        return request_id

    def wrap_async(send):
        async def metered_async(client, request):
            request_id = admit(request)
            try:
                response = await send(client, request)
            except Exception as exc:
                if request_id:
                    event({"event": "transport_failed", "id": request_id, "type": type(exc).__name__})
                raise
            if request_id:
                event({"event": "headers_received", "id": request_id, "status": response.status_code})
            return response
        return metered_async

    def wrap_sync(send):
        def metered_sync(client, request):
            request_id = admit(request)
            try:
                response = send(client, request)
            except Exception as exc:
                if request_id:
                    event({"event": "transport_failed", "id": request_id, "type": type(exc).__name__})
                raise
            if request_id:
                event({"event": "headers_received", "id": request_id, "status": response.status_code})
            return response
        return metered_sync

    # Installed OpenAI SDK defaults to httpx2; OAuth uses httpx. Both are actual
    # active transports, not speculative compatibility paths.
    originals = []
    for library in (httpx, httpx2):
        originals.append((library, library.AsyncClient._send_single_request, library.Client._send_single_request))
        library.AsyncClient._send_single_request = wrap_async(originals[-1][1])
        library.Client._send_single_request = wrap_sync(originals[-1][2])

    def restore():
        for library, async_send, sync_send in originals:
            library.AsyncClient._send_single_request = async_send
            library.Client._send_single_request = sync_send

    return restore
