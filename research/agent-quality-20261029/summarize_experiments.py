"""Summarize preserved runs/reviews and reconcile cumulative physical HTTP counts."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030"
RESEARCH = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-host", action="store_true")
    parser.add_argument("--include-joint", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = {"original": ["baseline-08", "baseline-08-complete02", "baseline-rest"],
               "capacity_rank": ["candidate-08-complete", "candidate-rest"]}
    if args.include_host:
        records["capacity_and_host_rank"] = ["host-01-07", "host-08-10"]
    if args.include_joint:
        records["joint_query_prompt"] = ["joint-07", "joint-08"]
        if (OUT / "joint-controls/runs.json").exists():
            records["joint_query_prompt"].append("joint-controls")
    reviews = {}
    for path in OUT.glob("judge-*/*/review.json"):
        review = json.loads(path.read_text())
        assert review["run_id"] not in reviews, review["run_id"]
        reviews[review["run_id"]] = review
    rows = []
    counts = {}
    cases = defaultdict(list)
    for arm, directories in records.items():
        stats = Counter()
        ordinal = Counter()
        for directory in directories:
            for run in json.loads((OUT / directory / "runs.json").read_text()):
                ordinal[run["case_id"]] += 1
                review = reviews.get(run["run_id"])
                stats["attempts"] += 1
                completed = run["terminal_status"] == "completed"
                stats["delivered"] += completed
                stats["run_failed"] += not completed
                task = review["quality_axes"]["task_satisfaction"]["score"] if review else None
                reliability = review["quality_axes"]["answer_reliability"]["score"] if review else None
                if completed and review is None:
                    raise RuntimeError(f"completed run lacks a review: {run['run_id']}")
                passed = task is not None and reliability is not None and task >= 3 and reliability >= 3
                trace = next(json.loads(path.read_text()) for path in (OUT / directory / "traces").glob("*.json")
                             if json.loads(path.read_text())["trace_id"] == run["trace_id"])
                calls = [e["payload"] for e in trace["timeline"] if e["operation"] == "tool.call.started"]
                clipped_semantic = [e["payload"] for e in trace["timeline"]
                                    if e["operation"] == "runtime.tool.completed"
                                    and e["payload"]["tool_name"] == "semantic_search"
                                    and e["payload"].get("omitted_hit_messages", 0) > 0]
                stats["semantic_hit_clip_runs"] += bool(clipped_semantic)
                stats["reviewed"] += review is not None
                stats["joint_axis_threshold_pass"] += passed
                row = {"arm": arm, "case": run["case_id"], "repeat": ordinal[run["case_id"]],
                       "run_id": run["run_id"], "record_dir": directory,
                       "terminal_status": run["terminal_status"], "task": task, "reliability": reliability,
                       "joint_axis_threshold_pass": passed,
                       "semantic_hit_clip": bool(clipped_semantic),
                       "retrieval_requests": [{"tool": c["tool_name"], "request": c["request"]} for c in calls],
                       "diagnostic_types": dict(Counter(d["type"] for d in review.get("diagnostics", []))) if review else {}}
                rows.append(row)
                cases[run["case_id"]].append(row)
        counts[arm] = dict(stats)
    sends = {}
    for path in OUT.glob("**/http-events.jsonl"):
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event["event"] == "sending":
                assert event["id"] not in sends, event["id"]
                sends[event["id"]] = {**event, "record_file": str(path.relative_to(ROOT))}
    recovery = json.loads((OUT / "request-count-recovery.json").read_text())
    agent = recovery["known_total"] + sum(e["role"] == "agent" for e in sends.values())
    judge = sum(e["role"] == "judge" for e in sends.values())
    by_phase = {"R2": Counter(agent=recovery["known_total"]), "R6": Counter(), "R7": Counter()}
    for event in sends.values():
        parts = Path(event["record_file"]).parts
        phase = ("R7" if any(part.startswith(("http-joint-", "judge-joint-")) for part in parts) else
                 "R6" if any(part.startswith(("http-host-", "judge-host-")) for part in parts) else "R2")
        by_phase[phase][event["role"]] += 1
    budget = json.loads((RESEARCH / "budget.json").read_text())
    assert 250 - budget["deepseekRemaining"] == agent, (budget, agent)
    assert 32 - budget["judgeRemaining"] == judge, (budget, judge)
    result = {"interpretation": "Joint-axis >=3/3 is a Judge signal, not the historical checklist task-completion metric. Scores are provisional; no human adjudication. Failed runs have no fabricated score.",
              "counts": counts, "cases": dict(cases), "rows": rows,
              "cumulative_http": {"agent": agent, "judge": judge, "recovered_pre_meter": recovery["known_total"]},
              "http_by_phase": {phase: dict(count) for phase, count in by_phase.items()},
              "remaining": budget, "http_sends": sends}
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"counts": counts, "cumulative_http": result["cumulative_http"], "remaining": budget}, indent=2))
    for cid, case_rows in cases.items():
        print(cid, [(r["arm"], r["repeat"], r["task"], r["reliability"]) for r in case_rows])


if __name__ == "__main__":
    main()
