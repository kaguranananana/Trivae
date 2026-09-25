#!/usr/bin/env python3
"""从 Trace 的请求起点重建保守的计费调用账本，不读取模型正文。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Mapping


def build_ledger(raw_paths: list[Path], canonical_db: Path, route_paths: list[Path]) -> dict[str, object]:
    """一次 Runtime turn/Planner start/Jev Provider attempt 各占一个预算槽。"""

    events: list[dict[str, object]] = []
    with sqlite3.connect(f"file:{canonical_db.resolve()}?mode=ro", uri=True) as db:
        for raw_path in raw_paths:
            records = json.loads(raw_path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError(f"raw records must be an array: {raw_path}")
            for record in records:
                if not isinstance(record, Mapping):
                    raise ValueError("raw run must be an object")
                trace_id = record["trace_id"]
                rows = db.execute(
                    "SELECT sequence, occurred_at, operation, phase, operation_id, payload_json "
                    "FROM trace_events WHERE trace_id=? AND operation IN "
                    "('planner.started','planner.completed','planner.failed','model.turn','model.usage') "
                    "ORDER BY sequence",
                    (trace_id,),
                ).fetchall()
                # 每个起点与同 operation_id 的终态/usage 配对；失败和无 usage 仍计入。
                endings = {(row[2], row[4]): row for row in rows if row[3] in ("completed", "failed")}
                usages = {row[4]: json.loads(row[5]).get("usage") for row in rows if row[2] == "model.usage"}
                for row in rows:
                    _, when, operation, phase, operation_id, payload_json = row
                    if phase != "started" or operation not in ("planner.started", "model.turn"):
                        continue
                    payload = json.loads(payload_json)
                    planner = operation == "planner.started"
                    end = endings.get(("planner.completed" if planner else "model.turn", operation_id))
                    if planner and end is None:
                        end = endings.get(("planner.failed", operation_id))
                    end_payload = json.loads(end[5]) if end is not None else {}
                    usage = end_payload.get("usage") if planner else usages.get(operation_id)
                    events.append({
                        "occurred_at": when,
                        "case_id": record["case_id"],
                        "experiment": raw_path.parent.name,
                        "arm": "planned" if planner or "planned" in str(record["variant_id"]) else "standard",
                        "provider": end_payload.get("provider") or payload.get("provider") or "deepseek",
                        "model": end_payload.get("model") or payload.get("model") or "unavailable",
                        "purpose": "planner" if planner else "runtime",
                        "result": "unknown_after_start" if end is None else end[3],
                        "estimated_usage": None,
                        "actual_usage": usage if isinstance(usage, Mapping) else None,
                        "run_id": record["run_id"],
                    })
    for route_path in route_paths:
        routes = json.loads(route_path.read_text(encoding="utf-8"))
        for route in routes["cases"]:
            # Rule gate 不发计费请求；ambiguous route 即使降级也保守记一次 Jev attempt。
            if route["rule_gate"]:
                continue
            events.append({
                "occurred_at": None,
                "case_id": route["case_id"],
                "experiment": route_path.parent.name,
                "arm": "route",
                "provider": route.get("provider") or "openrouter",
                "model": route.get("model") or "jev-decisions",
                "purpose": "jev_decisions",
                "result": "degraded" if route.get("degraded") else "completed",
                "estimated_usage": None,
                "actual_usage": route.get("usage"),
                "run_id": None,
            })
    # Trace 自带时刻；Jev 路由文件没有时刻，按输入文件/Case 顺序列在末尾。
    events.sort(key=lambda event: (event["occurred_at"] is None, event["occurred_at"] or ""))
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        event["cumulative_invocation_count"] = sequence
    return {
        "schema_version": 1,
        "counting_policy": "conservative request-start accounting; failed and unknown outcomes count",
        "total_paid_provider_invocations": len(events),
        "by_purpose": {
            purpose: sum(event["purpose"] == purpose for event in events)
            for purpose in ("planner", "runtime", "existing_router_llm", "jev_decisions")
        },
        "invocations": events,
    }


def main() -> None:
    """本地 create-only 写入 ignored 账本；绝不输出私有模型内容。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, action="append", default=[])
    parser.add_argument("--canonical-db", type=Path, required=True)
    parser.add_argument("--routes", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_ledger(args.raw, args.canonical_db, args.routes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"total": report["total_paid_provider_invocations"], "by_purpose": report["by_purpose"]}))


if __name__ == "__main__":
    main()
