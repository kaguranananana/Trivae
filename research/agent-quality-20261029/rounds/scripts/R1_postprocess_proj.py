"""Post-process replay outputs: attach runtime projection counts (projected/omitted/truncated
+ budget) to each replayed call, then re-classify fact layers with real projection windows.

Reason: trace tool.call.started payloads carry no tool_call_id; the id lives on
runtime.tool.started. The main replay therefore recorded projection fields as None and used
an optimistic visibility default. This script pairs tool.call.started <-> runtime.tool.started
by chronological order, re-joins runtime.tool.completed, and re-runs the fact classifier.

Zero model-budget; read-only.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
sys.path.insert(0, str(ROOT / "src"))
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
FROZEN = ROOT / "data/evaluation/frozen-20261028-validated"
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"

NUM_RE = re.compile(r"(\d{15,22})")


def nums(s):
    return set(NUM_RE.findall(s or ""))


def main() -> None:
    import sqlite3

    study = json.load(open(BASE / "study-data.json"))
    harness_maps = {}
    for smf in ("source-map-a.json", "source-map-b.json"):
        sm = json.load(open(BASE / smf))
        for sel in sm["selected"]:
            harness_maps[sel["run_id"]] = sel["source"]

    runs = []
    for cid, case in study["cases"].items():
        for arm, runlist in case["runs"].items():
            for idx, r in enumerate(runlist):
                if r["source"] == "new-agent-run":
                    trace_path = ROOT / r["trace"]["trace_path"]
                    runs_json = trace_path.parent.parent / "runs.json"
                else:
                    tr = harness_maps[r["run_id"]]["trace_record"]
                    trace_path = ROOT / tr
                    runs_json = ROOT / tr.split("/traces/")[0] / "runs.json"
                runs.append({"case": cid, "arm": arm, "idx": idx, "run": r,
                             "trace_path": trace_path, "runs_json": runs_json})

    calls = json.load(open(OUT / "replay-calls.json"))
    # index call records by label preserving order
    by_label = {}
    for c in calls:
        by_label.setdefault(c["label"], []).append(c)

    # attach projection payloads
    for entry in runs:
        cid, arm, idx = entry["case"], entry["arm"], entry["idx"]
        label = f"{arm}{idx}-{cid}"
        recs = by_label.get(label, [])
        if not recs:
            continue
        tl = json.load(open(entry["trace_path"]))["timeline"]
        starts = [e["payload"] for e in tl if e["operation"] == "tool.call.started"]
        rt_starts = [e["payload"] for e in tl if e["operation"] == "runtime.tool.started"]
        rt_done = {p.get("tool_call_id"): p for p in
                   (e["payload"] for e in tl if e["operation"] == "runtime.tool.completed")}
        # 1:1 chronological pairing of the two started streams
        pairs = []
        si = ri = 0
        while si < len(starts) and ri < len(rt_starts):
            s, rt = starts[si], rt_starts[ri]
            if s.get("tool_name") == rt.get("tool_name"):
                pairs.append((s, rt))
                si += 1
                ri += 1
            else:
                # transient mismatch: advance the stream whose next event matches later
                si += 1
        j = 0
        for c in recs:
            if "error" in c:
                continue
            while j < len(pairs) and pairs[j][0].get("tool_name") not in (
                    "lexical_search", "semantic_search", "search_messages"):
                j += 1
            if j >= len(pairs):
                break
            s, rt = pairs[j]
            j += 1
            want = {"lexical": {"lexical_search", "search_messages"},
                    "semantic": {"semantic_search"}}.get(c.get("tool"), set())
            if s.get("tool_name") not in want:
                j -= 1
                continue
            proj = rt_done.get(rt.get("tool_call_id"), {})
            c["projection_truncated"] = proj.get("projection_truncated")
            c["projected_messages"] = proj.get("projected_messages")
            c["omitted_hit_messages"] = proj.get("omitted_hit_messages")
            c["omitted_context_messages"] = proj.get("omitted_context_messages")
            c["remaining_budget"] = (proj.get("tool_result_budget") or {}).get(
                "remaining_run_tool_evidence_budget_after_call")

    json.dump(calls, open(OUT / "replay-calls.json", "w"), ensure_ascii=False, default=str)
    n_proj = sum(1 for c in calls if c.get("projected_messages") is not None)
    print(f"projection attached to {n_proj}/{len(calls)} calls")

    # ---- re-classify fact layers with real projection windows --------------
    import sqlite3
    repo_con = sqlite3.connect(f"file:{FROZEN}/trivae.sqlite3?mode=ro", uri=True)
    repo_con.row_factory = sqlite3.Row

    checklist = json.load(open(BASE / "fact-checklist.json"))
    facts_by_case = {}
    for case in checklist["cases"]:
        cid = case["case_id"]
        fl = []
        for cr in case["criteria"]:
            resolved = {}
            for eid in cr["evidence"]:
                row = repo_con.execute(
                    "SELECT timestamp, content_text, session_id FROM messages WHERE internal_message_id=?",
                    (eid,)).fetchone()
                if row:
                    resolved[eid] = {"kind": "message", "timestamp": row["timestamp"],
                                     "session_id": row["session_id"], "content": row["content_text"] or ""}
                    continue
                row = repo_con.execute(
                    "SELECT timestamp, content_text, session_id FROM forwarded_messages WHERE internal_message_id=?",
                    (eid,)).fetchone()
                if row:
                    resolved[eid] = {"kind": "forwarded", "timestamp": row["timestamp"],
                                     "session_id": row["session_id"], "content": row["content_text"] or ""}
                    continue
                smid = eid.split(":")[2] if eid.startswith("qq:") and "#" not in eid else None
                if smid:
                    row = repo_con.execute(
                        "SELECT internal_message_id, session_id, timestamp, content_text FROM messages "
                        "WHERE source_message_id=?", (smid,)).fetchone()
                    if row:
                        resolved[eid] = {"kind": "message", "timestamp": row["timestamp"],
                                         "session_id": row["session_id"],
                                         "content": row["content_text"] or "",
                                         "actual_internal_id": row["internal_message_id"]}
                        continue
                resolved[eid] = {"kind": "unresolved"}
            fl.append({"fact_id": cr["id"], "evidence": cr["evidence"], "resolved": resolved})
        facts_by_case[cid] = fl

    def gt_ids(fact):
        out = set()
        for eid, m in fact["resolved"].items():
            if m["kind"] in ("message", "forwarded"):
                out.add(eid)
                if m.get("actual_internal_id"):
                    out.add(m["actual_internal_id"])
        return out

    def id_match(tids, cand):
        if cand in tids:
            return True
        cn = nums(cand)
        return any(cn & nums(t) for t in tids)

    # recorded direct hits per label+call order (from run records, same as replay)
    rec_calls_by_label = {}
    for entry in runs:
        cid, arm, idx = entry["case"], entry["arm"], entry["idx"]
        label = f"{arm}{idx}-{cid}"
        try:
            record_runs = json.load(open(entry["runs_json"]))
        except FileNotFoundError:
            record_runs = []
        rec = next((x for x in record_runs if x["run_id"] == entry["run"]["run_id"]), None)
        rec_calls_by_label[label] = list(rec["query_result"]["retrieval_calls"]["calls"]) if rec else []

    def adoption(r, tids):
        ev_ids = set()
        for e in r.get("evidence_sources") or []:
            if isinstance(e, dict):
                es = e.get("sources") or []
                es = es.get("sources", []) if isinstance(es, dict) else es
                for s in es or []:
                    ref = s.get("reference", {}) if isinstance(s, dict) else {}
                    if ref.get("internal_message_id"):
                        ev_ids.add(ref["internal_message_id"])
        cited = set()
        for m in r.get("answer_cited_messages") or []:
            if isinstance(m, str):
                cited.add(m)
            elif isinstance(m, dict) and m.get("internal_message_id"):
                cited.add(m["internal_message_id"])
        return any(id_match(tids, x) for x in ev_ids | cited)

    fact_records = []
    for entry in runs:
        cid, arm, idx = entry["case"], entry["arm"], entry["idx"]
        r = entry["run"]
        label = f"{arm}{idx}-{cid}"
        run_calls = by_label.get(label, [])
        rec_list = rec_calls_by_label[label]
        for fact in facts_by_case[cid]:
            tids = gt_ids(fact)
            meta0 = next((m for m in fact["resolved"].values() if m.get("timestamp")), {})
            ts_val = meta0.get("timestamp")
            content = meta0.get("content") or ""
            adopted = adoption(r, tids)
            in_recorded_dh = any(id_match(tids, d["internal_message_id"])
                                 for c in rec_list for d in (c.get("direct_hits") or []))
            layers = []
            if not run_calls:
                layers.append("L0_no_retrieval_call")
            for c in run_calls:
                if "error" in c:
                    layers.append("ERR")
                    continue
                if c["tool"] == "lexical":
                    fr = None
                    for tid in tids:
                        r1 = c["full_rank"].get(tid)
                        if r1 is None:
                            tn = nums(tid)
                            for i, mid in enumerate(c["full_rank"]):
                                if nums(mid) & tn:
                                    r1 = i + 1
                                    break
                        if r1 is not None:
                            fr = r1 if fr is None else min(fr, r1)
                    if fr is None:
                        if ts_val and c.get("resolved_start") and ts_val < c["resolved_start"]:
                            lay = "L0_time_scope"
                        elif ts_val and c.get("resolved_end") and ts_val >= c["resolved_end"]:
                            lay = "L0_time_scope"
                        else:
                            terms = [t.casefold() for t in c.get("terms", [])]
                            kw = (c.get("keyword") or "").casefold()
                            hit = any(t and t in content.casefold() for t in terms) or (kw and kw in content.casefold())
                            lay = "L2_fts_miss_with_overlap" if hit else "L1_no_lexical_overlap"
                        layers.append(lay)
                    elif fr > (c.get("limit") or 20):
                        layers.append("L3_window_truncated")
                    else:
                        pos = None
                        for tid in tids:
                            if tid in c["expanded_ids"]:
                                pos = c["expanded_ids"].index(tid)
                                break
                        if pos is None:
                            tn_all = set().union(*(nums(t) for t in tids))
                            for i, mid in enumerate(c["expanded_ids"]):
                                if nums(mid) & tn_all:
                                    pos = i
                                    break
                        vis = True
                        if pos is not None and c.get("projection_truncated"):
                            vis = pos < (c.get("projected_messages") or 0)
                        layers.append("L5_returned" if vis else "L4_budget_crop")
                else:
                    covering = []
                    for pr in c.get("pool_rows", []):
                        ps, pe = nums(pr["parent_start"] or ""), nums(pr["parent_end"] or "")
                        for tid in tids:
                            tn = nums(tid)
                            ps_n = int(next(iter(ps))) if len(ps) == 1 else None
                            pe_n = int(next(iter(pe))) if len(pe) == 1 else None
                            tid_n = [int(x) for x in tn]
                            cover = ps_n is not None and pe_n is not None and tid_n and ps_n <= tid_n[0] <= pe_n
                            if cover or (tn & (ps | pe | nums(pr["chunk_id"]))):
                                covering.append((pr["chunk_id"], pr["dense_rank"]))
                                break
                    if not covering:
                        layers.append("S1_pool_miss")
                        continue
                    accepted = any(cid_ in c["accepted_chunk_ids"] for cid_, _ in covering)
                    if not accepted:
                        layers.append("S2_rank_cut")
                        continue
                    pos = None
                    for tid in tids:
                        if tid in c["expanded_ids"]:
                            pos = c["expanded_ids"].index(tid)
                            break
                    if pos is None:
                        tn_all = set().union(*(nums(t) for t in tids))
                        for i, mid in enumerate(c["expanded_ids"]):
                            if nums(mid) & tn_all:
                                pos = i
                                break
                    if pos is None:
                        layers.append("S3_projection_gap")
                    else:
                        vis = True
                        if c.get("projection_truncated"):
                            vis = pos < (c.get("projected_messages") or 0)
                        layers.append("L5_returned" if vis else "L4_budget_crop")
            if adopted:
                final_layer = "L6_adopted"
            elif in_recorded_dh or "L5_returned" in layers:
                final_layer = "L5_returned_not_adopted"
            elif "L4_budget_crop" in layers:
                final_layer = "L4_budget_crop"
            elif "S3_projection_gap" in layers:
                final_layer = "S3_projection_gap"
            elif "S2_rank_cut" in layers:
                final_layer = "S2_rank_cut"
            elif "S1_pool_miss" in layers:
                final_layer = "S1_pool_miss"
            elif "L3_window_truncated" in layers:
                final_layer = "L3_window_truncated"
            elif "L2_fts_miss_with_overlap" in layers:
                final_layer = "L2_fts_miss_with_overlap"
            elif "L1_no_lexical_overlap" in layers:
                final_layer = "L1_no_lexical_overlap"
            elif "L0_time_scope" in layers:
                final_layer = "L0_time_scope"
            elif "L0_no_retrieval_call" in layers:
                final_layer = "L0_no_retrieval_call"
            elif "ERR" in layers:
                final_layer = "ERR"
            else:
                final_layer = "UNCLASSIFIED"
            fact_records.append({"case": cid, "arm": arm, "run_idx": idx,
                                 "fact_id": fact["fact_id"], "evidence": fact["evidence"],
                                 "layer": final_layer, "n_calls": len(run_calls)})

    json.dump(fact_records, open(OUT / "replay-facts.json", "w"), ensure_ascii=False, default=str)
    print("fact layers (re-classified with real projection windows):")
    for k, v in Counter(f["layer"] for f in fact_records).most_common():
        print(f"  {k}: {v}")

    # ---- Q7 omitted tail ----------------------------------------------------
    omitted_tail = []
    for c in calls:
        oh = c.get("omitted_hit_messages") or 0
        if not oh:
            continue
        exp = c.get("expanded_ids") or []
        tail = exp[-oh:] if oh <= len(exp) else exp
        tss = []
        for mid in tail:
            t = repo_con.execute(
                "SELECT timestamp FROM messages WHERE internal_message_id=?", (mid,)).fetchone()
            if not t:
                t = repo_con.execute(
                    "SELECT timestamp FROM forwarded_messages WHERE internal_message_id=?", (mid,)).fetchone()
            if t:
                tss.append(int(t["timestamp"]))
        rs, re_ = c.get("resolved_start"), c.get("resolved_end")
        in_win = sum(1 for t in tss if (rs is None or t >= rs) and (re_ is None or t < re_))
        omitted_tail.append({"label": c.get("label"), "tool": c.get("tool"), "omitted": oh,
                             "tail_with_ts": len(tss), "tail_ts_in_resolved_window": in_win,
                             "tail_ts_min": min(tss) if tss else None,
                             "tail_ts_max": max(tss) if tss else None})
    json.dump(omitted_tail, open(OUT / "q7-omitted-tail.json", "w"), ensure_ascii=False, default=str)
    print(f"omitted-tail calls: {len(omitted_tail)}")
    for x in omitted_tail[:12]:
        fmt = lambda t: datetime.fromtimestamp(t / 1000, tz=__import__("datetime").timezone.utc).strftime("%m-%d") if t else "?"
        print(f"  {x['label']} {x['tool']} omitted={x['omitted']} tail {fmt(x['tail_ts_min'])}..{fmt(x['tail_ts_max'])}")


if __name__ == "__main__":
    from datetime import datetime
    main()
