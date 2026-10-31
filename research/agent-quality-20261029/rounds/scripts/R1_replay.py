"""R1 Q1-step1: replay real retrieval queries of eval runs against the frozen snapshot.

Zero model-budget: embeddings are local (sentence-transformers Qwen3-Embedding-0.6B).
Canonical DB: read-only connection to the frozen master (SQLiteCanonicalReadRepository is
read-only). Semantic DB: APFS clone at /tmp/trivae-r1-sem.sqlite3 (SQLiteSemanticIndex opens
rw); master freeze files untouched.

Outputs: rounds/outputs/replay-calls.json (per call), replay-facts.json (per fact per run
failure layer), replay-summary.json (aggregates).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
sys.path.insert(0, str(ROOT / "src"))

BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
FROZEN = ROOT / "data/evaluation/frozen-20261028-validated"
SEMANTIC_CLONE = Path("/tmp/trivae-r1-sem.sqlite3")
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"

NUM_RE = re.compile(r"(\d{15,22})")


def nums(s: str) -> set[str]:
    return set(NUM_RE.findall(s))


def main() -> None:
    from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput, SemanticSearchInput
    from trivae.capabilities.search_messages import SearchMessagesCapability
    from trivae.capabilities.semantic_search import SemanticSearchCapability
    from trivae.retrieval.lexical import LexicalRetrieval
    from trivae.retrieval.semantic.embedding import SentenceTransformerEmbeddingProvider
    from trivae.retrieval.semantic.index import SQLiteSemanticIndex
    from trivae.retrieval.semantic.retrieval import SemanticRetrieval
    from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository

    study = json.load(open(BASE / "study-data.json"))
    checklist = json.load(open(BASE / "fact-checklist.json"))

    harness_maps: dict[str, dict] = {}
    for smf in ("source-map-a.json", "source-map-b.json"):
        sm = json.load(open(BASE / smf))
        for sel in sm["selected"]:
            harness_maps[sel["run_id"]] = sel["source"]

    repo = SQLiteCanonicalReadRepository(FROZEN / "trivae.sqlite3")
    store = SQLiteSemanticIndex(SEMANTIC_CLONE)
    provider = SentenceTransformerEmbeddingProvider()
    sem_retrieval = SemanticRetrieval(repo, store, provider, database_identity="trivae.sqlite3")
    lex_cap = SearchMessagesCapability(LexicalRetrieval(repo))
    sem_cap = SemanticSearchCapability(sem_retrieval)
    scope = ExecutionScope(max_results=100)

    t0 = time.time()
    print("loading embedding model...", flush=True)
    provider.preload()
    print(f"model loaded in {time.time()-t0:.1f}s", flush=True)

    # ---- GT facts per case -------------------------------------------------
    facts_by_case: dict[str, list[dict]] = {}
    for case in checklist["cases"]:
        cid = case["case_id"]
        fl = []
        for cr in case["criteria"]:
            eids = cr["evidence"]
            resolved = {}
            for eid in eids:
                row = repo.read_message_by_id(eid)
                if row is not None:
                    full = repo._connection.execute(
                        "SELECT content_text FROM messages WHERE internal_message_id = ?", (eid,)
                    ).fetchone()
                    resolved[eid] = {
                        "kind": "message", "session_id": row.session_id, "timestamp": row.timestamp,
                        "content": (full["content_text"] if full else "") or "",
                    }
                    continue
                r = repo._connection.execute(
                    "SELECT session_id, timestamp, content_text, root_message_id, source_message_id "
                    "FROM forwarded_messages WHERE internal_message_id = ?", (eid,)
                ).fetchone()
                if r is not None:
                    resolved[eid] = {
                        "kind": "forwarded", "session_id": r["session_id"], "timestamp": r["timestamp"],
                        "root": r["root_message_id"], "source_message_id": r["source_message_id"],
                        "content": r["content_text"] or "",
                    }
                    continue
                # checklist id may carry a wrong group prefix; fall back to source_message_id
                smid = eid.split(":")[2] if eid.startswith("qq:") and "#" not in eid else None
                if smid:
                    r2 = repo._connection.execute(
                        "SELECT internal_message_id, session_id, timestamp, content_text "
                        "FROM messages WHERE source_message_id = ?", (smid,)
                    ).fetchone()
                    if r2 is not None:
                        resolved[eid] = {
                            "kind": "message", "session_id": r2["session_id"],
                            "timestamp": r2["timestamp"], "content": r2["content_text"] or "",
                            "actual_internal_id": r2["internal_message_id"], "checklist_prefix_mismatch": True,
                        }
                        continue
                resolved[eid] = {"kind": "unresolved"}
            fl.append({"fact_id": cr["id"], "requirement": cr["requirement"],
                       "evidence": eids, "resolved": resolved})
        facts_by_case[cid] = fl

    unresolved = [(cid, f["fact_id"], eid) for cid, fl in facts_by_case.items()
                  for f in fl for eid, m in f["resolved"].items() if m["kind"] == "unresolved"]
    prefix_mismatch = [(cid, f["fact_id"], eid) for cid, fl in facts_by_case.items()
                       for f in fl for eid, m in f["resolved"].items() if m.get("checklist_prefix_mismatch")]
    if unresolved:
        print("UNRESOLVED GT evidence:", unresolved)
    if prefix_mismatch:
        print("CHECKLIST PREFIX MISMATCH (resolved via source_message_id):", prefix_mismatch)

    def gt_ids(fact: dict) -> set[str]:
        out = set()
        for eid, m in fact["resolved"].items():
            if m["kind"] not in ("message", "forwarded"):
                continue
            out.add(eid)
            if m.get("actual_internal_id"):
                out.add(m["actual_internal_id"])
        return out

    def id_match(target_ids: set[str], candidate: str) -> bool:
        if candidate in target_ids:
            return True
        cn = nums(candidate)
        return any(cn & nums(tid) for tid in target_ids)

    # ---- enumerate runs ----------------------------------------------------
    runs = []
    for cid, case in study["cases"].items():
        for arm, runlist in case["runs"].items():
            for idx, r in enumerate(runlist):
                if r["source"] == "new-agent-run":
                    trace_path = ROOT / r["trace"]["trace_path"]
                    src = trace_path.parent.parent
                    runs_json = src / "runs.json"
                else:
                    tr = harness_maps[r["run_id"]]["trace_record"]
                    trace_path = ROOT / tr
                    runs_json = ROOT / tr.split("/traces/")[0] / "runs.json"
                runs.append({"case": cid, "arm": arm, "idx": idx, "run": r,
                             "trace_path": trace_path, "runs_json": runs_json})
    print(f"{len(runs)} runs to replay", flush=True)
    smoke = int(os.environ.get("R1_SMOKE", "0"))
    if smoke:
        runs = runs[:smoke]
        print(f"SMOKE mode: only {len(runs)} runs", flush=True)

    call_records: list[dict] = []
    fact_records: list[dict] = []
    sem_stats = Counter()
    fidelity = {"lexical_checked": 0, "lexical_match": 0, "semantic_checked": 0, "semantic_match": 0,
                "lex_mismatch_detail": [], "sem_mismatch_detail": []}

    for ri, entry in enumerate(runs):
        cid, arm, idx = entry["case"], entry["arm"], entry["idx"]
        r = entry["run"]
        label = f"{arm}{idx}-{cid}"
        trace = json.load(open(entry["trace_path"]))
        tl = trace["timeline"]
        try:
            record_runs = json.load(open(entry["runs_json"]))
        except FileNotFoundError:
            record_runs = []
        rec = next((x for x in record_runs if x["run_id"] == r["run_id"]), None)
        rec_calls = {}
        rec_ordered = []
        if rec is not None:
            for c in rec["query_result"]["retrieval_calls"]["calls"]:
                rec_calls[c["tool_call_id"]] = c
                rec_ordered.append(c)
        rec_pos = 0
        requests = [e for e in tl if e["operation"] == "tool.call.started"]
        proj_events = {e["payload"].get("tool_call_id"): e["payload"]
                       for e in tl if e["operation"] == "runtime.tool.completed"}

        ev_ids: set[str] = set()
        for entry_es in r.get("evidence_sources") or []:
            if not isinstance(entry_es, dict):
                continue
            for s in entry_es.get("sources", []) or []:
                ref = s.get("reference", {}) if isinstance(s, dict) else {}
                if ref.get("internal_message_id"):
                    ev_ids.add(ref["internal_message_id"])
        cited = set()
        for m in r.get("answer_cited_messages") or []:
            if isinstance(m, str):
                cited.add(m)
            elif isinstance(m, dict) and m.get("internal_message_id"):
                cited.add(m["internal_message_id"])

        run_calls = []
        for req_ev in requests:
            tool = req_ev["payload"].get("tool_name")
            if tool not in ("lexical_search", "semantic_search", "search_messages"):
                continue
            request = req_ev["payload"].get("request") or {}
            tcid = req_ev["payload"].get("tool_call_id")
            rec_call = rec_calls.get(tcid)
            if rec_call is None:
                # older traces carry no tool_call_id; align by chronological position + tool name
                while rec_pos < len(rec_ordered) and rec_ordered[rec_pos].get("tool_name") != tool:
                    rec_pos += 1
                if rec_pos < len(rec_ordered):
                    rec_call = rec_ordered[rec_pos]
                    rec_pos += 1
                else:
                    rec_call = {}
            proj = proj_events.get(tcid, {})
            t1 = time.time()
            try:
                if tool in ("lexical_search", "search_messages"):
                    inp = SearchMessagesInput(
                        keyword=request["keyword"],
                        session_ids=tuple(request["session_ids"]) if request.get("session_ids") else None,
                        start_timestamp=request.get("start_timestamp"),
                        end_timestamp=request.get("end_timestamp"),
                        time_range=request.get("time_range"),
                        sender_user_ids=tuple(request["sender_user_ids"]) if request.get("sender_user_ids") else None,
                        message_types=tuple(request["message_types"]) if request.get("message_types") else None,
                        limit=request.get("limit") or 20,
                        context_before=request.get("context_before") or 0,
                        context_after=request.get("context_after") or 0,
                    )
                    result = lex_cap.execute(inp, scope)
                    q = result.query
                    returned_ids = [h.message.internal_message_id for h in result.hits]
                    expanded_ids = [m.internal_message_id for m in result.expanded_messages]
                    union_sql, parameters = repo._lexical_match_union(q, scored=True)
                    full_rows = repo._connection.execute(
                        f"{union_sql} ORDER BY lexical_score ASC, timestamp ASC, missing_seq ASC, "
                        "order_seq ASC, internal_message_id ASC", parameters).fetchall()
                    full_ids = [row["internal_message_id"] for row in full_rows]
                    full_rank = {mid: i + 1 for i, mid in enumerate(full_ids)}
                    call_rec = {
                        "label": label, "case": cid, "arm": arm, "tool": "lexical",
                        "keyword": request.get("keyword"), "limit": q.limit,
                        "terms": list(q.terms),
                        "resolved_start": q.start_timestamp, "resolved_end": q.end_timestamp,
                        "total_hits": result.total_hits, "returned": len(result.hits),
                        "expanded": len(result.expanded_messages),
                        "projection_truncated": proj.get("projection_truncated"),
                        "projected_messages": proj.get("projected_messages"),
                        "omitted_hit_messages": proj.get("omitted_hit_messages"),
                        "omitted_context_messages": proj.get("omitted_context_messages"),
                        "recorded_direct_hit_count": rec_call.get("direct_hit_count"),
                        "recorded_truncated": rec_call.get("truncated"),
                        "recorded_omitted_direct": rec_call.get("omitted_direct_ids"),
                        "remaining_budget": (proj.get("tool_result_budget") or {}).get(
                            "remaining_run_tool_evidence_budget_after_call"),
                        "full_rank": full_rank, "returned_ids": returned_ids,
                        "expanded_ids": expanded_ids,
                        "elapsed": round(time.time() - t1, 3),
                    }
                    rdh = rec_call.get("direct_hits") or []
                    if rdh:
                        rec_ids = [d["internal_message_id"] for d in rdh]
                        match_n = sum(1 for a, b in zip(returned_ids, rec_ids) if a == b)
                        fidelity["lexical_checked"] += 1
                        if match_n == len(rec_ids) or set(rec_ids) <= set(returned_ids):
                            fidelity["lexical_match"] += 1
                        elif len(fidelity["lex_mismatch_detail"]) < 10:
                            fidelity["lex_mismatch_detail"].append({
                                "label": label, "keyword": request.get("keyword"),
                                "first_diff": next((i for i, (a, b) in enumerate(zip(returned_ids, rec_ids)) if a != b), None),
                                "replay_n": len(returned_ids), "rec_n": len(rec_ids)})
                else:
                    inp = SemanticSearchInput(
                        query=request["query"],
                        session_ids=tuple(request["session_ids"]) if request.get("session_ids") else None,
                        start_timestamp=request.get("start_timestamp"),
                        end_timestamp=request.get("end_timestamp"),
                        time_range=request.get("time_range"),
                        sender_user_ids=tuple(request["sender_user_ids"]) if request.get("sender_user_ids") else None,
                        message_types=tuple(request["message_types"]) if request.get("message_types") else None,
                        source_message_id=request.get("source_message_id"),
                        reply_to_source_message_id=request.get("reply_to_source_message_id"),
                        limit=request.get("limit") or 20,
                        context_before=request.get("context_before") or 0,
                        context_after=request.get("context_after") or 0,
                        dense_top_k=request.get("dense_top_k") or 40,
                    )
                    result = sem_cap.execute(inp, scope)
                    q = result.query
                    pool = min(max(q.dense_top_k, (q.limit or 20) * 4), 1000)
                    qvec = provider.embed_query(q.query)
                    pool_cands = store.dense_search(
                        sem_retrieval.identity, qvec, pool,
                        session_ids=q.session_ids,
                        start_timestamp=q.start_timestamp, end_timestamp=q.end_timestamp)
                    pool_rows = [{"chunk_id": c.chunk_id, "dense_rank": c.dense_rank,
                                  "parent_start": c.parent_start_message_id,
                                  "parent_end": c.parent_end_message_id,
                                  "distance": c.distance} for c in pool_cands]
                    accepted_chunk_ids = [h.chunk_id for h in result.hits]
                    expanded_ids = [m.internal_message_id for m in result.expanded_messages]
                    details = result.metadata.details
                    sem_returned_ids = [h.start_message_id for h in result.hits]
                    call_rec = {
                        "label": label, "case": cid, "arm": arm, "tool": "semantic",
                        "query": request.get("query"), "limit": q.limit, "dense_top_k": q.dense_top_k,
                        "resolved_start": q.start_timestamp, "resolved_end": q.end_timestamp,
                        "pool": pool, "pool_returned": len(pool_cands),
                        "pool_exhausted": details.get("dense_candidates_returned", 0) >= pool,
                        "accepted_candidates": details.get("accepted_candidates"),
                        "literal_candidate_count": details.get("literal_candidate_count"),
                        "expansion_truncated": result.truncated,
                        "expanded_count": result.returned_messages,
                        "projection_truncated": proj.get("projection_truncated"),
                        "projected_messages": proj.get("projected_messages"),
                        "omitted_hit_messages": proj.get("omitted_hit_messages"),
                        "recorded_direct_hit_count": rec_call.get("direct_hit_count"),
                        "recorded_truncated": rec_call.get("truncated"),
                        "remaining_budget": (proj.get("tool_result_budget") or {}).get(
                            "remaining_run_tool_evidence_budget_after_call"),
                        "pool_rows": pool_rows,
                        "accepted_chunk_ids": accepted_chunk_ids,
                        "expanded_ids": expanded_ids,
                        "elapsed": round(time.time() - t1, 3),
                    }
                    sem_stats["total"] += 1
                    if call_rec["pool_exhausted"]:
                        sem_stats["pool_exhausted"] += 1
                    if details.get("accepted_candidates") == q.limit:
                        sem_stats["accepted_eq_limit"] += 1
                    if result.truncated:
                        sem_stats["expansion_truncated"] += 1
                    rdh = rec_call.get("direct_hits") or []
                    if rdh:
                        # record direct_hits/expanded_ids = tool-result message items split by is_hit
                        rec_ids = [d["internal_message_id"] for d in rdh] + list(rec_call.get("expanded_ids") or [])
                        replay_set = set(expanded_ids)
                        rec_set = set(rec_ids)
                        fidelity["semantic_checked"] += 1
                        if rec_set <= replay_set:  # record capped at 50+50; superset = faithful
                            fidelity["semantic_match"] += 1
                        elif len(fidelity["sem_mismatch_detail"]) < 10:
                            fidelity["sem_mismatch_detail"].append({
                                "label": label, "query": (request.get("query") or "")[:60],
                                "replay_n": len(replay_set), "rec_n": len(rec_set),
                                "inter": len(replay_set & rec_set),
                                "replay_only": sorted(replay_set - rec_set)[:5],
                                "rec_only": sorted(rec_set - replay_set)[:5]})
                run_calls.append(call_rec)
            except Exception as exc:  # noqa: BLE001
                run_calls.append({"label": label, "case": cid, "arm": arm, "tool": tool,
                                  "error": f"{type(exc).__name__}: {exc}", "request": request})

        # ---- fact-level classification -------------------------------------
        for fact in facts_by_case[cid]:
            tids = gt_ids(fact)
            meta0 = next((m for m in fact["resolved"].values() if m.get("timestamp")), {})
            ts_val = meta0.get("timestamp")
            content = meta0.get("content") or ""
            adopted = any(id_match(tids, e) for e in ev_ids) or any(id_match(tids, c) for c in cited)
            in_recorded_dh = any(
                id_match(tids, d["internal_message_id"])
                for c in rec_calls.values() for d in (c.get("direct_hits") or []))
            layers = []
            detail = []
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
                        if ts_val and c["resolved_start"] and ts_val < c["resolved_start"]:
                            lay = "L0_time_scope"
                        elif ts_val and c["resolved_end"] and ts_val >= c["resolved_end"]:
                            lay = "L0_time_scope"
                        else:
                            terms = [t.casefold() for t in c.get("terms", [])]
                            kw = (c.get("keyword") or "").casefold()
                            hit = any(t and t in content.casefold() for t in terms) or (kw and kw in content.casefold())
                            lay = "L2_fts_miss_with_overlap" if hit else "L1_no_lexical_overlap"
                        layers.append(lay)
                        detail.append({"call": c.get("keyword"), "layer": lay, "rank": None,
                                       "total_hits": c.get("total_hits")})
                    elif fr > (c["limit"] or 20):
                        layers.append("L3_window_truncated")
                        detail.append({"call": c.get("keyword"), "layer": "L3_window_truncated",
                                       "rank": fr, "limit": c["limit"], "total_hits": c.get("total_hits")})
                    else:
                        pos = None
                        for tid in tids:
                            if tid in c["expanded_ids"]:
                                pos = c["expanded_ids"].index(tid)
                                break
                        vis = True
                        if c.get("projection_truncated") and pos is not None:
                            vis = pos < (c.get("projected_messages") or 0)
                        lay = "L5_returned" if vis else "L4_budget_crop"
                        layers.append(lay)
                        detail.append({"call": c.get("keyword"), "layer": lay, "rank": fr,
                                       "pos_in_expanded": pos,
                                       "projected": c.get("projected_messages")})
                else:
                    covering = []
                    for pr in c.get("pool_rows", []):
                        ps, pe = nums(pr["parent_start"] or ""), nums(pr["parent_end"] or "")
                        for tid in tids:
                            tn = nums(tid)
                            common = tn & (ps | pe | nums(pr["chunk_id"]))
                            ps_n = int(next(iter(ps))) if len(ps) == 1 else None
                            pe_n = int(next(iter(pe))) if len(pe) == 1 else None
                            tid_n = [int(x) for x in tn]
                            cover = False
                            if ps_n and pe_n and tid_n:
                                v = tid_n[0]
                                cover = ps_n <= v <= pe_n
                            if cover or common:
                                covering.append((pr["chunk_id"], pr["dense_rank"]))
                                break
                    if not covering:
                        lay = "S1_pool_miss"
                        detail.append({"call": (c.get("query") or "")[:60], "layer": lay, "pool": c.get("pool")})
                    else:
                        best_rank = min(r for _, r in covering)
                        accepted = any(cid_ in c["accepted_chunk_ids"] for cid_, _ in covering)
                        if not accepted:
                            lay = "S2_rank_cut"
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
                            if pos is None:
                                lay = "S3_projection_gap"
                            else:
                                vis = True
                                if c.get("projection_truncated") and pos is not None:
                                    vis = pos < (c.get("projected_messages") or 0)
                                lay = "L5_returned" if vis else "L4_budget_crop"
                        detail.append({"call": (c.get("query") or "")[:60], "layer": lay,
                                       "best_dense_rank": best_rank, "pool": c.get("pool")})
                    layers.append(lay)
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
            fact_records.append({
                "case": cid, "arm": arm, "run_idx": idx, "fact_id": fact["fact_id"],
                "evidence": fact["evidence"], "layer": final_layer,
                "detail": detail[:6], "n_calls": len(run_calls),
            })

        call_records.extend(run_calls)
        if (ri + 1) % 8 == 0:
            print(f"[{ri+1}/{len(runs)}] elapsed {time.time()-t0:.0f}s", flush=True)

    json.dump(call_records, open(OUT / "replay-calls.json", "w"), ensure_ascii=False, default=str)
    json.dump(fact_records, open(OUT / "replay-facts.json", "w"), ensure_ascii=False, default=str)
    summary = {
        "n_runs": len(runs), "n_calls": len(call_records),
        "call_error_count": sum(1 for c in call_records if "error" in c),
        "semantic_truncation": dict(sem_stats),
        "fidelity": fidelity,
        "fact_layer_counts": dict(Counter(f["layer"] for f in fact_records)),
    }
    json.dump(summary, open(OUT / "replay-summary.json", "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
