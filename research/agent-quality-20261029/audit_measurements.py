"""Audit existing measurements without changing historical annotations or requesting models."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path(__file__).resolve().parent
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"


def source_ids(value):
    if isinstance(value, dict):
        if isinstance(value.get("internal_message_id"), str):
            yield value["internal_message_id"]
        for key, child in value.items():
            if key in {"message_ids", "answer_cited_messages"} and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from source_ids(child)
    elif isinstance(value, list):
        for item in value:
            yield from source_ids(item)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    study = json.loads((BASE / "study-data.json").read_text())
    coverage = json.loads((BASE / "coverage-assessments.json").read_text())
    replay = json.loads((RESEARCH / "rounds/outputs/replay-facts.json").read_text())
    counts = Counter()
    citation_rows = []
    # Explicit analyst categorization of the 52 existing combined-label diagnostics.
    # Keys are case number / arm+zero-based run / zero-based temporal diagnostic.
    historical_now = {"04-A0-0", "04-A1-0", "04-B0-0", "04-B1-0", "08-A1-1", "08-B0-0", "08-B1-0"}
    wrong_source_date = {"02-B1-1", "08-B1-1", "09-A1-0", "11-A0-0"}
    temporal = []
    for cid, case in study["cases"].items():
        case_no = cid.split("-")[1]
        for arm, runs in case["runs"].items():
            for idx, run in enumerate(runs):
                diags = [d for d in run["review_diagnostics"] if d["type"] == "temporal_or_scope_error"]
                for j, d in enumerate(diags):
                    key = f"{case_no}-{arm}{idx}-{j}"
                    category = ("historical_to_current" if key in historical_now else
                                "wrong_source_date" if key in wrong_source_date else "entity_task_population_scope")
                    counts[category] += 1
                    temporal.append({"key": key, "category": category, "diagnostic": d})
    for fact in replay:
        run = study["cases"][fact["case"]]["runs"][fact["arm"]][fact["run_idx"]]
        ids = set(source_ids({"sources": run["evidence_sources"], "answer_cited_messages": run["answer_cited_messages"]}))
        exact = bool(set(fact["evidence"]) & ids)
        if fact["layer"] == "L6_adopted":
            counts["r1_l6"] += 1
            counts["r1_l6_exact_id_intersection"] += exact
            citation_rows.append({"case": fact["case"], "arm": fact["arm"], "idx": fact["run_idx"],
                                  "fact": fact["fact_id"], "exact_id_intersection": exact})
    case02 = next(c for c in coverage["cases"] if c["case_id"] == "cap1-02-regression")
    unchanged_02b = {
        "old_status": case02["facts"][1]["status"],
        "rationale_issue": "A2 claim-7 and B1 claim-6 mention turning old login behavior into a fast test; old rationale says no answer mentions it.",
        "attribution_issue": "A2 calls it a group practice; B1 calls it another practice. Neither clearly marks it as a forwarded recommendation, which the frozen criterion requires.",
        "decision": "Keep the historical numeric status; annotate the inaccurate rationale separately. No quality uplift claimed.",
    }
    result = {"classification": "Codex analyst-assisted audit, provisional; no human adjudication",
              "counts": dict(counts), "temporal_diagnostics": temporal, "r1_l6_audit": citation_rows,
              "criterion_02b": unchanged_02b,
              "token_calibration": "R1 uses a first-claim structural multiplier and median substitution; not an exact tokenizer measurement. Do not use 1.31 as a budget correction coefficient."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(counts), indent=2))


if __name__ == "__main__":
    main()
