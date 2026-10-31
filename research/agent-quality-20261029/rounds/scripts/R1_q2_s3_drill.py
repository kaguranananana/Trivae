"""Q2 follow-up: classify S3_projection_gap facts — is the GT message inside the accepted
chunk's matching core [start,end], only in the parent range, or outside both?

Reads replay-facts.json + replay-calls.json and the semantic clone (read-only) for chunk
ranges. Also Q7 follow-up: for tool calls with omitted hits, timestamps of the omitted tail
(last N of replayed expanded order) vs the call's resolved window.
"""
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"
NUM = re.compile(r"(\d{15,22})")

facts = json.load(open(OUT / "replay-facts.json"))
calls = json.load(open(OUT / "replay-calls.json"))

con = sqlite3.connect(f"file:/tmp/trivae-r1-sem.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row
chunk_ranges = {}
for row in con.execute("SELECT chunk_id, start_message_id, end_message_id, parent_start_message_id, parent_end_message_id FROM semantic_chunks"):
    chunk_ranges[row["chunk_id"]] = (row["start_message_id"], row["end_message_id"],
                                     row["parent_start_message_id"], row["parent_end_message_id"])
con.close()

canon = sqlite3.connect(f"file:{ROOT}/data/evaluation/frozen-20261028-validated/trivae.sqlite3?mode=ro", uri=True)
canon.row_factory = sqlite3.Row


def nums(s):
    return set(NUM.findall(s or ""))


def ts_of(iid):
    r = canon.execute("SELECT timestamp FROM messages WHERE internal_message_id=?", (iid,)).fetchone()
    if r:
        return r["timestamp"]
    r = canon.execute("SELECT timestamp FROM forwarded_messages WHERE internal_message_id=?", (iid,)).fetchone()
    return r["timestamp"] if r else None


# ---- S3 drill ------------------------------------------------------------
s3_rows = []
sub = Counter()
for f in facts:
    if f["layer"] != "S3_projection_gap":
        continue
    # find the semantic call(s) for this run that had covering chunks
    run_calls = [c for c in calls if c.get("label") == f"{f['arm']}{f['run_idx']}-{f['case']}" and c.get("tool") == "semantic"]
    done = False
    for c in run_calls:
        if done:
            break
        for pr in c.get("pool_rows", []):
            covering = pr["chunk_id"] in c.get("accepted_chunk_ids", [])
            if not covering:
                continue
            cr = chunk_ranges.get(pr["chunk_id"])
            if not cr:
                continue
            core_s, core_e, par_s, par_e = cr
            gt_hit = None
            for eid in f["evidence"]:
                tn = nums(eid)
                ps_n = int(next(iter(nums(par_s)))) if len(nums(par_s)) == 1 else None
                pe_n = int(next(iter(nums(par_e)))) if len(nums(par_e)) == 1 else None
                cs_n = int(next(iter(nums(core_s)))) if len(nums(core_s)) == 1 else None
                ce_n = int(next(iter(nums(core_e)))) if len(nums(core_e)) == 1 else None
                v = int(next(iter(tn)))
                in_parent = ps_n is not None and pe_n is not None and ps_n <= v <= pe_n
                in_core = cs_n is not None and ce_n is not None and cs_n <= v <= ce_n
                if in_parent or in_core:
                    gt_hit = (in_parent, in_core)
                    break
            if gt_hit is None:
                continue
            in_parent, in_core = gt_hit
            if in_core:
                label = "core_contains_gt_but_not_returned"
            elif in_parent:
                label = "gt_in_parent_outside_core"
            else:
                label = "gt_outside_parent"
            sub[label] += 1
            s3_rows.append({"case": f["case"], "arm": f["arm"], "idx": f["run_idx"],
                            "fact": f["fact_id"], "chunk": pr["chunk_id"], "dense_rank": pr["dense_rank"],
                            "class": label,
                            "core": [core_s, core_e], "parent": [par_s, par_e]})
            done = True
            break

# ---- Q7: omitted tail timestamps -----------------------------------------
omitted_tail = []
canon2 = canon
for c in calls:
    oh = c.get("omitted_hit_messages") or 0
    if not oh:
        continue
    exp = c.get("expanded_ids") or []
    tail = exp[-oh:] if oh <= len(exp) else exp
    tss = []
    for mid in tail:
        t = ts_of(mid)
        if t:
            tss.append(int(t))
    rs, re_ = c.get("resolved_start"), c.get("resolved_end")
    in_win = sum(1 for t in tss if (rs is None or t >= rs) and (re_ is None or t < re_))
    omitted_tail.append({"label": c.get("label"), "tool": c.get("tool"),
                         "omitted": oh, "tail_with_ts": len(tss),
                         "tail_ts_in_resolved_window": in_win,
                         "tail_ts_min": min(tss) if tss else None,
                         "tail_ts_max": max(tss) if tss else None,
                         "resolved_start": rs, "resolved_end": re_})

out = {
    "s3_subclasses": dict(sub),
    "s3_rows": s3_rows,
    "q7_omitted_tail": omitted_tail,
}
json.dump(out, open(OUT / "q2-q7-followup.json", "w"), ensure_ascii=False, indent=1, default=str)
print("S3 subclasses:", dict(sub))
for r in s3_rows:
    print("  ", r["case"], r["arm"] + str(r["idx"]), r["fact"], "rank", r["dense_rank"], r["class"])
print()
print("omitted-tail windows (Q7):")
for r in omitted_tail:
    fmt = lambda t: datetime.fromtimestamp(t / 1000, tz=timezone.utc).strftime("%m-%d") if t else "?"
    print(f"  {r['label']} {r['tool']} omitted={r['omitted']} tail_ts {fmt(r['tail_ts_min'])}..{fmt(r['tail_ts_max'])} in_window={r['tail_ts_in_resolved_window']}/{r['tail_with_ts']}")
