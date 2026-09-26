"""Planner treatment、Jev route 与人工裁决的独立契约回归。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from trivae.evaluation.benchmark.orchestrator import load_cases_dir
from trivae.evaluation.contracts import CaseReference, EvaluationSuite
from trivae.evaluation.router_utility import (
    RouterUtilityError,
    analyze_router_utility,
    load_treatment_pairs,
    run_jev_route_observations,
)
from trivae.query.router import RouterProviderResult


class _FakeJev:
    """只记录真正到达 Provider 的 ambiguous Case。"""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, context: object) -> RouterProviderResult:
        self.calls += 1
        return RouterProviderResult(
            route="planned_execution",
            confidence=0.8,
            probabilities={"standard_execution": 0.2, "planned_execution": 0.8},
            usage={"input_tokens": 10, "output_tokens": 2, "cost": 0.001},
            provider="openrouter",
            model="test-jev",
        )


class RouterUtilityTests(unittest.TestCase):
    """区分 route classification 与实际 treatment utility。"""

    def test_suite_binds_existing_and_new_case_bundles(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cases = load_cases_dir((root / "evaluation/cases/benchmark/dev", root / "evaluation/cases/planner-utility"))
        suite = EvaluationSuite.from_json(root / "evaluation/suites/planner-utility-development-v1.json")
        self.assertEqual(len(suite.case_references), 15)
        self.assertEqual({cases[ref.case_id].identity for ref in suite.case_references}, {ref.identity for ref in suite.case_references})
        self.assertEqual(len({cases[ref.case_id].dataset_snapshot.snapshot_id for ref in suite.case_references}), 1)

    def test_jev_route_observation_keeps_rule_gate_separate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cases = load_cases_dir((root / "evaluation/cases/benchmark/dev", root / "evaluation/cases/planner-utility"))
        suite = EvaluationSuite(
            suite_id="router-utility-test",
            version=1,
            kind="core",
            case_references=(CaseReference("pu-count-utc-day", 1), CaseReference("dev-context-archify", 1)),
            description="rule and Jev branches",
            created_at="2026-09-26T00:00:00+00:00",
        )
        provider = _FakeJev()
        report = asyncio.run(run_jev_route_observations(suite, cases, provider))
        self.assertEqual(provider.calls, 1)
        rows = report["cases"]
        self.assertTrue(rows[0]["rule_gate"])
        self.assertFalse(rows[1]["rule_gate"])
        self.assertEqual(rows[1]["predicted_route"], "planned_execution")

    def test_route_preflight_rejects_identity_error_before_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cases = load_cases_dir(root / "evaluation/cases/benchmark/dev")
        suite = EvaluationSuite(
            suite_id="router-utility-preflight-test",
            version=1,
            kind="core",
            case_references=(CaseReference("dev-context-archify", 1), CaseReference("missing-case", 1)),
            description="preflight identity",
            created_at="2026-09-26T00:00:00+00:00",
        )
        provider = _FakeJev()
        with self.assertRaises(RouterUtilityError):
            asyncio.run(run_jev_route_observations(suite, cases, provider))
        self.assertEqual(provider.calls, 0)

    def test_asymmetric_errors_and_pending_review(self) -> None:
        def arm(run_id: str, variant: str, valid: float) -> dict[str, object]:
            return {"run_id": run_id, "variant_id": variant, "status": "completed", "metrics": {"valid_answer": valid}, "latency_ms": 10.0, "usage": {"requests": 1}}

        pairs = [
            {"case_id": "benefit", "repetition": 1, "snapshot_id": "s", "standard": arm("s1", "std", 0.0), "planned": arm("p1", "plan", 1.0)},
            {"case_id": "harm", "repetition": 1, "snapshot_id": "s", "standard": arm("s2", "std", 1.0), "planned": arm("p2", "plan", 0.0)},
            {"case_id": "unknown", "repetition": 1, "snapshot_id": "s", "standard": arm("s3", "std", 1.0), "planned": arm("p3", "plan", 1.0)},
        ]
        routes = {"suite_identity": "suite@v1", "snapshot_id": "s", "cases": [
            {"case_id": "benefit", "repetition": 1, "predicted_route": "standard_execution", "rule_gate": False, "degraded": False},
            {"case_id": "harm", "repetition": 1, "predicted_route": "planned_execution", "rule_gate": True, "degraded": False},
            {"case_id": "unknown", "repetition": 1, "predicted_route": "standard_execution", "rule_gate": False, "degraded": True},
        ]}
        def review(case_id: str, label: str, standard_id: str, planned_id: str) -> dict[str, object]:
            return {"case_id": case_id, "label": label, "review_status": "human_adjudicated", "snapshot_id": "s", "standard_variant_id": "std", "planned_variant_id": "plan", "standard_run_ids": [standard_id], "planned_run_ids": [planned_id], "reviewer": "human-test", "rationale": "reviewed answer and evidence", "quality_axes": {"answer_correctness": "planned"}}
        adjudications = {"cases": [
            review("benefit", "planned_beneficial", "s1", "p1"),
            review("harm", "standard_preferable", "s2", "p2"),
            {"case_id": "unknown", "label": "uncertain", "review_status": "pending"},
        ]}
        report = analyze_router_utility(pairs, routes, adjudications)
        self.assertEqual(report["direction_counts"], {"planned_to_standard": 1, "standard_to_planned": 1, "unadjudicated": 1})
        self.assertEqual(report["source_counts"], {"jev_provider": 2, "rule_gate": 1})
        self.assertEqual(report["provider_degraded_count"], 1)
        self.assertEqual(report["observations"][0]["metric_deltas_planned_minus_standard"], {"valid_answer": 1.0})
        adjudications["cases"][0]["snapshot_id"] = "wrong"
        with self.assertRaises(RouterUtilityError):
            analyze_router_utility(pairs, routes, adjudications)
        routes["cases"] = routes["cases"][:-1]
        with self.assertRaisesRegex(RouterUtilityError, "missing route observation"):
            analyze_router_utility(pairs, routes, {"cases": [
                review("benefit", "planned_beneficial", "s1", "p1"),
                review("harm", "standard_preferable", "s2", "p2"),
                {"case_id": "unknown", "label": "uncertain", "review_status": "pending"},
            ]})

    def test_treatment_pair_requires_result_and_canonical_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path = root / "raw.json"
            evaluation_db = root / "evaluation.sqlite3"
            canonical_db = root / "canonical.sqlite3"
            records = [{
                "run_id": f"run-{arm}", "case_id": "case", "variant_id": arm,
                "trace_id": f"trace-{arm}", "run_status": "completed",
                "metrics": [{"name": "valid_answer", "availability": "available", "value": 1.0}],
                "operational_measurements": {"latency_ms": 10.0},
            } for arm in ("standard", "planned")]
            raw_path.write_text(json.dumps(records), encoding="utf-8")
            with sqlite3.connect(evaluation_db) as db:
                db.execute("CREATE TABLE evaluation_runs (run_id TEXT, case_id TEXT, variant_id TEXT, snapshot_id TEXT, started_at TEXT, trace_id TEXT)")
                db.execute("CREATE TABLE evaluation_results (run_id TEXT)")
                for index, arm in enumerate(("standard", "planned")):
                    db.execute("INSERT INTO evaluation_runs VALUES (?,?,?,?,?,?)", (
                        f"run-{arm}", "case", arm, "snapshot", f"2026-09-26T00:00:0{index}", f"trace-{arm}",
                    ))
                    db.execute("INSERT INTO evaluation_results VALUES (?)", (f"run-{arm}",))
            with sqlite3.connect(canonical_db) as db:
                db.execute("CREATE TABLE traces (trace_id TEXT)")
                db.executemany("INSERT INTO traces VALUES (?)", [("trace-standard",), ("trace-planned",)])
            args = (raw_path, evaluation_db, canonical_db)
            variants = {"standard_variant_id": "standard", "planned_variant_id": "planned"}
            self.assertEqual(len(load_treatment_pairs(*args, **variants)), 1)
            with sqlite3.connect(evaluation_db) as db:
                db.execute("DELETE FROM evaluation_results WHERE run_id='run-planned'")
            with self.assertRaisesRegex(RouterUtilityError, "Evaluation result missing"):
                load_treatment_pairs(*args, **variants)
            with sqlite3.connect(evaluation_db) as db:
                db.execute("INSERT INTO evaluation_results VALUES ('run-planned')")
            with sqlite3.connect(canonical_db) as db:
                db.execute("DELETE FROM traces WHERE trace_id='trace-planned'")
            with self.assertRaisesRegex(RouterUtilityError, "canonical Trace identity mismatch"):
                load_treatment_pairs(*args, **variants)


if __name__ == "__main__":
    unittest.main()
