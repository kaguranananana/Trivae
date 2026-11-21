"""Resolve R1's numeric interval S3 labels against exact canonical range membership."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from functools import lru_cache
from pathlib import Path

from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = Path(__file__).resolve().parent
OUTPUT = ROOT / "data/evaluation/agent-quality-codex-20261030/exact-projection-gaps.json"


def main():
    rows = json.loads((RESEARCH / "rounds/outputs/q2-s3-refined.json").read_text())
    facts = json.loads((RESEARCH / "rounds/outputs/replay-facts.json").read_text())
    paired = json.loads((OUTPUT.parent / "semantic-rank-candidate.json").read_text())
    corrections = {r["original"]: r["resolved"] for r in paired["gt_corrections"]}
    repo = SQLiteCanonicalReadRepository(ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3")
    repo.read_message_range = lru_cache(maxsize=None)(repo.read_message_range)
    sem = sqlite3.connect(f"file:{ROOT}/data/evaluation/frozen-20261028-validated/trivae.semantic.sqlite3?mode=ro", uri=True)
    sem.row_factory = sqlite3.Row
    counts = Counter()
    result = []
    for row in rows:
        fact = next(f for f in facts if (f["case"], f["fact_id"], f["arm"], f["run_idx"]) ==
                    (row["case"], row["fact"], row["arm"], row["idx"]))
        targets = {corrections.get(mid, mid) for mid in fact["evidence"]}
        chunk = sem.execute("SELECT * FROM semantic_chunks WHERE chunk_id=?", (row["chunk"],)).fetchone()
        core = {m.internal_message_id for m in repo.read_message_range(
            chunk["session_id"], chunk["start_message_id"], chunk["end_message_id"], chunk["message_count"],
        )}
        parent = {m.internal_message_id for m in repo.read_message_range(
            chunk["session_id"], chunk["parent_start_message_id"], chunk["parent_end_message_id"], 1000,
        )}
        calls = [c for c in paired["calls"] if c["label"] == f"{row['arm']}{row['idx']}-{row['case']}"
                 and any(h["chunk_id"] == row["chunk"] for h in c["cores"])]
        assert calls
        returned = {mid for c in calls for mid in c["old_ids"]}
        if targets & core:
            category = "exact_core_returned" if targets & core & returned else "exact_core_capacity_loss"
        elif targets & parent:
            category = "parent_only_not_selected_child"
        else:
            category = "numeric_interval_false_positive"
        counts[category] += 1
        result.append({"case": row["case"], "arm": row["arm"], "idx": row["idx"], "fact": row["fact"],
                       "old_numeric_class": row["class"], "exact_class": category,
                       "exact_core_targets": sorted(targets & core), "exact_parent_targets": sorted(targets & parent)})
    with OUTPUT.open("x") as stream:
        json.dump({"counts": dict(counts), "rows": result}, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(counts), indent=2))


if __name__ == "__main__":
    main()
