"""Check actual first model input for the query-time anchor, not just system instructions."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030/query-time-anchor-audit.json"


def main():
    study = json.loads((BASE / "study-data.json").read_text())
    sources = {}
    for arm in ("a", "b"):
        for item in json.loads((BASE / f"source-map-{arm}.json").read_text())["selected"]:
            sources[item["run_id"]] = item["source"]
    rows = []
    counts = Counter()
    for cid, case in study["cases"].items():
        for arm, runs in case["runs"].items():
            for idx, run in enumerate(runs):
                path = (run["trace"]["trace_path"] if run["source"] == "new-agent-run"
                        else sources[run["run_id"]]["trace_record"])
                events = json.loads((ROOT / path).read_text())["timeline"]
                first = next(e for e in events if e["operation"] == "model.turn" and e["phase"] == "started")
                inputs = first["payload"].get("model_visible_context", [])
                anchors = [item for item in inputs if isinstance(item, dict) and
                           "2026-10-28T12:00:00+08:00" in str(item.get("content", ""))]
                counts["runs"] += 1
                counts["anchor_observed_in_first_model_input"] += bool(anchors)
                rows.append({"case": cid, "arm": arm, "idx": idx, "run_id": run["run_id"],
                             "trace_path": path, "anchor_observed": bool(anchors), "anchor": anchors})
    with OUT.open("x") as stream:
        json.dump({"counts": dict(counts), "rows": rows}, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(counts), indent=2))


if __name__ == "__main__":
    main()
