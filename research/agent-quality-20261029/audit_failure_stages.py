"""Separate frozen semantic coverage labels from exact source presence in saved runs."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from audit_measurements import source_ids

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path(__file__).resolve().parent
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030"


def main():
    study = json.loads((BASE / "study-data.json").read_text())
    coverage = json.loads((BASE / "coverage-assessments.json").read_text())
    calls = json.loads((RESEARCH / "rounds/outputs/replay-calls.json").read_text())
    paired = json.loads((OUT / "semantic-rank-candidate.json").read_text())
    corrections = {c["original"]: c["resolved"] for c in paired["gt_corrections"]}
    by_run = {}
    for c in calls:
        by_run.setdefault(c["label"], set()).update(c.get("expanded_ids", []))
    counts = {arm: Counter() for arm in ("A", "B")}
    rows = []
    for case in coverage["cases"]:
        cid = case["case_id"]
        for fact in case["facts"]:
            if fact["id"] in coverage["conditional_not_applicable"]:
                continue
            targets = {corrections.get(mid, mid) for mid in fact["evidence_ids"]}
            for arm, runs in study["cases"][cid]["runs"].items():
                for idx, run in enumerate(runs):
                    ids = set(source_ids({"sources": run["evidence_sources"],
                                          "answer_cited_messages": run["answer_cited_messages"]}))
                    in_answer = bool(ids & targets)
                    in_capability = bool(targets & by_run.get(f"{arm}{idx}-{cid}", set()))
                    covered = fact["status"][f"{arm}{idx + 1}"] == "covered"
                    if covered:
                        category = "semantically_covered"
                    elif not targets:
                        category = "uncovered_criterion_without_fixed_target_ids"
                    elif in_answer:
                        category = "uncovered_despite_target_in_answer_sources"
                    elif in_capability:
                        category = "uncovered_target_in_capability_visibility_unknown"
                    else:
                        category = "uncovered_target_not_observed_in_replayed_searches"
                    counts[arm][category] += 1
                    rows.append({"case": cid, "fact": fact["id"], "arm": arm, "idx": idx,
                                 "category": category, "target_in_final_sources": in_answer,
                                 "target_in_replayed_capability": in_capability})
    with (OUT / "failure-stage-audit-v2.json").open("x") as stream:
        json.dump({"unit": "applicable criterion/run pairs, not independent cases",
                   "counts": {arm: dict(c) for arm, c in counts.items()}, "rows": rows,
                   "limits": "Capability includes the 166 saved/replayed lexical+semantic calls; explicit context tools and cropped bodies may be unknown. Exact target-ID absence does not exclude alternative supporting evidence. Original coverage labels remain provisional."},
                  stream, ensure_ascii=False, indent=2)
    print(json.dumps({arm: dict(c) for arm, c in counts.items()}, indent=2))


if __name__ == "__main__":
    main()
