"""Read local runs, reviews, diagnoses and judge outcomes without aggregating them into accuracy."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .contracts import EvaluationContractError, EvaluationReview, EvaluationRun
from .langsmith_sync import _index_records, _read_db


def run_report(database: Path, *, suite_id: str | None = None, judgments: Path | None = None) -> dict[str, Any]:
    judge_records = _index_records(judgments)
    con = _read_db(database)
    try:
        if suite_id:
            rows = con.execute("SELECT payload_json FROM evaluation_runs WHERE suite_id=? ORDER BY started_at,run_id",
                               (suite_id,)).fetchall()
        else:
            rows = con.execute("SELECT payload_json FROM evaluation_runs ORDER BY started_at,run_id").fetchall()
        details = []
        counts: Counter[str] = Counter()
        for row in rows:
            run = EvaluationRun.from_dict(json.loads(row[0]))
            reviews = [EvaluationReview.from_dict(json.loads(review[0])) for review in con.execute(
                "SELECT payload_json FROM evaluation_reviews WHERE run_id=? ORDER BY created_at", (run.run_id,))]
            diagnoses = [json.loads(diagnosis[0]) for diagnosis in con.execute(
                "SELECT payload_json FROM evaluation_diagnoses WHERE run_id=? ORDER BY diagnosis_id", (run.run_id,))]
            human = [r for r in reviews if r.reviewer_type == "human" and not r.needs_adjudication]
            quality_failed = any(assessment.get("label") == "fail" for r in human for assessment in r.quality_axes.values())
            runtime_failed = run.terminal_status != "completed"
            judgment = judge_records.get(run.run_id)
            judge_status = "not_supplied" if judgment is None else judgment.get("status", judgment.get("verification_status"))
            if not isinstance(judge_status, str):
                raise EvaluationContractError("judge record has no status")
            judge_failed = judge_status == "judge_failed"
            counts["runs"] += 1
            counts["runtime_failed"] += int(runtime_failed)
            counts["deterministic_failed"] += int(any(c.status == "failed" for c in run.deterministic_checks))
            counts["human_quality_failed"] += int(quality_failed)
            counts["human_reviewed"] += int(bool(human))
            counts["human_review_pending"] += int(not human)
            counts["judge_failed"] += int(judge_failed)
            details.append({"run_id": run.run_id, "case": f"{run.case_id}@v{run.case_version}",
                            "variant": run.variant_id, "trace_id": run.trace_id,
                            "terminal_status": run.terminal_status, "runtime_failed": runtime_failed,
                            "exception_type": run.exception_type,
                            "failed_checks": [c.to_dict() for c in run.deterministic_checks if c.status == "failed"],
                            "human_quality_failed": quality_failed, "human_review_count": len(human),
                            "judge_status": judge_status, "diagnoses": diagnoses})
        return {"counts": dict(counts), "runs": details,
                "note": "Failure categories may overlap. Human quality failure requires an explicit fail label; "
                        "pending and model-assisted judgments are not accuracy."}
    finally:
        con.close()
