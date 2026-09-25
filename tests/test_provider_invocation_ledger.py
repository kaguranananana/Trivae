"""计费请求起点账本必须包含失败请求，且 Rule gate 不计费。"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_provider_invocation_ledger import build_ledger


class ProviderInvocationLedgerTests(unittest.TestCase):
    """只用本地 Trace 事件验证逐次计数。"""

    def test_failed_runtime_and_degraded_jev_are_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db_path = root / "canonical.sqlite3"
            raw_path = root / "treatment" / "raw-records.json"
            routes_path = root / "routes" / "routes.json"
            raw_path.parent.mkdir()
            routes_path.parent.mkdir()
            raw_path.write_text(json.dumps([{
                "trace_id": "trace-1", "case_id": "case-1", "variant_id": "planned-v1", "run_id": "run-1"
            }]), encoding="utf-8")
            routes_path.write_text(json.dumps({"cases": [
                {"case_id": "case-1", "rule_gate": False, "degraded": True, "usage": None},
                {"case_id": "control", "rule_gate": True, "degraded": False, "usage": None},
            ]}), encoding="utf-8")
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE trace_events (trace_id TEXT, sequence INTEGER, occurred_at TEXT, operation TEXT, phase TEXT, operation_id TEXT, payload_json TEXT)")
                db.executemany("INSERT INTO trace_events VALUES (?,?,?,?,?,?,?)", [
                    ("trace-1", 1, "2026-09-26T00:00:00", "planner.started", "started", "planner", '{"provider":"deepseek","model":"flash"}'),
                    ("trace-1", 2, "2026-09-26T00:00:01", "planner.completed", "completed", "planner", '{"usage":{"input_tokens":10}}'),
                    ("trace-1", 3, "2026-09-26T00:00:02", "model.turn", "started", "turn-1", '{"provider":"deepseek","model":"flash"}'),
                    ("trace-1", 4, "2026-09-26T00:00:03", "model.turn", "failed", "turn-1", '{}'),
                ])
            ledger = build_ledger([raw_path], db_path, [routes_path])
            self.assertEqual(ledger["total_paid_provider_invocations"], 3)
            self.assertEqual(ledger["by_purpose"], {
                "planner": 1, "runtime": 1, "existing_router_llm": 0, "jev_decisions": 1,
            })
            self.assertEqual([item["result"] for item in ledger["invocations"]], ["completed", "failed", "degraded"])
            self.assertEqual([item["cumulative_invocation_count"] for item in ledger["invocations"]], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
