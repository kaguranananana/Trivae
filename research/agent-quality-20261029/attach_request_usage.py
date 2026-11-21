"""Fill the existing request ledger from exact per-worker request order and saved usage.

Run after all requests stop. Count mismatches fail explicitly; missing response usage
stays unknown. No model calls, source-data changes or cost estimates.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030"
RESEARCH = Path(__file__).resolve().parent


def trace_requests(trace):
    events = trace["timeline"]
    records = []
    for i, event in enumerate(events):
        payload = event["payload"]
        if event["operation"] in {"router.decision", "planner.completed"} and payload.get("usage"):
            records.append({"usage": payload["usage"], "source": f"{trace['trace_id']}:{event['sequence']}", "kind": "completion"})
        if event["operation"] == "model.turn" and event["phase"] == "started":
            end = next((j for j in range(i + 1, len(events))
                        if events[j]["operation"] == "model.turn" and events[j]["phase"] == "started"), len(events))
            usage = next((e["payload"]["usage"] for e in events[i + 1:end] if e["operation"] == "model.usage"), None)
            records.append({"usage": usage, "source": f"{trace['trace_id']}:{event['sequence']}", "kind": "runtime"})
    model = [record for record in records if record["kind"] == "runtime"]
    missing = [record for record in model if record["usage"] is None]
    aggregate = next((e["payload"].get("usage") for e in reversed(events)
                      if e["operation"] == "runtime.run" and e["phase"] in {"completed", "failed"}), None)
    # A completed response can be counted by Runtime before a failing hook skips
    # model.usage emission. Recover its exact delta only when the count proves it.
    if len(missing) == 1 and aggregate and aggregate.get("requests") == len(model):
        delta = {key: aggregate[key] - sum(record["usage"].get(key, 0) for record in model if record["usage"])
                 for key in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens")}
        assert all(value >= 0 for value in delta.values())
        missing[0]["usage"] = {**delta, "requests": 1}
        missing[0]["source"] += " (exact runtime aggregate minus observed model usage)"
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    by_id = {}
    for path in OUT.glob("**/http-events.jsonl"):
        events = [json.loads(line) for line in path.read_text().splitlines()]
        sends = [e for e in events if e["event"] == "sending"]
        if not sends:
            continue
        role = sends[0]["role"]
        if role == "agent":
            record = OUT / path.parent.name.removeprefix("http-")
            traces = [json.loads(p.read_text()) for p in (record / "traces").glob("*.json")]
            traces.sort(key=lambda t: t["started_at"])
            usages = [u for trace in traces for u in trace_requests(trace)]
        else:
            responses = sorted(path.parent.glob("*/response.json"), key=lambda p: p.stat().st_mtime_ns)
            usages = [{"usage": json.loads(p.read_text())["usage"], "source": str(p.relative_to(ROOT))}
                      for p in responses]
        assert len(sends) == len(usages), (str(path), len(sends), len(usages))
        for send, usage in zip(sends, usages, strict=True):
            status = next((e.get("status") for e in events
                           if e["event"] == "headers_received" and e["id"] == send["id"]), None)
            by_id[send["id"]] = {**usage, "role": role, "http_status": status}
    recovery = json.loads((OUT / "request-count-recovery.json").read_text())
    for i, request in enumerate(recovery["http_requests"], 1):
        by_id[f"agent-{i:03d}"] = {"usage": request["usage"], "source": f"{request['trace_id']}:{request['sequence']}",
                                    "role": "agent", "http_status": None}
    known = Counter()
    unknown = Counter()
    totals = {"agent": Counter(), "judge": Counter()}
    for record in by_id.values():
        if record["usage"] is None:
            unknown[record["role"]] += 1
            continue
        known[record["role"]] += 1
        for key, value in record["usage"].items():
            if isinstance(value, int) and key != "requests":
                totals[record["role"]][key] += value
    result = {"requests": by_id, "known_usage_requests": dict(known), "unknown_usage_requests": dict(unknown),
              "observed_usage_subtotals": {role: dict(t) for role, t in totals.items()},
              "cost": "n/a: no billing data or assumed token price; partial streams have unknown usage"}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    ledger = RESEARCH / "LEDGER.md"
    lines = []
    updated = 0
    for line in ledger.read_text().splitlines():
        parts = line.split("|")
        match = re.search(r"(?:recovered-)?((?:agent|judge)-\d{3})", parts[3]) if len(parts) == 10 else None
        if match:
            record = by_id[match.group(1)]
            parts[6] = " " + (json.dumps(record["usage"], separators=(",", ":")) if record["usage"] else "unknown（未记录完整Usage）") + " "
            parts[8] = parts[8].split(" Usage来源 ", 1)[0] + f" Usage来源 {record['source']}；HTTP状态 {record['http_status'] or '未直接记录（追记请求）'} "
            line = "|".join(parts)
            updated += 1
        lines.append(line)
    assert updated == len(by_id), (updated, len(by_id))
    ledger.write_text("\n".join(lines) + "\n")
    print(json.dumps({"known": dict(known), "unknown": dict(unknown), "ledger_rows_updated": updated,
                      "observed_usage_subtotals": result["observed_usage_subtotals"]}, indent=2))


if __name__ == "__main__":
    main()
