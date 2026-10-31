"""Reconcile new HTTP admissions, saved Usage, actual inputs and visible GT.

Updates only this round's admitted ledger rows (agent>=123 / judge>=27).
Historical results and original ledger rows remain unchanged.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

from offline import targets

from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/budget-capacity-20261031"
STATE = ROOT / "research/agent-quality-20261029"


def main():
    repo = SQLiteCanonicalReadRepository(ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3")
    gt, _ = targets(repo)
    repo.close()
    rows, records = [], {}
    for arm in ("32", "64"):
        directory = OUT / f"controlled-live-v2-{arm}"
        results = [json.loads(p.read_text()) | {"case": p.parent.name, "directory": p.parent}
                   for p in directory.glob("*/result.json")]
        events = [json.loads(line) for line in (directory / "http-events.jsonl").read_text().splitlines()]
        sends = [e for e in events if e["event"] == "sending"]
        # The predeclared case order was 08/10/12; budget failure 10 at 32K sent none.
        requested = sorted([r for r in results if r["inference_http_requests"]], key=lambda r: r["case"])
        assert len(sends) == len(requested)
        for index, result in enumerate(requested):
            usage = result["usage"]
            provider = {k: usage[k] for k in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens")}
            provider["requests"] = 1
            records[sends[index]["id"]] = {"usage": provider, "source": str((result["directory"] / "result.json").relative_to(ROOT)), "status": 200}
            body = json.loads((directory / f"request-{index+1:03}.json").read_text())
            tools = [json.loads(p.read_text()) for p in result["directory"].glob("tool-*.json")]
            mapping = {handle: mid for t in tools for handle, mid in t["handle_map"].items()}
            visible, projected, estimated, truncated, omitted_hits = set(), 0, 0, 0, 0
            for message in body["messages"]:
                if message["role"] != "tool":
                    continue
                # Installed SDK sends repr(dict) tool strings. Parse the actual
                # captured request, rather than reconstructing visibility from DB.
                payload = ast.literal_eval(message["content"])
                handles = [s["source_id"] for s in payload["provenance"]["message_sources"]]
                visible.update(mapping[h] for h in handles)
                metrics = payload["model_projection"]
                projected += metrics["projected_messages"]
                estimated += metrics["estimated_tokens"]
                truncated += metrics["truncated"]
                omitted_hits += metrics["omitted_hit_messages"]
            full_estimate = (len(json.dumps(body["messages"], ensure_ascii=False, separators=(",", ":")).encode()) + 2) // 3
            # Saturday official off-peak tariff, USD/M tokens: miss .15, hit .003,
            # output .6. This is a tariff estimate, not a billed-account invoice.
            cost = ((provider["input_tokens"] - provider["cached_input_tokens"]) * .15
                    + provider["cached_input_tokens"] * .003 + provider["output_tokens"] * .6) / 1000000
            rows.append({"pool": int(arm)*1000, "case": result["case"], "runtime": result["termination"],
                         "delivered": result["artifact"] is not None, "finalization_error": result["finalization_error"],
                         "usage": provider, "latency_seconds": result["latency_seconds"], "tariff_usd": cost,
                         "visible_gt": sorted(visible & gt[result["case"]]), "known_gt": sorted(gt[result["case"]]),
                         "visible_messages_unique": len(visible), "projected_occurrences": projected,
                         "estimated_tool_tokens": estimated, "truncated_results": truncated, "omitted_hit_messages": omitted_hits,
                         "full_message_bytes_over_3": full_estimate, "provider_over_estimate": provider["input_tokens"]/full_estimate})
        for result in results:
            if not result["inference_http_requests"]:
                rows.append({"pool": int(arm)*1000, "case": result["case"], "runtime": result["termination"],
                             "delivered": False, "error": result["runtime_error"], "inference_http_requests": 0,
                             "visible_gt": None, "latency_seconds": result["latency_seconds"]})
    # All new HTTP attempts, including invalid fixture, diagnostic and Judge failure.
    events_by_id = {}
    for file in OUT.glob("**/http-events.jsonl"):
        for event in map(json.loads, file.read_text().splitlines()):
            if event["event"] == "sending":
                assert event["id"] not in events_by_id
                events_by_id[event["id"]] = {"source": str(file.relative_to(ROOT)), "status": None}
            elif event["id"] in events_by_id:
                if event["event"] == "headers_received":
                    events_by_id[event["id"]]["status"] = event["status"]
                if event["event"] == "transport_failed":
                    events_by_id[event["id"]]["failure"] = event["type"]
    for directory in sorted(OUT.glob("judge*")):
        event_file = directory / "http-events.jsonl"
        if not event_file.exists():
            continue
        sends = [e for e in map(json.loads, event_file.read_text().splitlines()) if e["event"] == "sending"]
        responses = sorted(directory.glob("*/response.json"), key=lambda p: p.stat().st_mtime_ns)
        successful = [s for s in sends if events_by_id[s["id"]]["status"] == 200]
        assert len(successful) == len(responses)
        for send, response in zip(successful, responses, strict=True):
            records[send["id"]] = {"usage": json.loads(response.read_text())["usage"],
                                   "source": str(response.relative_to(ROOT)), "status": 200}
    for request_id, info in events_by_id.items():
        records.setdefault(request_id, {**info, "usage": "unknown (no Provider Usage returned)"})
    budget = json.loads((STATE / "budget.json").read_text())
    assert 128 - budget["deepseekRemaining"] == sum(i.startswith("agent-") for i in events_by_id)
    assert 6 - budget["judgeRemaining"] == sum(i.startswith("judge-") for i in events_by_id)
    ledger = STATE / "LEDGER.md"
    lines = ledger.read_text().splitlines()
    for index, line in enumerate(lines):
        matches = [i for i in records if f"/{i} |" in line]
        if not matches:
            continue
        assert len(matches) == 1
        info = records[matches[0]]
        columns = line.split("|")
        columns[6] = " " + json.dumps(info["usage"], ensure_ascii=False, separators=(",", ":")) + " "
        columns[8] = f" Usage source {info['source']}; HTTP {info.get('status')}; {info.get('failure', '')} "
        lines[index] = "|".join(columns)
    ledger.write_text("\n".join(lines)+"\n")
    summary = {"controlled_answers": sorted(rows, key=lambda r: (r["pool"], r["case"])),
               "requests": records, "remaining": budget,
               "tariff_source": "https://api-docs.deepseek.com/quick_start/pricing/ (2026-10-31 Saturday off-peak)",
               "unknown_usage": [i for i,r in records.items() if isinstance(r["usage"], str)]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({"rows": rows, "remaining": budget, "unknown_usage": summary["unknown_usage"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
